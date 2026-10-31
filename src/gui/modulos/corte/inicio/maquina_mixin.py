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




class MaquinaMixin:

    def _apagar_maquina(self, autorizador_id=None) -> bool:
        """Cierra la sesion (solo con la maquina ya detenida). Devuelve True
        si cerro.

        `autorizador_id` es el operador que autentico el cierre (si se pasa);
        por defecto se atribuye al dueno de la sesion, como en Primera pieza.
        El reset del contador vive en la APERTURA de sesion (`_sesion_abierta`),
        no aqui: encender/apagar la maquina ya no toca el acumulado.
        """
        if self._seguro_paro_segundos() is not None:
            self._estado(
                "La maquina esta cortando: espera unos segundos para apagar.",
                "error",
            )
            log.info("Apagado bloqueado por seguro anti-corte")
            return False
        if not self.controlador.maquina_detenida():
            # Camino defensivo: el guard de toggle_sesion deberia haber
            # bloqueado este caso con la maquina en marcha.
            self.controlador.maquina_pausada()
        total = self.controlador.cortes_totales()
        if self.sesion_id is not None:
            self._finalizar_primera_pieza_si_activa(self.operador_id)
            self._cerrar_trabajo_por_cierre_sesion()
            # Paro EN CURSO: cerrarlo junto con la sesion para no dejar filas
            # 'En curso' eternas sobre una sesion ya Finalizada (Diagnostico
            # 7.2.5). En el MODO PARO se cierra con la causa/zona ya elegidas
            # (el operador no llego a pulsar SALIR DE PARO); en un paro aun no
            # autorizado queda SIN causa (la columna lo permite, igual que
            # _cerrar_primera_pieza cuando falta la causa).
            if self.paro_id is not None:
                autorizador = autorizador_id or self.operador_id
                if self._modo_paro:
                    causa_cierre = self._modo_paro_causa_id
                    zona_cierre = self._modo_paro_zona_id
                else:
                    causa_cierre = zona_cierre = None
                try:
                    finalizar_paro(self.paro_id, causa_cierre, autorizador,
                                   zona_cierre)
                    log.info("Paro %s cerrado junto con la sesion "
                             "(autorizado por operador %s, causa %s)",
                             self.paro_id, autorizador, causa_cierre)
                except Exception:  # noqa: BLE001 - no debe frenar el cierre
                    log.warning("No se pudo cerrar el paro %s al cerrar la "
                                "sesion", self.paro_id, exc_info=True)
                self.paro_id = None
            # Espera implicita abierta: se cierra con su causa, atribuida a
            # quien autentico el cierre (o al dueno de la sesion).
            self._cerrar_espera_trabajo(autorizador_id or self.operador_id)
            cerrar_sesion(self.sesion_id, total)
        self.sesion_id = None
        self.operador_id = None
        self.operador_nombre = None
        self.paro_id = None
        self._en_paro = False
        self._paro_idle_triggado = False
        self._primera_pieza = False
        self._primera_pieza_paro_id = None
        self._primera_pieza_inicio = None
        self._espera_trabajo_paro_id = None
        self._modo_mantenimiento = False
        self._mantenimiento_zona_id = None
        self._modo_paro = False
        self._modo_paro_causa_id = None
        self._modo_paro_causa_desc = None
        self._modo_paro_zona_id = None
        self._modo_paro_maquina_encendida = False
        self._fijar_switch(False)
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(f"Maquina en espera. {total} cortes registrados.", "info")
        log.info("Sesion cerrada con %s cortes", total)
        return True

    def _toggle_maquina(self):
        if self._modal_abierto:
            return
        if self.sesion_id is None:
            self._estado(
                "Inicia sesion antes de encender la maquina.", "error"
            )
            return
        if self._en_paro and not self._modo_paro:
            # Paro aun NO autorizado (el del boton PARO no ha pasado el
            # modal): el boton de maquina queda deshabilitado; la salida es
            # autorizando por el boton PARO. En el MODO PARO ya autorizado el
            # boton central sale del modo con huella y deja la maquina
            # encendida, nunca apaga.
            return
        if self._modo_mantenimiento:
            # El boton central (glow ambar) tambien sale del modo con la
            # doble validacion; nunca apaga ni desprotege la maquina.
            self._salir_modo_mantenimiento()
            return
        if self._modo_paro:
            self._salir_modo_paro()
            return
        if self._maquina_en_marcha():
            if self._seguro_paro_segundos() is not None:
                self._estado(
                    "La maquina esta cortando: espera unos segundos para "
                    "apagar.", "error",
                )
                log.info("APAGADO bloqueado por seguro anti-corte")
                return
            self._apagar_maquina_en_marcha()
        else:
            self._encender_maquina()

    def _encender_maquina(self):
        """Entra a espera de trabajo (Primera pieza) DENTRO de la sesion.

        La maquina fisicamente queda APAGADA (punto 3): solo se enciende al
        CARGAR un trabajo (`_trabajo_cargado` -> `maquina_lista()`), para
        hacer los cortes de setup. Asi nunca queda energizada sin trabajo
        cargado. Abre el pedido de trabajo (modal QR).
        """
        self._entrar_primera_pieza(self.operador_nombre)
        self._refrescar_estado_maquina()
        self._estado(
            "En espera de trabajo: escanea un trabajo para encender la "
            "maquina y hacer el setup.", "exito",
        )
        log.info("Espera de trabajo por %s (sesion %s): la maquina queda "
                 "apagada hasta cargar un trabajo.", self.operador_nombre,
                 self.sesion_id)
        self._abrir_modal_trabajo()

    def _apagar_maquina_en_marcha(self):
        """Apaga la maquina manteniendo la sesion abierta.

        Con un trabajo cargado hace el CIERRE COMPLETO (#5): confirma la
        cantidad detectada en un input editable (o modifica el folio), guarda
        la cantidad y detiene el relevo, quedando en espera de trabajo. Sin
        trabajo detiene directo (saliendo del modo Primera
        pieza si estuviera activo). La sesion sigue abierta: solo se cierra
        desde el header con la maquina ya detenida.
        """
        if self._trabajo is not None:
            self._abrir_cierre_con_modalidad(por_meta=False)
            return
        # Detener PRIMERO el relevo y despues salir del modo: cualquier
        # delta en vuelo cae a los excluidos y se descarta con el modo.
        self.controlador.maquina_pausada()
        self._finalizar_primera_pieza_si_activa(self.operador_id)
        self._fijar_switch(False)
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        self._estado(
            "Maquina detenida. La sesion sigue abierta.", "info"
        )
        log.info("Maquina apagada por %s (sesion %s continua)",
                 self.operador_nombre, self.sesion_id)
        # Sin folio cargado empieza la espera implicita hasta el siguiente QR.
        self._abrir_espera_trabajo()

    def _abrir_cierre_con_modalidad(self, por_meta=False):
        """CIERRE COMPLETO (#5) con cantidad confirmada, comun al apagado
        manual (boton de maquina) y al alcanzar la meta.

        `por_meta=True` indica que la maquina ya llego a la cantidad_total
        (cierre automatico por timer). El flujo es 1) dialogo de cierre (input
        editable + folio modificado) y 2) guardar y DETENER la maquina: la
        confirmacion de la cantidad ES la autorizacion, no se pide huella
        (el operador de la sesion ya esta autenticado al abrirla).
        """
        if self._trabajo is None or self._modal_abierto or self._en_paro:
            return
        # Todo el flujo (dialogo de modalidad) corre con `_modal_abierto`
        # para que el timer de refresco no reabra otro modal en el entretanto.
        self._modal_abierto = True
        try:
            folio = self._trabajo["folio"]
            num_part = self._trabajo["num_part"]
            # Pre-carga con lo cortado EN ESTA SESION (no el acumulado del
            # folio): lo confirmado se suma al global, nunca lo reemplaza.
            cortado = self._cortes_sesion_trabajo()
            meta = self._trabajo["cantidad_total"]
            # 1) Cierre (#5): input con la cantidad detectada (editable) +
            # Folio modificado. Por meta NO se puede cancelar: el operador
            # debe confirmar (no queda un trabajo Abierto con la meta cumplida).
            dlg = ModalidadCierreDialog(
                self, folio, num_part, cortado, meta, cancelable=not por_meta,
            )
            if dlg.exec() != QDialog.Accepted:
                self._estado(
                    "Apagado cancelado; el trabajo sigue abierto.", "info",
                )
                return
            modalidad = dlg.resultado_modalidad
            cantidad_final = dlg.resultado_cantidad
            nuevo_total = dlg.resultado_nuevo_total
            # 2) Sin huella: confirmar la cantidad ya autoriza el cierre.
            self._cerrar_trabajo_confirmado(
                self.operador_id, self.operador_nombre, modalidad,
                cantidad_final, nuevo_total, por_meta=por_meta,
            )
        finally:
            self._modal_abierto = False

    def _cerrar_trabajo_confirmado(self, id_operador, nombre,
                                   modalidad, cantidad_final,
                                   nuevo_total=None, causa_id=None,
                                   por_meta=False):
        """Cierre completo (#5): guarda la cantidad del dialogo y DETIENE la
        maquina.

        `cantidad_final` es AUTORITATIVA (viene del input del dialogo,
        pre-cargado con el conteo detectado y corregible); la capa de BD
        decide el estado del trabajo: alcanza la meta -> 'Cerrado', no ->
        'Abierto' (retomable re-escaneando el folio). La sesion sigue abierta
        con la maquina detenida.
        """
        folio = self._trabajo["folio"]
        meta = self._trabajo["cantidad_total"]
        # Detectados vivos al cerrar (antes de detener): van a
        # `cortes_detectados`; la del dialogo va a `cortes_confirmados`.
        detectados = self._cortes_trabajo()
        self.controlador.maquina_pausada()
        self._finalizar_primera_pieza_si_activa(id_operador)
        self._fijar_switch(False)
        ok, estado, cantidad_final = cerrar_trabajo_modalidad(
            folio, cantidad_final, meta, nuevo_total, modalidad,
            detectados=detectados,
        )
        self._trabajo = None
        self._baseline_trabajo = 0
        self._detectados_al_cargar = 0
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        if not ok:
            self._estado(
                f"No se pudo guardar el trabajo {folio}: {estado}.",
                "error",
            )
            return
        if por_meta:
            self._sonar_alarma()
            self._estado(
                f"Trabajo {folio} completado ({cantidad_final}/{meta}) "
                f"y maquina detenida. Pulsa PLAY para cargar el siguiente.",
                "procesando",
            )
        else:
            # Mensaje claro segun cierre
            if modalidad == MODALIDAD_FOLIO:
                # nuevo_total es el nuevo total del folio
                self._estado(
                    f"Trabajo {folio} guardado por {nombre}: "
                    f"{cantidad_final} piezas (Folio modificado a {nuevo_total}), "
                    f"maquina detenida.", "exito",
                )
            else:
                self._estado(
                    f"Trabajo {folio} guardado por {nombre} con {cantidad_final} "
                    f"piezas ({estado}) y maquina detenida.", "exito",
                )
        log.info("Trabajo %s guardado (modalidad %s, %s piezas, estado %s) "
                 "y maquina apagada por %s (sesion %s continua%s)", folio,
                 modalidad, cantidad_final, estado, nombre, self.sesion_id,
                 ", por_meta" if por_meta else "")
        # Sin folio cargado empieza la espera implicita hasta el siguiente QR.
        self._abrir_espera_trabajo()

    def _maquina_en_marcha(self):
        return not self.controlador.maquina_detenida()

    def _estado_actual(self):
        """Fuente UNICA del estado sesion/maquina.

        Devuelve un dict con: clave, texto y badge del indicador, iconos
        (tablero y boton de maquina), estilo del boton y si esta habilitado.
        Los consumidores (`_refrescar_estado_maquina`, futuros badges)
        leen de aqui; nunca derivan el estado por su cuenta.

        Estados: sin_sesion / en_paro / detenida (sesion activa, relevo
        apagado) / espera_trabajo (en marcha, modo Primera pieza) / lista
        (en marcha, produccion).
        """
        sp = QStyle.StandardPixmap
        if self.sesion_id is None:
            return dict(
                clave="sin_sesion", texto="Maquina: EN ESPERA",
                badge="pendiente", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaPlay, btn_estilo="PowerOn", btn_on=False,
                tooltip="Inicia sesion para encender la maquina",
            )
        # MODO PARO (paro autorizado): el paro sigue ABIERTO y se cierra con
        # 'SALIR DE PARO' (boton central o PARO rojo). La maquina esta EN
        # MARCHA solo si la zona lo requiere; si no, sigue DETENIDA. Va ANTES
        # del chequeo generico de `_en_paro` para que no lo oculte.
        if self._modo_paro:
            en_marcha = self._modo_paro_maquina_encendida
            causa_txt = self._modo_paro_causa_desc or "(sin causa)"
            return dict(
                clave="modo_paro" if en_marcha else "modo_paro_detenida",
                texto=f"Maquina: PARO ({causa_txt})",
                badge="procesando", icono=sp.SP_MediaStop,
                btn_icono=sp.SP_MediaStop, btn_estilo="Power",
                btn_on=en_marcha,
                tooltip=("Salir del paro (la maquina sigue en marcha)"
                         if en_marcha
                         else "Salir del paro (la maquina sigue detenida)"),
            )
        if self._en_paro:
            return dict(
                clave="en_paro", texto="Maquina: EN PARO",
                badge="procesando", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaStop, btn_estilo="Power", btn_on=False,
                tooltip="Resuelve el paro para habilitar la maquina",
            )
        # Mantenimiento: la maquina SIGUE EN MARCHA con el conteo suspendido.
        # Salir del modo (boton central o PARO rojo) pide la doble validacion.
        if self._modo_mantenimiento:
            return dict(
                clave="mantenimiento", texto="Maquina: MANTENIMIENTO",
                badge="procesando", icono=sp.SP_MediaStop,
                btn_icono=sp.SP_MediaStop, btn_estilo="Power", btn_on=True,
                tooltip="Salir del modo Mantenimiento",
            )
        # Espera de trabajo / Primera pieza: PRIORIDAD antes del chequeo de
        # marcha, porque puede darse con la maquina APAGADA (aun sin trabajo
        # cargado, punto 3) o ENCENDIDA (cortes de setup).
        if self._primera_pieza:
            if self._maquina_en_marcha():
                return dict(
                    clave="espera_trabajo", texto="Maquina: PRIMERA PIEZA",
                    badge="procesando", icono=sp.SP_MediaPlay,
                    btn_icono=sp.SP_MediaStop, btn_estilo="Power",
                    btn_on=True,
                    tooltip="Apagar maquina (detiene el setup de Primera pieza)",
                )
            return dict(
                clave="espera_trabajo", texto="Maquina: ESPERA TRABAJO",
                badge="procesando", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaPlay, btn_estilo="PowerOn", btn_on=True,
                tooltip="Cargar un trabajo (QR+huella) para encender la maquina",
            )
        if not self._maquina_en_marcha():
            return dict(
                clave="detenida", texto="Maquina: DETENIDA",
                badge="info", icono=sp.SP_MediaPause,
                btn_icono=sp.SP_MediaPlay, btn_estilo="PowerOn", btn_on=True,
                tooltip="Encender maquina",
            )
        return dict(
            clave="lista", texto="Maquina: LISTA",
            badge="exito", icono=sp.SP_MediaPlay,
            btn_icono=sp.SP_MediaStop, btn_estilo="Power", btn_on=True,
            tooltip="Apagar maquina (con trabajo: lo guarda y detiene)",
        )

    def _refrescar_estado_maquina(self):
        """Pinta el estado desde `_estado_actual` (fuente unica) y
        actualiza los resplandores y el boton PARO."""
        e = self._estado_actual()
        estilo = self.style()
        self.lbl_estado_maquina.setText(e["texto"])
        aplicar_estado(self.lbl_estado_maquina, e["badge"])
        self._icono_estado(estilo, e["icono"])
        self.btn_maquina.setIcon(estilo.standardIcon(e["btn_icono"]))
        aplicar_estilo_boton(self.btn_maquina, e["btn_estilo"])
        self.btn_maquina.setEnabled(e["btn_on"])
        self.btn_maquina.setToolTip(e["tooltip"])
        # Resplandores en el boton CENTRAL (grande e intenso): AMARILLO en
        # Primera pieza, AMBAR en Mantenimiento y en el PARO con la maquina
        # EN MARCHA, y VERDE al producir. El modo PARO con la maquina
        # DETENIDA no resplandece (esta apagada, como un paro normal).
        if self._modo_mantenimiento or (self._modo_paro
                                        and self._modo_paro_maquina_encendida):
            self.resplandor_maquina.set_resplandor("mantenimiento")
        elif self._primera_pieza:
            self.resplandor_maquina.set_resplandor("amarillo")
        elif e["clave"] == "lista":
            self.resplandor_maquina.set_resplandor("exito")
        else:
            self.resplandor_maquina.detener_resplandor()
        try:
            self._actualizar_torre()
        except Exception:
            log.debug("No se pudo actualizar la torre de luces", exc_info=True)
        self._fila_switch.setVisible(
            self.sesion_id is not None
            and not self._en_paro
            and not self._modo_mantenimiento
            and not self._modo_paro
            and (self._maquina_en_marcha() or self._primera_pieza)
        )
        # ESCANEAR TRABAJO visible en espera de trabajo sin trabajo cargado
        # (con la maquina apagada o ya encendida en setup). Oculto durante
        # Mantenimiento y el modo PARO.
        self.btn_escanear.setVisible(
            self.sesion_id is not None
            and self._trabajo is None
            and not self._modo_mantenimiento
            and not self._modo_paro
            and (self._maquina_en_marcha() or self._primera_pieza)
        )
        self.switch_primera_pieza.setEnabled(
            self.sesion_id is not None
            and not self._modo_mantenimiento
            and not self._modo_paro
        )
        self._actualizar_boton_paro()

    def _actualizar_boton_paro(self):
        """PARO pasa a 'SALIR DE MANTENIMIENTO'/'SALIR DE PARO' en rojo
        durante esos modos."""
        en_paro_especial = self._modo_mantenimiento or self._modo_paro
        if en_paro_especial == self._boton_paro_especial:
            return
        self._boton_paro_especial = en_paro_especial
        if self._modo_mantenimiento:
            self.btn_paro.setText("SALIR DE MANTENIMIENTO")
            aplicar_estilo_boton(self.btn_paro, "Danger")
        elif self._modo_paro:
            self.btn_paro.setText("SALIR DE PARO")
            aplicar_estilo_boton(self.btn_paro, "Danger")
        else:
            self.btn_paro.setText("PARO")
            aplicar_estilo_boton(self.btn_paro, "")

