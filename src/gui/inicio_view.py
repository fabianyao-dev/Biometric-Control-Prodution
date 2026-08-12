"""
inicio_view.py - Vista principal de produccion (Inicio).

Maquina de estados de la maquina:
    EN ESPERA -> LISTA: al pulsar PLAY se abre un modal que pide la
                 huella de inmediato; al autenticar se abre la sesion
                 (automatica) y la maquina arranca.
    LISTA     -> EN ESPERA: al pulsar STOP se abre un modal que pide la
                 huella (operador de la sesion o rol autorizado
                 admin/supervisor); al autorizar se cierra la sesion.
    LISTA     -> PARO: al pulsar PARO (o por inactividad) se abre el modal
                 que pide motivo + huella; al autorizar se reanuda.

La sesion se cuenta desde que la maquina arranca (LISTA) hasta que se
detiene; no hay boton de mantenimiento de sesion.

RECUPERACION TRAS CIERRE ABRUPTO: si la app se cerro con una sesion 'Activa'
(apagon, crash, cierre de ventana), al reiniciar se detecta en
`_revisar_sesion_interrumpida`: se restaura el operador, el total de cortes
del ultimo checkpoint y se deja la maquina en estado EN PARO. El operador
dueño o un rol autorizado (admin/supervisor) debe autorizar la reanudacion
(causa + huella) o cerrar formalmente la sesion; no se puede iniciar una
sesion nueva mientras exista la interrumpida.
"""

import logging
from tkinter import messagebox, ttk

from src import config
from src.database import (
    abrir_sesion,
    actualizar_cortes_sesion,
    cerrar_sesion,
    finalizar_paro,
    iniciar_paro,
    obtener_rol_operador,
    obtener_sesion_interrumpida,
    paro_en_curso,
)
from src.gui.huella_modal import HuellaModal
from src.gui.style import ESTILOS_ESTADO

log = logging.getLogger(__name__)


class InicioView(ttk.Frame):
    def __init__(self, parent, controller, biometrico, controlador):
        super().__init__(parent, style="TFrame")
        self.controller = controller
        self.biometrico = biometrico
        self.controlador = controlador

        self.sesion_id = None
        self.operador_id = None
        self.operador_nombre = None
        self.paro_id = None
        self._en_paro = False
        self._paro_idle_triggado = False
        self._modal_abierto = False
        self._recuperando = False

        self._crear_interfaz()
        self._revisar_sesion_interrumpida()
        self._refrescar_contador()
        self._checkpoint_cortes()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self):
        self.lbl_operador = ttk.Label(
            self, text="Operador: Sin sesion", style="Header.TLabel"
        )
        self.lbl_operador.pack(pady=(20, 4))

        self.lbl_cortes = ttk.Label(self, text="Cortes: 0", style="Big.TLabel")
        self.lbl_cortes.pack(pady=4)

        self.lbl_estado_maquina = ttk.Label(
            self, text="Maquina: EN ESPERA", style="Pendiente.TLabel"
        )
        self.lbl_estado_maquina.pack(pady=6)

        self.lbl_detalle = ttk.Label(self, text="", style="Info.TLabel")
        self.lbl_detalle.pack(pady=2)

        # --- Boton principal: PLAY (verde, lista para arrancar) o STOP
        # (rojo, con sesion activa: en espera o en paro) ---
        self.btn_poder = ttk.Button(
            self, text="\u25B6", style="PowerOn.TButton", command=self._toggle_poder,
        )
        self.btn_poder.pack(pady=16)

        self.btn_paro = ttk.Button(
            self, text="PARO", style="TButton", command=self._boton_paro,
        )
        self.btn_paro.pack(pady=2, ipady=4, ipadx=24)

        self.lbl_estado = ttk.Label(
            self,
            text="Pulsa el boton y coloca tu huella para encender.",
            style="Info.TLabel",
        )
        self.lbl_estado.pack(pady=10)

    # ------------------------------------------------------------------
    # Boton de poder (interruptor)
    # ------------------------------------------------------------------

    def _toggle_poder(self):
        if self._modal_abierto:
            return
        if self.sesion_id is None:
            self._encender_maquina()
        else:
            self._abrir_huella_cierre()

    def _encender_maquina(self):
        self._abrir_huella_encendido()

    def _apagar_maquina(self):
        if not self.controlador.maquina_detenida():
            self.controlador.maquina_pausada()
        total = self.controlador.cortes_totales()
        if self.sesion_id is not None:
            cerrar_sesion(self.sesion_id, total)
        self.controlador.reset_conteo()
        self.sesion_id = None
        self.operador_id = None
        self.operador_nombre = None
        self.paro_id = None
        self._en_paro = False
        self._paro_idle_triggado = False
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(f"Maquina en espera. {total} cortes registrados.", "info")
        log.info("Sesion cerrada con %s cortes", total)

    # ------------------------------------------------------------------
    # Modal: huella para arrancar (abre sesion automaticamente)
    # ------------------------------------------------------------------

    def _abrir_huella_encendido(self):
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="ARRANCAR MAQUINA",
                mensaje="Coloca tu huella. La sesion se abrira automaticamente.",
                on_autenticado=self._encendido_autenticado,
                on_cancelar=lambda: self._estado("Arranque cancelado.", "info"),
            )
            modal.grab_set()
            modal.wait_window()
        finally:
            self._modal_abierto = False

    def _encendido_autenticado(self, id_operador, nombre, causa_id=None):
        self.sesion_id = abrir_sesion(id_operador)
        self.operador_id = id_operador
        self.operador_nombre = nombre
        self.controlador.reset_conteo()
        self.controlador.maquina_lista()
        self._en_paro = False
        self._paro_idle_triggado = False
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(f"Maquina lista. Operador: {nombre}.", "exito")
        log.info("Sesion %s abierta para %s", self.sesion_id, nombre)

    # ------------------------------------------------------------------
    # Recuperacion de sesion/paro tras cierre abrupto
    # ------------------------------------------------------------------

    def _revisar_sesion_interrumpida(self):
        """Detecta una sesion 'Activa' heredada de un apagon y la recupera.

        Restaura operador, contador de cortes (ultimo checkpoint) y deja la
        maquina en EN PARO: el dueno o un rol autorizado debe autorizar la
        reanudacion, o cerrar formalmente la sesion. Mientras exista esta
        sesion no se puede iniciar una nueva (el boton de poder pasa a
        cerrar/recuperar, nunca a encender).
        """
        sesion = obtener_sesion_interrumpida()
        if not sesion:
            return
        self._recuperando = True
        self.sesion_id = sesion["id"]
        self.operador_id = sesion["operador_id"]
        self.operador_nombre = sesion["nombre"]
        self.controlador.establecer_conteo(sesion["total_cortes"] or 0)
        self._en_paro = True
        self._paro_idle_triggado = True
        # Paro en curso de la sesion; si no existia, se formaliza la detencion.
        self.paro_id = paro_en_curso(self.sesion_id) or iniciar_paro(self.sesion_id)
        self._refrescar_operador()
        self._refrescar_estado_maquina()
        self._estado(
            "Sesion interrumpida detectada. Maquina EN PARO: autoriza para "
            "reanudar o pulsa poder para cerrar la sesion.",
            "procesando",
        )
        log.info("Sesion interrumpida %s recuperada (operador %s, cortes %s)",
                 self.sesion_id, self.operador_nombre, sesion["total_cortes"])
        self.after(600, lambda: self._abrir_paro_autorizacion(recuperacion=True))

    def _abrir_huella_cierre(self):
        """Cierre de sesion: requiere autorizacion del operador de la sesion
        o de un rol con autoridad (admin/supervisor)."""
        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo=(
                    "CERRAR SESION INTERRUMPIDA"
                    if self._recuperando else "CERRAR SESION"
                ),
                mensaje=(
                    "Sesion interrumpida. Coloca tu huella para cerrarla "
                    "sin reanudar." if self._recuperando else
                    "Coloca tu huella para cerrar la sesion."
                ),
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._cierre_autenticado,
                on_cancelar=lambda: self._estado("Cierre cancelado.", "info"),
            )
            modal.grab_set()
            modal.wait_window()
        finally:
            self._modal_abierto = False

    def _cierre_autenticado(self, id_operador, nombre, causa_id=None):
        era_recuperacion = self._recuperando
        sesion_id = self.sesion_id
        self._recuperando = False
        self._apagar_maquina()
        if era_recuperacion:
            self._estado(f"Sesion interrumpida cerrada por {nombre}.", "exito")
        log.info("Sesion %s cerrada por %s", sesion_id, nombre)

    # ------------------------------------------------------------------
    # Paro
    # ------------------------------------------------------------------

    def _boton_paro(self):
        if self.sesion_id is None:
            self._estado("Primero arranca la maquina.", "error")
            return
        if self._modal_abierto:
            return
        if self._maquina_en_marcha():
            self._pausar_maquina()
        else:
            # Maquina ya detenida: reabrir autorizacion del paro pendiente
            if self._en_paro:
                self._abrir_paro_autorizacion()
    def _pausar_maquina(self, motivo="manual"):
        self.controlador.maquina_pausada()
        self._en_paro = True
        self.paro_id = iniciar_paro(self.sesion_id)
        self._refrescar_estado_maquina()
        log.info("Paro %s registrado (%s)", self.paro_id, motivo)
        self._estado("Maquina en PARO. Indica el motivo y autoriza.", "procesando")
        self._abrir_paro_autorizacion()

    def _abrir_paro_autorizacion(self, recuperacion=False):
        from src.database import listar_causas_paro

        causas = listar_causas_paro(activas_solo=True)
        if not causas:
            messagebox.showwarning(
                "Sin causas",
                "No hay causas de paro configuradas. Ve a Administracion.",
                parent=self.controller,
            )
            self._estado("Sin causas de paro; maquina detenida.", "error")
            return

        if recuperacion:
            on_cancelar = lambda: self._estado(  # noqa: E731
                "Recuperacion cancelada. Autoriza para reanudar o pulsa "
                "poder para cerrar la sesion.", "info"
            )
        else:
            on_cancelar = lambda: self._estado(  # noqa: E731
                "Paro NO autorizado; maquina detenida.", "error"
            )

        self._modal_abierto = True
        try:
            modal = HuellaModal(
                self.controller,
                self.biometrico,
                titulo="AUTORIZAR REANUDACION",
                mensaje=(
                    "Sesion interrumpida. Maquina EN PARO. Coloca tu huella."
                    if recuperacion else
                    "Maquina en PARO. Coloca tu huella."
                ),
                # En recuperacion el modal se puede cancelar (para cerrar la
                # sesion); en un paro normal no, hasta autorizar.
                mostrar_cancelar=recuperacion,
                cerrable=recuperacion,
                pedir_causa=True,
                validador=self._validar_autorizacion_paro,
                on_autenticado=self._autorizado_autenticado,
                on_cancelar=on_cancelar,
            )
            modal.grab_set()
            modal.wait_window()
        finally:
            self._modal_abierto = False

    def _validar_autorizacion_paro(self, id_operador, nombre, causa_id=None):
        """Solo autoriza (reanudar paro o cerrar sesion) el dueno de la
        sesion o un rol con autoridad (admin/supervisor, ver
        config.ROLES_AUTORIZAN_PARO)."""
        if id_operador == self.operador_id:
            return True, None
        rol = obtener_rol_operador(id_operador)
        if rol and rol in config.ROLES_AUTORIZAN_PARO:
            return True, None
        operador_sesion = self.operador_nombre or "el operador de la sesion"
        return False, (
            f"No eres {operador_sesion}. Solo el operador de la sesion "
            "o un rol autorizado (admin/supervisor) puede autorizar "
            "esta accion"
            + (f" (tu rol: {rol})." if rol else " (sin rol asignado).")
        )

    def _autorizado_autenticado(self, id_operador, nombre, causa_id=None):
        finalizar_paro(self.paro_id, causa_id, id_operador)
        self.controlador.reprisar_maquina()
        self._en_paro = False
        self._paro_idle_triggado = False
        self._recuperando = False
        self._refrescar_estado_maquina()
        self._estado(f"Paro autorizado por {nombre}. Maquina reanudada.", "exito")

    # ------------------------------------------------------------------
    # Inactividad -> auto paro
    # ------------------------------------------------------------------

    def _refrescar_contador(self):
        self.lbl_cortes.configure(text=f"Cortes: {self.controlador.cortes_totales()}")
        self._refrescar_estado_maquina()
        self._refrescar_enlace_modbus()
        self._verificar_inactividad()
        self.after(config.REFRESCO_CONTADOR_MS, self._refrescar_contador)

    def _refrescar_enlace_modbus(self):
        """Alerta visual si el enlace Modbus se cae (sin crashear la UI).

        Solo aplica al controlador Modbus (configurado con MODBUS_HOST); en
        modo simulacion o con SimulacionController no hay alerta.
        """
        en_simulacion = getattr(self.controlador, "en_simulacion", lambda: True)()
        conectado = getattr(self.controlador, "conectado", None)
        if en_simulacion or conectado is None:
            self.lbl_detalle.configure(text="", style="Info.TLabel")
        elif not conectado():
            self.lbl_detalle.configure(
                text="Error de comunicacion con el modulo Modbus. "
                     "Reintentando...",
                style="Error.TLabel",
            )
        else:
            self.lbl_detalle.configure(text="", style="Info.TLabel")

    def _checkpoint_cortes(self):
        """Guarda periodicamente el total de cortes de la sesion activa.

        Respaldos ante apagones: si se va la luz, la sesion conserva el
        ultimo conteo en la base de datos (ver config.CORTES_GUARDAR_INTERVALO_MS).
        """
        if self.sesion_id is not None:
            actualizar_cortes_sesion(self.sesion_id, self.controlador.cortes_totales())
        self.after(config.CORTES_GUARDAR_INTERVALO_MS, self._checkpoint_cortes)

    def _verificar_inactividad(self):
        timeout = config.PARO_IDLE_TIMEOUT_S
        if not timeout or timeout <= 0:
            return
        if (self.sesion_id is None or self._paro_idle_triggado
                or self._modal_abierto or self._en_paro):
            return
        if not self._maquina_en_marcha():
            return
        if self.controlador.segundos_sin_corte() >= timeout:
            self._paro_idle_triggado = True
            log.info("Sin cortes por %s s; abriendo paro automatico", timeout)
            self._pausar_maquina(motivo="automatico")

    def _maquina_en_marcha(self):
        return not self.controlador.maquina_detenida()

    def _refrescar_estado_maquina(self):
        if self.sesion_id is None:
            self.lbl_estado_maquina.configure(
                text="Maquina: EN ESPERA", style="Pendiente.TLabel"
            )
            self.btn_poder.configure(text="\u25B6", style="PowerOn.TButton")
        elif self._en_paro:
            self.lbl_estado_maquina.configure(
                text="Maquina: EN PARO \u23F8", style="Procesando.TLabel"
            )
            self.btn_poder.configure(text="\u25A0", style="Power.TButton")
        else:
            self.lbl_estado_maquina.configure(
                text="Maquina: LISTA", style="Exito.TLabel"
            )
            self.btn_poder.configure(text="\u25A0", style="Power.TButton")

    # ------------------------------------------------------------------
    # Helpers UI
    # ------------------------------------------------------------------

    def _refrescar_operador(self):
        texto = self.operador_nombre if self.operador_nombre else "Sin sesion"
        self.lbl_operador.configure(text=f"Operador: {texto}")

    def _estado(self, texto="", estado="info"):
        self.lbl_estado.configure(
            text=texto, style=ESTILOS_ESTADO.get(estado, "Info.TLabel")
        )