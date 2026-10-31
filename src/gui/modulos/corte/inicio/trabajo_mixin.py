"""Carga y seguimiento del trabajo por QR (TrabajoMixin).

Abre el modal folio|num_part|cantidad, valida el QR, abre el trabajo en BD,
dispara la rutina Easy del num_part y vigila la meta y los cortes para saber
si el trabajo se puede confirmar o debe cerrarse con la sesion.
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




class TrabajoMixin:

    def _folio_activo(self):
        """Folio del trabajo en curso de la sesion (o None si no hay folio
        cargado: Primera pieza sin trabajo con permiso o espera de QR)."""
        if self.sesion_id is None:
            return None
        try:
            trabajo = obtener_trabajo_abierto(self.sesion_id)
        except Exception:  # noqa: BLE001 - un paro nunca debe fallar por esto
            log.warning("No se pudo leer el trabajo activo", exc_info=True)
            return None
        return trabajo["folio"] if trabajo is not None else None

    def _abrir_modal_trabajo(self):
        """Modal QR + huella que CARGA el trabajo estando en Primera pieza.

        El QR trae los datos y la huella CONFIRMA la carga; el modal no
        arranca el conteo ni saca la maquina del modo: sigue en Primera
        pieza (cortes de setup excluidos, sin auto-paro) mostrando el
        folio/parte. La SALIDA del modo (switch + huella) es lo que empieza
        a contar para el folio.
        """
        if self.sesion_id is None:
            return
        sin_trabajo = self._tiene_permiso_iniciar_primera_pieza()
        mensaje = (
            "Escanea el QR del trabajo "
            "(folio|num_part|cantidad_total) y confirma con tu huella. "
            "El conteo inicia al salir del modo Primera pieza."
        )
        if sin_trabajo:
            mensaje += (
                " Si dejas el campo vacio y pones tu huella, entras a "
                "Primera pieza SIN trabajo (permiso concedido)."
            )
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="TRABAJO NUEVO",
                mensaje=mensaje,
                validador=self._validar_autorizacion_paro,
                pedir_trabajo=True,
                permitir_sin_trabajo=sin_trabajo,
                mostrar_cancelar=True,
                cerrable=True,
                on_autenticado=self._trabajo_cargado,
                on_cancelar=self._cancelar_modal_trabajo,
            )
            modal.exec()
        finally:
            self._modal_abierto = False

    def _cancelar_modal_trabajo(self):
        """QR cancelado/vaCio (punto 4): permanecer en Primera pieza SIN
        trabajo solo si el operador de la sesion tiene el permiso
        `iniciar_primera_pieza` (mantenimiento/admin). Si no, el modo se
        cierra y la maquina queda detenida (espera de trabajo sin permiso
        no se mantiene)."""
        if self._tiene_permiso_iniciar_primera_pieza():
            self._estado(
                "Primera pieza sin trabajo aprobada (rol autorizado): los "
                "cortes no cuentan.", "info",
            )
            log.info("Primera pieza sin trabajo mantenida por %s (permiso "
                     "iniciar_primera_pieza)", self.operador_nombre)
            return
        self._finalizar_primera_pieza_si_activa(self.operador_id)
        self._fijar_switch(False)
        self._refrescar_estado_maquina()
        self._refrescar_labels_cortes()
        permitidos = " o ".join(roles_con_permiso("iniciar_primera_pieza")) or (
            "un rol autorizado"
        )
        self._estado(
            f"Sin trabajo y sin permiso para Primera pieza: la maquina se "
            f"detuvo. Solo {permitidos} puede iniciarla sin trabajo.",
            "error",
        )
        log.warning("Primera pieza sin trabajo cancelada para %s: "
                    "no tiene el permiso iniciar_primera_pieza",
                    self.operador_nombre)
        # Maquina detenida sin folio ni modo: empieza la espera implicita.
        self._abrir_espera_trabajo()

    def _trabajo_cargado(self, id_operador, nombre, causa_id,
                         folio, num_part, cantidad_total):
        """QR + huella aceptados: registra/retoma el folio EN ESPERA o, si la
        huella llego SIN QR (permitir_sin_trabajo), entra a Primera pieza
        SIN trabajo con la maquina ENCENDIDA (exige permiso).

        En ningun caso sale del modo Primera pieza: el conteo del trabajo
        arranca hasta que el operador autorice la salida del modo (switch
        + huella).
        """
        if folio is None:
            self._entrar_primera_pieza_sin_trabajo(
                id_operador, nombre
            )
            return
        # Fin de la espera: el QR trae su propia huella, que autoriza el
        # cierre del paro implicito.
        self._cerrar_espera_trabajo(id_operador)
        ok, res = abrir_trabajo(folio, self.sesion_id, num_part,
                                cantidad_total)
        if not ok:
            log.warning("Trabajo %s rechazado: %s", folio, res)
            caja = QMessageBox(self.controller)
            caja.setWindowTitle("Trabajo rechazado")
            caja.setText(str(res))
            caja.setIcon(QMessageBox.Warning)
            caja.addButton("Aceptar", QMessageBox.AcceptRole)
            caja.exec()
            self._abrir_modal_trabajo()
            return
        self._trabajo = res
        guardada = res["cortes_detectados"] or 0
        self._detectados_al_cargar = guardada
        # Al cargar un trabajo la maquina ENCIENDE para los cortes de setup
        # (punto 3): estando en espera de trabajo con el relevo apagado,
        # el arranque real ocurre aqui, no al pulsar PLAY.
        if self.controlador.maquina_detenida():
            self.controlador.maquina_lista()
            log.info("Maquina encendida (setup) al cargar el trabajo %s",
                     folio)
        # Baseline fijo desde la carga: los cortes de setup siguen
        # excluidos (total congelado), asi que `_cortes_trabajo()` muestra
        # lo ya hecho del folio y al salir del modo empieza a sumar.
        self._baseline_trabajo = self.controlador.cortes_totales() - guardada
        self._refrescar_labels_cortes()
        confirmados = res["cortes_confirmados"] or 0
        self._estado(
            f"Trabajo {res['folio']} ({res['num_part']}) cargado por "
            f"{nombre} ({confirmados}/{res['cantidad_total']}). Sal del modo "
            "Primera pieza con tu huella para empezar.", "exito",
        )
        log.info("Trabajo %s (%s) cargado en espera por %s a la sesion %s "
                 "(retoma %s/%s)", res["folio"], res["num_part"], nombre,
                 self.sesion_id, guardada, res["cantidad_total"])
        # Usar el numero de parte real del trabajo (res['num_part']) en lugar de enviar texto fijo o de busqueda
        self._enviar_easy_num_part(res["num_part"])

    def _enviar_easy_num_part(self, num_part):
        """Notifica al agente Easy (estacion remota) el numero de parte escaneado.

        Delega en ServicioEasy, que resuelve la rutina en la BD y elige el
        protocolo (legacy o v2) segun config.EASY_CONFIG.
        """
        from ..easy.service import desde_config

        cfg = config.EASY_CONFIG
        if not (cfg.get("host") or "").strip():
            return

        servicio = desde_config()

        def _on_resultado(ok, error):
            if not ok and error:
                def _actualizar_ui():
                    try:
                        self._estado(error, "error")
                    except RuntimeError:
                        pass
                QTimer.singleShot(0, _actualizar_ui)

        _trabajo = getattr(self, "_trabajo", None)
        _folio = None
        if _trabajo is not None:
            try:
                _folio = _trabajo["folio"]
            except Exception:  # noqa: BLE001
                _folio = None
        servicio.ejecutar_rutina(
            cfg.get("rutina", "buscar_easy"), num_part,
            folio=_folio,
            sesion_id=getattr(self, "sesion_id", None),
            callback=_on_resultado,
        )

    def _cortes_trabajo(self):
        """Cortes hechos DENTRO del trabajo abierto (total - baseline).

        Es el acumulado GLOBAL del folio en vivo (retoma desde lo ya
        cortado): alimenta el label, la meta y el checkpoint."""
        if self._trabajo is None:
            return 0
        return max(
            self.controlador.cortes_totales() - self._baseline_trabajo, 0
        )

    def _cortes_sesion_trabajo(self):
        """Cortes del folio hechos EN ESTA sesion (vivo - al cargar).

        Es lo que pre-carga el dialogo de cierre: en una sesion retomada
        sin cortes muestra 0 aunque el folio traiga acumulado.
        """
        if self._trabajo is None:
            return 0
        return max(self._cortes_trabajo() - self._detectados_al_cargar, 0)

    def _confirmable_trabajo(self):
        """Piezas con las que se podria completar el folio YA: confirmados
        globales acumulados + lo cortado en ESTA sesion.

        Dispara el auto-cierre por meta (no el vivo global: con
        sobreproduccion el vivo supera la meta pero quiza falten confirmadas,
        y en una retomada sin cortes no debe naggear).
        """
        if self._trabajo is None:
            return 0
        try:
            previos = self._trabajo["cortes_confirmados"] or 0
        except (KeyError, IndexError, TypeError):
            previos = 0
        return previos + self._cortes_sesion_trabajo()

    def _verificar_meta_trabajo(self):
        """Meta alcanzable: abre el cierre con cantidad a confirmar sin detener
        la maquina.

        AUTO-FINALIZACION INHABILITADA: la llamada desde
        `_refrescar_contador` quedo comentada, asi que este metodo NO se
        invoca (el cierre al llegar a la meta es manual, boton de MAQUINA).
        Se conserva intacto para reactivarlo.

        Llamado desde `_refrescar_contador` (hilo principal). Cuando lo
        confirmado global mas lo cortado en ESTA sesion alcanza la
        cantidad_total se abre el mismo cierre con input editable que el boton
        de MAQUINA (#5) — el operador confirma/corrige la cantidad (o modifica
        el folio); esa confirmacion autoriza el cierre, sin huella. La
        maquina SIGUE EN MARCHA y contando mientras se resuelve el cierre
        (el operador la detiene al confirmar); lo que se guarda es el numero
        confirmado, no el conteo en vivo. Un
        trabajo solo pasa a 'Cerrado' al alcanzarse la meta (hoy: solo en el
        cierre manual).
        """
        if self._trabajo is None or self._modal_abierto or self._en_paro:
            return
        if self._confirmable_trabajo() < self._trabajo["cantidad_total"]:
            return
        # No se detiene la maquina: mientras el modal de cierre esta abierto
        # sigue contando; `_cerrar_trabajo_confirmado` la detiene al
        # confirmar el cierre.
        self._abrir_cierre_con_modalidad(por_meta=True)

    def _boton_escanear_trabajo(self):
        """Reabre el modal QR + huella cuando no hay trabajo abierto."""
        if self._modal_abierto or self.sesion_id is None:
            return
        if self._trabajo is not None:
            self._estado(
                f"El trabajo {self._trabajo['folio']} sigue abierto; "
                "finalizalo antes de escanear otro.", "error"
            )
            return
        self._abrir_modal_trabajo()

    def _cerrar_trabajo_por_cierre_sesion(self):
        """Guarda el parcial del trabajo abierto al apagar/cerrar sesion.

        El trabajo NO se cierra (solo la meta lo cierra): queda 'Abierto'
        con su parcial y puede retomarse re-escaneando el folio en cualquier
        sesion futura.
        """
        if self._trabajo is None:
            return
        folio = self._trabajo["folio"]
        real = self._cortes_trabajo()
        pausar_trabajo(folio, real)
        self._trabajo = None
        self._baseline_trabajo = 0
        self._detectados_al_cargar = 0
        log.info("Trabajo %s con parcial guardado al cerrar la sesion "
                 "(%s piezas, sigue Abierto)", folio, real)

