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

