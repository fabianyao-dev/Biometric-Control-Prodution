"""Sesion de produccion: abrir y cerrar con huella (SesionMixin).

Gestiona el boton del header: pide huella, abre la sesion en BD, refresca el
operador y los totales, y rechaza cerrar con la maquina en marcha. Tambien
reconstruye el estado de la sesion y del paro tras un apagon.
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




class SesionMixin:

    def toggle_sesion(self):
        """Accion del boton de sesion del header (delegada desde la App).

        Sin sesion abre el modal de huella de inicio; con sesion la cierra,
        PERO solo con la maquina detenida: una maquina encendida siempre
        vive dentro de una sesion (al encender entra a Primera pieza y pide
        trabajo), asi que cerrarla en marcha dejaria cortes sin dueno.
        """
        if self._modal_abierto:
            return
        if self.sesion_id is None:
            self._abrir_huella_sesion()
            return
        if not self.controlador.maquina_detenida():
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("No se puede cerrar la sesion")
            caja.setText("La maquina esta EN MARCHA.\n\nDetenla con el boton de maquina antes de cerrar la sesion.")
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            log.warning("Cierre de sesion bloqueado: la maquina esta en "
                        "marcha")
            return
        self._abrir_huella_cierre()

    def _abrir_huella_sesion(self):
        """Modal de huella para INICIAR sesion (cualquier operador registrado).

        Solo identidad: aqui NO se toca el relevo ni el modo Primera pieza;
        eso lo hace el boton de maquina al encender.
        """
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="INICIAR SESION",
                mensaje="Coloca tu huella para iniciar la sesion.",
                on_autenticado=self._sesion_abierta,
                on_cancelar=lambda: self._estado(
                    "Inicio de sesion cancelado.", "info"
                ),
                mostrar_dev=config.MODO_DEV,
                on_dev=self._sesion_dev,
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _sesion_dev(self):
        """Inicia sesion con el operador temporal de desarrollo (sin lector)."""
        from src.database import obtener_operador_temporal
        id_op, nombre = obtener_operador_temporal()
        self._sesion_abierta(id_op, nombre)
        self._estado(f"Acceso DEV sin lector como '{nombre}'.", "exito")
        log.info("Acceso DEV sin lector iniciado como %s (%s)", nombre, id_op)

    def _sesion_abierta(self, id_operador, nombre, causa_id=None):
        """Sesion abierta: reinicia el contador (el TOTAL es por sesion).

        La maquina NO arranca aqui: queda DETENIDA hasta que el operador
        pulse el boton de maquina.
        """
        self.sesion_id = abrir_sesion(id_operador)
        self.operador_id = id_operador
        self.operador_nombre = nombre
        self.controlador.reset_conteo()
        self._en_paro = False
        self._paro_idle_triggado = False
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(
            f"Sesion iniciada por {nombre}. Enciende la maquina para "
            "comenzar.", "exito",
        )
        log.info("Sesion %s abierta para %s", self.sesion_id, nombre)
        # Desde el login corre la espera implicita hasta PLAY o el primer QR.
        self._abrir_espera_trabajo()

    def _cerrar_sesion_interrumpida(self):
        """Cierra la sesion 'Activa' heredada de un apagon. NO la recupera.

        Los datos YA estan guardados: el checkpoint de 30 s
        (`_checkpoint_cortes`, `config.CORTES_GUARDAR_INTERVALO_MS`) dejo
        `sesiones_produccion.total_cortes` y `trabajos.cortes_detectados` en
        la BD, asi que tras un corte de luz no hay nada que reconstruir ni que
        pedir autorizacion. Aqui solo se hace la limpieza para que el
        operador entre con una sesion NUEVA:

        1. El trabajo en curso se CONFIRMA con lo detectado (se paso tal cual:
           aqui no hay conteo vivo todavia). Las piezas ya se cortaron y no
           habra quien las vuelva a contar, asi que no se dejan solo como
           detectadas; si el folio llega a la meta queda 'Cerrado', si no
           'Abierto' con su parcial y su segmento cerrado. Se retoma
           escaneando su QR, que lo reactiva desde `cortes_confirmados`.
        2. El paro en curso se cierra con la causa implicita "Computadora
           apagada": se fue la luz y nadie autorizo nada, pero el reporte no
           debe mostrar un paro "(sin causa registrada)".
        3. La sesion pasa a 'Finalizada' con el total del checkpoint.

        La vista queda deliberadamente SIN sesion (`sesion_id=None`): el
        header pide huella de inicio y el operador abre un folio desde cero,
        con su conteo arrancando en 0. El latch PAUSE inicial del HAL
        (`ModbusController._aplicar_paro_inicial`) ya deja la maquina
        fisicamente detenida.
        """
        sesion = obtener_sesion_interrumpida()
        if not sesion:
            return
        sesion_id = sesion["id"]
        operador_id = sesion["operador_id"]
        nombre = sesion["nombre"]
        total = sesion["total_cortes"] or 0
        # 1) Parcial del trabajo: se re-pasa el valor del checkpoint (aun no
        # hay contador vivo que lo supere) y se CONFIRMA, no solo se pausa.
        trabajo = None
        estado_trabajo = None
        confirmados = 0
        # El folio se guarda ANTES de cerrar el trabajo: `confirmar_trabajo_
        # por_apagon` le pone `fecha_fin`, asi que despues
        # `obtener_trabajo_abierto` ya no lo devolveria y el paro del corte de
        # luz saldria sin trabajo aunque la maquina cortara con el cargado.
        folio_en_curso = None
        try:
            trabajo = obtener_trabajo_abierto(sesion_id)
            if trabajo is not None:
                folio_en_curso = trabajo["folio"]
                detectados = trabajo["cortes_detectados"] or 0
                ok, estado_trabajo, confirmados = confirmar_trabajo_por_apagon(
                    trabajo["folio"], detectados
                )
                if not ok:
                    raise RuntimeError(estado_trabajo)
                log.info("Trabajo %s queda %s con %s/%s piezas (sesion %s "
                         "interrumpida: corte de luz)", trabajo["folio"],
                         estado_trabajo, confirmados,
                         trabajo["cantidad_total"], sesion_id)
        except Exception:  # noqa: BLE001 - la limpieza no debe tumbar el arranque
            log.warning("No se pudo cerrar el trabajo de la sesion %s",
                        sesion_id, exc_info=True)
            estado_trabajo = None
        # 2) Paro en curso (Primera pieza, 'Esperando trabajo' o el del boton
        # PARO): se cierra con la causa implicita del corte de luz para no
        # dejar filas 'En curso' ni "(sin causa registrada)" sobre una sesion
        # ya Finalizada.
        try:
            paro = paro_en_curso(sesion_id)
            if paro is not None:
                causa_id = self._causa_id("Computadora apagada")
                if causa_id is None:
                    log.warning("Causa 'Computadora apagada' inactiva o "
                                "inexistente; paro %s sin causa", paro)
                finalizar_paro(paro, causa_id, operador_id)
                log.info("Paro %s cerrado por corte de luz (sesion %s, causa "
                         "%s)", paro, sesion_id, causa_id)
            else:
                # La maquina CORRIA cuando se fue la luz: no habria fila en
                # curso que cerrar, pero el hueco quedaria sin medir. Se
                # escribe el paro entero desde el ultimo corte/arranque
                # conocido hasta el reinicio.
                self._reconstruir_paro_apagon(
                    sesion_id, operador_id, sesion["ultimo_corte"],
                    folio=folio_en_curso,
                )
        except Exception:  # noqa: BLE001 - idem
            log.warning("No se pudo cerrar el paro en curso de la sesion %s",
                        sesion_id, exc_info=True)
        # 3) La sesion queda cerrada con el total del checkpoint.
        try:
            cerrar_sesion(sesion_id, total)
        except Exception:  # noqa: BLE001 - idem
            log.warning("No se pudo cerrar la sesion %s", sesion_id,
                        exc_info=True)
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        if trabajo is not None and estado_trabajo == ESTADO_CERRADO:
            self._estado(
                f"Corte de luz: la sesion de {nombre} se cerro con {total} "
                f"cortes. El trabajo {trabajo['folio']} completo la meta y se "
                f"cerro con {confirmados}/{trabajo['cantidad_total']} piezas "
                "confirmadas. Inicia sesion para el siguiente.",
                "procesando",
            )
        elif trabajo is not None:
            self._estado(
                f"Corte de luz: la sesion de {nombre} se cerro con {total} "
                f"cortes. El trabajo {trabajo['folio']} sigue abierto con "
                f"{confirmados}/{trabajo['cantidad_total']} piezas "
                "confirmadas: inicia sesion y escanea su QR para continuar.",
                "procesando",
            )
        else:
            self._estado(
                f"Corte de luz: la sesion de {nombre} se cerro con {total} "
                "cortes. Inicia sesion para empezar de nuevo.",
                "procesando",
            )
        log.info("Sesion %s interrumpida cerrada por corte de luz (operador "
                 "%s, %s cortes)", sesion_id, nombre, total)

    def _reconstruir_paro_apagon(self, sesion_id, operador_id, ultimo_corte,
                                  folio=None):
        """Escribe el paro del corte de luz cuando la maquina CORRIA.

        Cubre el caso que `paro_en_curso` no alcanza: si no habia ninguna fila
        en curso, la maquina estaba EN MARCHA (contando) y no en paro. Sin
        esto, el tiempo desde el ultimo corte hasta el reinicio no aparece en
        ningun lado y el reporte sale como si la maquina hubiera producido
        todo ese tiempo sin interrupcion.

        El INTERVALO va del ultimo corte (o arranque) conocido al reinicio, no
        del reinicio: medir desde el reinicio daria un paro de cero. `fin` es
        el instante en que se detecto el apagon, para que el hueco no se
        alargue con las horas que el equipo estuvo apagado.

        `folio` lo pasa el llamador y es el trabajo que estaba ABIERTO al
        cortarse la luz. No se vuelve a consultar `obtener_trabajo_abierto`
        porque para este punto ese trabajo ya fue cerrado por
        `confirmar_trabajo_por_apagon` y la consulta exigiria `fecha_fin` nula,
        de ahi que antes saliera 'sin trabajo'. Sin folio, el paro queda sin
        trabajo asociado.
        """
        if not ultimo_corte:
            # Sin ancla no hay intervalo honesto: se cae a `fin` (paro de un
            # instante) en vez de medir desde el inicio de la sesion, que
            # inventaria horas de paro que el operador no hizo.
            log.warning("Sesion %s sin 'ultimo_corte' registrado; el paro del "
                        "corte de luz se registra de duracion cero", sesion_id)
        fin = ahora_local()
        try:
            causa_id = self._causa_id("Computadora apagada")
            paro_id = crear_paro_por_apagon(
                sesion_id, folio, ultimo_corte, operador_id, causa_id, fin=fin,
            )
            log.info("Paro %s reconstruido por corte de luz (sesion %s, folio "
                     "%s, desde %s hasta %s)", paro_id, sesion_id, folio,
                     ultimo_corte, fin)
            return paro_id
        except Exception:  # noqa: BLE001 - la limpieza no debe tumbar el arranque
            log.warning("No se pudo reconstruir el paro del corte de luz de "
                        "la sesion %s", sesion_id, exc_info=True)
            return None

    def _abrir_huella_cierre(self):
        """Cierre de sesion: requiere autorizacion del operador de la sesion
        o de un rol con autoridad (admin/supervisor)."""
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="CERRAR SESION",
                mensaje="Coloca tu huella para cerrar la sesion.",
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._cierre_autenticado,
                on_cancelar=lambda: self._estado("Cierre cancelado.", "info"),
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _cierre_autenticado(self, id_operador, nombre, causa_id=None):
        sesion_id = self.sesion_id
        if not self._apagar_maquina(autorizador_id=id_operador):
            return
        log.info("Sesion %s cerrada por %s", sesion_id, nombre)

