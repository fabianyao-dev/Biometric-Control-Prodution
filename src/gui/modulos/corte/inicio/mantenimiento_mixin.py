"""
inicio_view.py - Vista principal de produccion (Inicio).

La pantalla separa DOS controles independientes:

SESION (boton del header, esquina superior derecha): identidad + TOTALES.
    Al iniciarla se pide huella, se abre la sesion y se REINICIA el contador
    (el total de produccion es POR SESION). El icono muestra persona (rol
    operador) o engranaje (cualquier otro rol) y el nombre del operador queda
    a su lado. NO se puede cerrar sesion con la maquina en marcha: una
    maquina encendida siempre vive dentro de una sesion (al encender entra a
    Primera pieza y pide trabajo); cerrarla dejaria cortes sin dueno.

MAQUINA (boton central grande): enciende/apaga el relevo DENTRO de la
    sesion, sin huella extra (hereda la del login). Encender pone la maquina
    en marcha y entra AUTOMATICAMENTE al modo Primera pieza (estado "ESPERA
    TRABAJO") abriendo el pedido de trabajo; la espera de trabajo queda asi
    atada al ENCENDIDO, no al login. Apagar SIN trabajo detiene el relevo
    (seguro anti-corte mediante). Apagar CON trabajo cargado hace el cierre
    completo (#5): primero elige la MODALIDAD de cierre (produccion normal
    topada a la meta / produccion parcial con confirmacion o correccion del
    conteo / Folio modificado con el nuevo total) y DETIENE la maquina,
    quedando en espera de trabajo. La confirmacion de la cantidad ES la
    autorizacion del cierre: NO se pide huella (el operador de la sesion ya
    esta autenticado al abrirla). El estado final del trabajo (Cerrado si
    alcanza la meta, Abierto si no) lo decide la BD.

Modo "Primera pieza": con la sesion abierta y la maquina en marcha, registra
el evento como un paro con la causa fija 'Primera pieza'; durante el modo la
maquina sigue en marcha y NO se aplica el auto-paro por inactividad. Al salir
del modo (switch + huella) la gracia del auto-paro se reinicia. El boton PARO
queda deshabilitado mientras este activo.

Modo "MANTENIMIENTO": al parar y elegir la causa 'mantenimiento', hace falta
una validacion DOBLE, PRIMERO huella de personal de mantenimiento (permiso
'autorizar_mantenimiento') y LUEGO la del operador de la sesion. La maquina
SIGUE EN MARCHA con el conteo suspendido (los cortes van a excluidos, con la
misma logica de rafagas que Primera pieza). El boton PARO pasa a "SALIR DE
MANTENIMIENTO" (rojo) y el boton central brilla en ambar; para salir se pide
otra vez la doble validacion (mantenimiento + operador) y se finaliza el paro
con la causa 'mantenimiento'. El boton central brilla en amarillo durante
Primera pieza y en verde al producir.

MODO PARO: TODO paro autorizado entra aqui, sea cual sea la causa (la unica
excepcion es 'mantenimiento', que conserva su modo propio). El paro queda
ABIERTO en BD y se cierra en un SEGUNDO paso, 'SALIR DE PARO' (boton PARO en
rojo o boton central), que pide la huella del operador. Lo unico que depende
de la zona elegida es la maquina: si la causa requiere zona y esa zona tiene
marcada 'maquina encendida' (Administracion -> Zonas), la maquina REPRENDE con
el conteo suspendido y los cortes van a excluidos; en cualquier otro caso
(zona normal o causa que no requiere zona) la maquina se queda DETENIDA. En
ambos casos, al pulsar SALIR DE PARO se cierra el paro y la maquina queda
ENCENDIDA (si estaba detenida, se enciende automaticamente). El estado de la
maquina muestra la causa elegida entre parentesis ('Maquina: PARO (Causa)');
que la maquina siga en marcha se distingue por el resplandor y el tooltip.

SEGURO ANTI-CORRIDA: durante el modo los cortes van a un acumulado temporal.
Si se detecta una rafaga (mas de SEGURO_RAFAGA_CORTES cortes dentro de
SEGURO_RAFAGA_SEGUNDOS, ver .env), suena una alarma y se pregunta si la
maquina ya empezo a correr; al confirmar y autorizar por huella, SOLO los
cortes de la ventana detectada y posteriores se INCORPORAN al total de la
sesion (lo excluido antes queda como piezas de prueba descartadas). Con "No"
(o sin autorizacion) todo sigue fuera del conteo y se pierde al salir del modo.

TRABAJOS POR QR: al ENCENDER la maquina se ofrece un modal CANCELABLE que
pide el escaneo de un QR `folio|num_part|cantidad_total` (escaner USB tipo
teclado) + huella. El operador manda: puede cancelar para ajustar la maquina
y hacer piezas de prueba (el modo suprime el auto-paro por inactividad) y
escanear cuando este listo con ESCANEAR TRABAJO (visible solo sin trabajo
cargado y maquina en marcha). Al aceptar se registra/retoma el trabajo en la
tabla `trabajos` (folio unico: re-escanear uno Abierto retoma su conteo; uno
Cerrado se rechaza), se salen las piezas de prueba (mismo descarte del modo)
y los cortes empiezan a contar para ese trabajo ARRANCANDO EN 1 (total -
baseline, con la Primera pieza contando como la primera pieza del folio; un
folio retomado conserva su avance y no repite el +1). El
marcador muestra NUMERO DE PARTE arriba, los digitos al centro y CANTIDAD/
META abajo; la linea inferior de estado resume sesion, folio, parte,
cantidad, meta, ciclos totales y setup. 'Cerrado' SOLO al alcanzar la
cantidad_total, y ahora SOLO via cierre manual: EL AUTO-CIERRE POR META ESTA
INHABILITADO (`_verificar_meta_trabajo` quedo comentado en
`_refrescar_contador`), asi que ni la alarma ni el dialogo de cierre se abren
solos. El cierre por el boton de MAQUINA con trabajo carga el dialogo
de cierre (#5). Lo mismo al cerrar sesion: el parcial queda Abierto. Tras un
apagon el trabajo se retoma escaneando su QR, que lo reactiva desde su
checkpoint.

CIERRE ABRUPTO (APAGON): si la app se cerro con una sesion 'Activa' (apagon,
crash, cierre de ventana), al reiniciar `_cerrar_sesion_interrumpida` NO la
recupera: los datos ya estan guardados por el checkpoint de 30 s
(`_checkpoint_cortes`), asi que solo limpia y pide una sesion NUEVA:

    1. El trabajo en curso se CONFIRMA con lo detectado en su checkpoint: las
       piezas ya se cortaron y no habra quien las vuelva a contar. Si alcanzo
       la meta queda 'Cerrado', si no 'Abierto' con su parcial (se retoma
       escaneando su QR; no hace falta autorizacion).
    2. El paro en curso se cierra con la causa implicita "Computadora
       apagada" (nadie autorizo nada, pero el reporte no debe mostrar paros
       sin causa).
    3. La sesion pasa a 'Finalizada' con el total del checkpoint.

La vista arranca deliberadamente SIN sesion (`sesion_id=None`): el header pide
huella de inicio y el operador abre un folio desde cero, con conteo en 0. El
latch PAUSE inicial del HAL deja la maquina fisicamente detenida.
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

