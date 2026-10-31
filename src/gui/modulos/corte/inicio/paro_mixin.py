"""Modo PARO: autorizacion, pausa y salida (ParoMixin).

Abre el selector de causa/zona, pide la huella que autoriza el paro, lo deja
abierto en BD y lo cierra en el segundo paso "SALIR DE PARO". Segun la causa y
la zona, la maquina queda detenida o sigue en marcha con el conteo suspendido.
"""

import logging
import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from src import config
from src.database import (
    ESTADO_CERRADO,
    abrir_sesion,
    abrir_trabajo,
    actualizar_cortes_sesion,
    actualizar_detectados,
    ahora_local,
    cerrar_sesion,
    cerrar_trabajo_modalidad,
    confirmar_trabajo_por_apagon,
    crear_paro_por_apagon,
    finalizar_paro,
    iniciar_paro,
    listar_causas_paro,
    obtener_rol_operador,
    obtener_sesion_interrumpida,
    obtener_trabajo_abierto,
    paro_en_curso,
    pausar_trabajo,
    recortar_inicio_segmento,
    registrar_ultimo_corte,
    rol_tiene_permiso_operador,
    roles_con_permiso,
)
from src.gui.componentes.huella_modal import HuellaModal
from ..componentes.selector_causas import SelectorCausaZona
from ..componentes.modalidades_cierre import (
    MODALIDAD_FOLIO,
    ModalidadCierreDialog,
)
from src.gui.componentes.resplandor import Resplandor
from src.gui.componentes.switch import Switch
from src.gui.style import aplicar_estado, aplicar_estilo_boton

log = logging.getLogger(__name__)




class ParoMixin:

    def _boton_paro(self):
        if self.sesion_id is None:
            self._estado("Primero arranca la maquina.", "error")
            return
        if self._modal_abierto:
            return
        if self._modo_mantenimiento:
            # El boton PARO pasa a SALIR DE MANTENIMIENTO (rojo).
            self._salir_modo_mantenimiento()
            return
        if self._modo_paro:
            # Modo PARO: el boton sirve para SALIR del modo (segunda huella),
            # que cierra el paro y deja la maquina ENCENDIDA. Nunca enciende
            # ni apaga aqui.
            self._salir_modo_paro()
            return
        if self._primera_pieza:
            if self._maquina_en_marcha():
                if self._seguro_paro_segundos() is not None:
                    self._estado(
                        "La maquina esta cortando: espera unos segundos "
                        "para parar.",
                        "error",
                    )
                    log.info("PARO en Primera pieza bloqueado por seguro "
                             "anti-corte")
                    return
                self._pausar_maquina()
            return
        if self._maquina_en_marcha():
            if self._seguro_paro_segundos() is not None:
                self._estado(
                    "La maquina esta cortando: espera unos segundos para parar.",
                    "error",
                )
                log.info("PARO bloqueado por seguro anti-corte")
                return
            self._pausar_maquina()
        else:
            # Maquina ya detenida: reabrir autorizacion del paro pendiente
            if self._en_paro:
                self._abrir_paro_autorizacion()

    def _salir_modo_paro(self):
        """SEGUNDO paso del modo paro: pide la huella del operador que cierra
        el paro. Segun la zona, la maquina sigue en marcha (conteo suspendido)
        o se ENCIENDE aqui mismo; en ambos casos el conteo vuelve a la sesion
        (o a Primera pieza si estaba activa)."""
        if self._modal_abierto:
            return
        causa_id = self._modo_paro_causa_id
        zona_id = self._modo_paro_zona_id
        en_marcha = self._modo_paro_maquina_encendida
        mensaje = (
            "Paro finalizado. Coloca tu huella (operador) para reanudar "
            "la produccion. La maquina sigue en marcha."
            if en_marcha else
            "Paro finalizado. Coloca tu huella (operador) para cerrar el "
            "paro y encender la maquina."
        )
        self._pedir_huella_reanudacion(
            causa_id, zona_id,
            titulo="SALIR DE PARO",
            mensaje=mensaje,
            on_autorizado=lambda id_op, nop, causa=None:
                self._modo_paro_finalizado(id_op, nop),
        )

    def _modo_paro_finalizado(self, id_operador, nombre_operador):
        """Cierra el paro del modo PARO: finaliza el paro con su causa y zona,
        reanuda el conteo (o lo deja suspendido si aun hay Primera pieza
        activa) y ENCIENDE la maquina si estaba detenida.

        El encendido va DESPUES de resolver el conteo, para que el primer
        corte tras reanudar cuente de verdad (y no caiga en excluidos por el
        `suspender_conteo` de Primera pieza)."""
        causa_id = self._modo_paro_causa_id
        zona_id = self._modo_paro_zona_id
        en_marcha = self._modo_paro_maquina_encendida
        finalizar_paro(self.paro_id, causa_id, id_operador, zona_id)
        self.paro_id = None
        self._modo_paro = False
        self._modo_paro_causa_id = None
        self._modo_paro_causa_desc = None
        self._modo_paro_zona_id = None
        self._modo_paro_maquina_encendida = False
        self._en_paro = False
        self._paro_idle_triggado = False
        self._paro_inicio_momento = None
        self._ultimo_color_rojo = None
        try:
            if hasattr(self.controlador, "establecer_torre"):
                self.controlador.establecer_torre(False, False, False)
        except Exception:
            pass
        if self._primera_pieza:
            # El conteo sigue suspendido por el propio modo Primera pieza.
            self.controlador.suspender_conteo()
        else:
            self.controlador.retomar_conteo()
        # Salir del paro ENCIENDE la maquina: si la zona la dejo detenida,
        # el operador no tiene que volver a pulsar el boton central.
        if not en_marcha and self.sesion_id is not None:
            self.controlador.reprisar_maquina()
        self.controlador.reiniciar_gracia_inactividad()
        self._refrescar_estado_maquina()
        self._estado(
            f"Fin de paro autorizado por {nombre_operador}. "
            + ("La maquina sigue en marcha." if en_marcha
               else "Maquina encendida."),
            "exito",
        )
        log.info("Salida del modo paro por %s (sesion %s, maquina %s)",
                 nombre_operador, self.sesion_id,
                 "en marcha" if en_marcha else "encendida")

    def _pausar_maquina(self, motivo="manual", inicio_hace_s=None):
        self.controlador.maquina_pausada()
        self._en_paro = True
        # Ancla de la torre: el paro arranca aqui aunque el operador tarde en
        # autorizarlo (pasada la tolerancia se enciende la roja y la alarma).
        if self._paro_inicio_momento is None:
            self._paro_inicio_momento = time.time()
        self.paro_id = iniciar_paro(self.sesion_id, self._folio_activo(),
                                    inicio_hace_s=inicio_hace_s)
        self._refrescar_estado_maquina()
        log.info("Paro %s registrado (%s)", self.paro_id, motivo)
        self._estado("Maquina en PARO. Indica el motivo y autoriza.", "procesando")
        self._abrir_paro_autorizacion()

    def _abrir_paro_autorizacion(self):
        causas = listar_causas_paro(activas_solo=True)
        if not causas:
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Sin causas")
            caja.setText("No hay causas de paro configuradas. Ve a Administracion.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            self._estado("Sin causas de paro; maquina detenida.", "error")
            return

        # Flujo de 2 modales (decision de diseno): PRIMERO se elige causa (+
        # zona si la requiere) en un selector; al CONFIRMAR se abre el SEGUNDO
        # modal que pide la huella de reanudacion/autorizacion.
        def _on_confirmado(causa_id, causa_desc, zona_id, zona_nombre,
                           zona_maquina=False):
            if self._es_causa_mantenimiento(causa_id):
                # Flujo Mantenimiento: PRIMERO huella del personal de
                # mantenimiento y LUEGO la reanudacion del operador.
                self._pedir_huella_mantenimiento(
                    lambda id_mant, nombre_mant, causa=None:
                        self._mantenimiento_entrada_paso_operador(
                            id_mant, nombre_mant, causa_id, zona_id,
                            causa_desc, zona_nombre
                        )
                )
            else:
                # Los DOS modales del paro llevan SIEMPRE el mismo titulo,
                # haya zona o no: 1) 'AUTORIZACION DEL PARO' (elegir causa y
                # zona), 2) 'AUTORIZACION' (la huella que autoriza). Antes
                # el 2º decia 'REANUDACION' con zona y 'AUTORIZAR
                # REANUDACION' sin ella, que no describian lo que hace.
                self._pedir_huella_reanudacion(
                    causa_id, zona_id, causa_desc, zona_nombre,
                    titulo="AUTORIZACION", zona_maquina=zona_maquina,
                )

        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="AUTORIZACION DEL PARO",
                mensaje="Maquina en PARO. Indica la causa del paro (y la zona).",
                # Un paro normal NO se puede cancelar hasta confirmar la
                # causa: quien paro, autoriza o sale de ahi.
                mostrar_cancelar=False,
                cerrable=False,
                pedir_causa=True,
                selector_causas_cls=SelectorCausaZona,
                on_confirmado=_on_confirmado,
                on_cancelar=lambda: self._estado(
                    "Paro NO autorizado; maquina detenida.", "error"
                ),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _pedir_huella_reanudacion(self, causa_id=None, zona_id=None,
                                  causa_desc=None, zona_nombre=None,
                                  titulo="AUTORIZACION", mensaje=None,
                                  on_autorizado=None, zona_maquina=False):
        """SEGUNDO modal del flujo de paro: pide la huella que AUTORIZA el
        paro, ya con la causa (+ zona) elegida en el primer modal
        ('AUTORIZACION DEL PARO').

        En el flujo de Mantenimiento es el paso del OPERADOR (el personal de
        mantenimiento ya se valido primero): `on_autorizado` recibe el
        id/nombre del operador y `titulo`/`mensaje` van personalizados.
        """
        if mensaje is None:
            detalle = causa_desc or "(sin causa)"
            if zona_nombre:
                detalle += f" - {zona_nombre}"
            mensaje = f"Maquina en PARO. Causa: {detalle}. Coloca tu huella."

        # La causa/zona ya elegidas se pasan como `causa_id`/`zona_id` al
        # autorizador; el validador (permiso) no necesita la causa.
        def _autorizado(id_operador, nombre, causa=None):
            if on_autorizado is not None:
                on_autorizado(id_operador, nombre, causa)
            else:
                self._autorizado_autenticado(
                    id_operador, nombre, causa_id, zona_id, zona_maquina,
                    zona_nombre, causa_desc
                )

        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo=titulo,
                mensaje=mensaje,
                # Un paro normal NO se puede cancelar hasta autorizar.
                mostrar_cancelar=False,
                cerrable=False,
                validador=self._validar_autorizacion_paro,
                on_autenticado=_autorizado,
                on_cancelar=lambda: self._estado(
                    "Paro NO autorizado; maquina detenida.", "error"
                ),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _validar_autorizacion_paro(self, id_operador, nombre, causa_id=None):
        """Solo autoriza (reanudar paro, cerrar sesion o reanudar la
        produccion tras mantenimiento) el dueno de la sesion o un rol con el
        permiso 'autorizar_supervision' (Supervisor/Admin; gestionado en
        Administracion). Mantenimiento NO autoriza este modal."""
        if id_operador == self.operador_id:
            return True, None
        if rol_tiene_permiso_operador(id_operador, "autorizar_supervision"):
            return True, None
        return False, (
            "Solo el operador de la sesión, Supervisor o Admin "
            "puede autorizar esta acción"
        )

    def _autorizado_autenticado(self, id_operador, nombre, causa_id=None,
                                zona_id=None, zona_maquina=False,
                                zona_nombre=None, causa_desc=None):
        """Paro autorizado: entra al MODO PARO (unico, para toda causa salvo
        'mantenimiento', que tiene su propio modo).

        El paro queda ABIERTO en BD y se cierra en un SEGUNDO paso
        ('SALIR DE PARO', con huella del operador). Lo unico que depende de la
        zona es la maquina:

        - `zona_maquina=True` (la causa requiere zona y la zona tiene marcada
          'maquina encendida'): la maquina REPRENDE con el conteo suspendido
          (los cortes van a excluidos, como en Mantenimiento).
        - `zona_maquina=False` (zona normal o causa que no requiere zona): la
          maquina se queda DETENIDA donde la paro `_pausar_maquina` la dejo.
        """
        self._modo_paro = True
        self._modo_paro_causa_id = causa_id
        self._modo_paro_causa_desc = (
            causa_desc or self._causa_descripcion(causa_id) or "(sin causa)"
        )
        self._modo_paro_zona_id = zona_id
        self._modo_paro_maquina_encendida = bool(zona_maquina)
        self._en_paro = True
        self._paro_idle_triggado = False
        # El ancla de la torre ya la fijo `_pausar_maquina` (o la fija
        # `_actualizar_tolerancia_paro` en el siguiente ciclo): autorizar el
        # paro NO reinicia la tolerancia ni rearma la alarma.
        if zona_maquina:
            self.controlador.reprisar_maquina()
            self.controlador.suspender_conteo()
        self._refrescar_estado_maquina()
        zona_nom = zona_nombre or (str(zona_id) if zona_id is not None else None)
        if zona_maquina:
            self._estado(
                f"Paro autorizado por {nombre}. Zona '{zona_nom}' deja la "
                "maquina en marcha; los cortes NO cuentan. Pulsa SALIR DE "
                "PARO al terminar.",
                "procesando",
            )
        else:
            self._estado(
                f"Paro autorizado por {nombre}. Maquina detenida. Pulsa "
                "SALIR DE PARO al terminar.",
                "procesando",
            )
        log.info("Paro %s autorizado por %s en la sesion %s (causa %s, zona "
                 "%s, maquina %s)", self.paro_id, nombre, self.sesion_id,
                 causa_id, zona_id, "en marcha" if zona_maquina else "detenida")

    def _causa_id(self, descripcion):
        """Id de una causa por su descripcion (comparacion tolerante a
        mayusculas/espacios). None si no existe o esta inactiva: la columna
        `causa_id` de `paros_produccion` es nullable y el reporte muestra
        "(sin causa registrada)". Las llama el sistema, nunca el operador."""
        objetivo = str(descripcion).strip().lower()
        for causa in listar_causas_paro(activas_solo=True):
            if str(causa["descripcion"]).strip().lower() == objetivo:
                return causa["id"]
        return None

    def _causa_descripcion(self, causa_id):
        """Descripcion de una causa por su id, o None si no existe. Se consulta
        SIN filtrar por activo: una causa puede desactivarse mientras el paro
        sigue abierto y el estado del modo PARO debe seguir mostrandola."""
        if causa_id is None:
            return None
        for causa in listar_causas_paro(activas_solo=False):
            if causa["id"] == causa_id:
                return str(causa["descripcion"])
        return None

    def _paro_real_abierto(self):
        """True si hay un paro registrado que la torre debe vigilar.

        Cubre el PARO antes y despues de autorizarlo (`_en_paro` /
        `_modo_paro`) y el modo Mantenimiento: son paros que alguien tiene
        que resolver. NO cubre la espera de trabajo ni Primera pieza con la
        maquina apagada, donde no hay paro, solo la maquina esperando el
        siguiente folio.
        """
        return bool(self._en_paro or self._modo_paro
                    or self._modo_mantenimiento)

