"""Modo MANTENIMIENTO con doble validacion (MantenimientoMixin).

Para entrar y salir pide primero la huella de un rol con permiso
'autorizar_mantenimiento' y luego la del operador de la sesion. La maquina
sigue en marcha con el conteo suspendido y aplica el seguro anti-corrida.
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




class MantenimientoMixin:

    def _es_causa_mantenimiento(self, causa_id) -> bool:
        return (causa_id is not None
                and causa_id == self._causa_mantenimiento_id())

    def _causa_mantenimiento_id(self):
        return self._causa_id("mantenimiento")

    def _validar_mantenimiento(self, id_operador, nombre, causa_id=None):
        """Solo personal de mantenimiento autorizado valida la entrada, la
        salida y la confirmacion de corrida del modo."""
        if rol_tiene_permiso_operador(id_operador, "autorizar_mantenimiento"):
            return True, None
        return False, (
            "Solo el personal de mantenimiento puede validar esta acción"
        )

    def _pedir_huella_mantenimiento(self, on_autenticado, titulo="AUTORIZACION MANTENIMIENTO"):
        """PRIMER modal del flujo de Mantenimiento: huella del personal
        autorizado. El `on_autenticado` recibe (id_mant, nombre_mant,
        causa_id)."""
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo=titulo,
                mensaje=(
                    "Coloca la huella de PERSONAL DE MANTENIMIENTO "
                    "para validar."
                ),
                validador=self._validar_mantenimiento,
                on_autenticado=on_autenticado,
                on_cancelar=lambda: self._estado(
                    "Autorizacion de mantenimiento cancelada.", "info"
                ),
                mostrar_cancelar=True,
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _mantenimiento_entrada_paso_operador(self, id_mant, nombre_mant,
                                             causa_id, zona_id, causa_desc,
                                             zona_nombre):
        """Tras la huella de mantenimiento: la del OPERADOR REANUDA el paro y
        arranca el modo Mantenimiento (la maquina sigue en marcha)."""
        self._pedir_huella_reanudacion(
            causa_id, zona_id, causa_desc, zona_nombre,
            titulo="AUTORIZACION OPERADOR",
            mensaje=(
                "Mantenimiento autorizado. Coloca tu huella "
                "(operador) para reanudar y entrar en Mantenimiento."
            ),
            on_autorizado=lambda id_op, nop, causa=None:
                self._modo_mantenimiento_iniciado(
                    id_op, nop, id_mant, nombre_mant, causa_id, zona_id
                )
        )

    def _modo_mantenimiento_iniciado(self, id_operador, nombre_operador,
                                     id_mant, nombre_mant, causa_id, zona_id):
        """Entra al modo Mantenimiento.

        El paro abierto (PARO) queda ABIERTO como paro del modo y se
        finaliza al salir con la causa fija 'mantenimiento'. La maquina se
        REACTIVA (sigue en marcha) y el conteo se suspende: los cortes van a
        excluidos (solo memoria), como en Primera pieza.
        """
        self.controlador.reprisar_maquina()
        self.controlador.suspender_conteo()
        self._mantenimiento_zona_id = zona_id
        self._en_paro = False
        self._paro_idle_triggado = False
        self._modo_mantenimiento = True
        self._fijar_switch(False)
        # Baseline nuevo del seguro anti-corrida (descarta muestras de un
        # modo anterior).
        self._muestras_rafaga.clear()
        self._ultimo_excluidos = self.controlador.cortes_excluidos()
        self._refrescar_estado_maquina()
        self._estado(
            f"Modo Mantenimiento autorizado por {nombre_operador} y "
            f"{nombre_mant}. La maquina sigue en marcha; los cortes NO "
            "cuentan. Pulsa SALIR DE MANTENIMIENTO al terminar.",
            "procesando",
        )
        log.info("Modo Mantenimiento iniciado (paro %s) validado por %s y %s "
                 "en la sesion %s", self.paro_id, nombre_operador, nombre_mant,
                 self.sesion_id)

    def _salir_modo_mantenimiento(self):
        """Salida del modo: doble validacion con PRIMERO la huella del
        personal de mantenimiento y LUEGO la del operador que reanuda. La
        maquina SIGUE EN MARCHA; solo se cierra el paro del modo y el conteo
        vuelve a la sesion.
        """
        if self._modal_abierto:
            return
        self._pedir_huella_mantenimiento(
            self._salir_mantenimiento_paso_operador,
            titulo="REANUDACION MANTENIMIENTO"
        )

    def _salir_mantenimiento_paso_operador(self, id_mant, nombre_mant,
                                           causa_id=None):
        """2da huella de la salida: el OPERADOR reanuda la produccion."""
        self._pedir_huella_reanudacion(
            titulo="REANUDACION OPERADOR",
            mensaje=(
                "Mantenimiento finalizado. Coloca tu huella (operador) "
                "para reanudar la produccion."
            ),
            on_autorizado=lambda id_op, nop, causa=None:
                self._mantenimiento_finalizado(
                    id_mant, nombre_mant, id_op, nop
                )
        )

    def _mantenimiento_finalizado(self, id_mant, nombre_mant,
                                  id_operador, nombre_operador):
        """Salida del modo Mantenimiento: cierra el paro con causa fija y
        REANUDA el conteo; la maquina sigue en marcha produciendo."""
        self._finalizar_modo_mantenimiento(id_operador, id_mant,
                                           incorporar=False)
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        self._estado(
            f"Fin de Mantenimiento autorizado por {nombre_mant} y "
            f"{nombre_operador}. La maquina sigue en marcha.",
            "exito",
        )
        log.info("Salida de Mantenimiento por %s y %s (sesion %s)",
                 nombre_mant, nombre_operador, self.sesion_id)

    def _finalizar_modo_mantenimiento(self, id_operador, id_mant,
                                      incorporar=False, cantidad=None):
        """Cierra el paro del modo Mantenimiento (causa fija + autorizador de
        mantenimiento).

        Con `incorporar=False` los cortes del modo se descartan y el conteo
        normal se REANUDA. Con `incorporar=True` se confirman como
        produccion de la sesion. Devuelve cuantos cortes se incorporaron.
        """
        if not self._modo_mantenimiento:
            return 0
        causa_id = self._causa_mantenimiento_id()
        if causa_id is None:
            log.warning("Causa 'mantenimiento' inactiva; paro %s sin causa",
                        self.paro_id)
        excluidos = self.controlador.cortes_excluidos() if incorporar else 0
        finalizar_paro(self.paro_id, causa_id, id_mant,
                       self._mantenimiento_zona_id)
        self.paro_id = None
        self._modo_mantenimiento = False
        self._mantenimiento_zona_id = None
        if incorporar:
            self.controlador.incorporar_excluidos(cantidad)
            incorporados = (
                excluidos if cantidad is None
                else min(max(int(cantidad), 0), excluidos)
            )
        else:
            incorporados = 0
            self.controlador.retomar_conteo()
        self.controlador.reiniciar_gracia_inactividad()
        # El switch de Primera pieza refleja el estado REAL del modo al salir
        # de Mantenimiento: si se entro estando en Primera pieza, el sistema
        # sigue en Primera pieza y el switch debe volver a quedarse ENCENDIDO.
        self._fijar_switch(self._primera_pieza)
        return incorporados

    def _corrida_mantenimiento_paso_operador(self, id_mant, nombre_mant,
                                             causa_id=None):
        """Tras la huella de mantenimiento: el OPERADOR confirma la corrida."""
        self._pedir_huella_reanudacion(
            titulo="REANUDACION OPERADOR",
            mensaje=(
                "Mantenimiento autorizado. Coloca tu huella (operador) para "
                "contar los cortes como produccion de la sesion."
            ),
            on_autorizado=lambda id_op, nop, causa=None:
                self._corrida_confirmada_mantenimiento(
                    id_mant, nombre_mant, id_op, nop
                )
        )

    def _corrida_confirmada_mantenimiento(self, id_mant, nombre_mant,
                                          id_operador, nombre):
        """Corrida confirmada en Mantenimiento: incorpora SOLO los cortes de
        la ventana detectada y posteriores (los previos de setup quedan
        descartados) y FINALIZA el modo; la maquina sigue en marcha."""
        a_incorporar = max(
            self.controlador.cortes_excluidos() - self._excluidos_previos_rafaga,
            0,
        )
        n = self._finalizar_modo_mantenimiento(
            id_operador, id_mant, incorporar=True, cantidad=a_incorporar
        )
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        self._estado(
            f"Corrida confirmada por {nombre_mant} y {nombre}: {n} cortes "
            "incorporados al conteo. Fin de Mantenimiento.",
            "exito",
        )
        log.info("Corrida en Mantenimiento confirmada por %s y %s: %s cortes "
                 "incorporados (%s previos descartados como prueba)",
                 nombre_mant, nombre, n, self._excluidos_previos_rafaga)

