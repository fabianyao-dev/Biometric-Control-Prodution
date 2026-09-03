"""
huella_modal.py - Ventana modal reutilizable de autenticacion por huella.

Al abrirse, EMPIEZA a pedir la huella de inmediato (sin botones extras).
Se usa para:
    - Arranque de maquina (validar operador antes de encender).
    - Autorizacion de paro (elegir causa + confirmar con el dedo).

Con `pedir_causa=True` muestra el SelectorCausas: cuadricula con las causas
mas usadas y un boton para buscar, SIN ninguna causa preseleccionada; no
autoriza hasta que se elija una y la huella vuelva a pasar. Al autenticar con
exito invoca `on_autenticado(operador_id, nombre, causa_id)`.

Con `validador=(operador_id, nombre, causa_id) -> (bool, mensaje)` se puede
restringir quien puede autenticarse: si el validador devuelve (False, msg),
el modal NO se cierra, muestra `msg` como error y vuelve a pedir la huella
(se usa para que solo el operador de la sesion o un rol autorizado pueda
autorizar la reanudacion de un paro).

Con `pedir_trabajo=True` el modal TAMBIEN exige el escaneo de un codigo QR
de trabajo con formato `folio|num_part|cantidad_total`, capturado por un
escaner USB tipo teclado (escribe en un campo con foco y manda Enter).
Solo acepta cuando hay QR valido Y huella autenticada (en cualquier orden):
si falta uno, avisa y sigue pidiendo. Al aceptar invoca
`on_autenticado(operador_id, nombre, causa_id, folio, num_part, cantidad_total)`.

El tamano de la ventana se calcula en funcion del contenido (vease
`centrar_y_ajustar`), asi el modal crece o encoge segun la causa. Se abre en
bloqueo con `exec()`; los hilos secundarios solo escriben a `queue.Queue()`
que se drena con un QTimer en el hilo principal.
"""

import logging
import queue
import re
import threading
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from src.gui import style
from src.gui.selector_causas import SelectorCausaZona
from src.gui.style import aplicar_estado
from src.gui.util import centrar_y_ajustar, desplazamiento_tactil

log = logging.getLogger(__name__)

# Icono "fingerprint" de Material Symbols (path oficial, repositorio de
# google/material-design-icons). El trazo engrosa las crestas para que se
# lean bien a tamano de insignia. Rellenado/contorneado con {color}.
SVG_HUELLA = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" \
width="24" height="24"><path fill="{color}" stroke="{color}" \
stroke-width="28" stroke-linejoin="round" d="M481-781q106 0 200 45.5T838-604\
q7 9 4.5 16t-8.5 12q-6 5-14 4.5t-14-8.5q-55-78-141.5-119.5T481-741q-97 0-182 \
41.5T158-580q-6 9-14 10t-14-4q-7-5-8.5-12.5T126-602q62-85 155.5-132T481-781\
Zm0 94q135 0 232 90t97 223q0 50-35.5 83.5T688-257q-51 0-87.5-33.5T564-374q0-33 \
-24.5-55.5T481-452q-34 0-58.5 22.5T398-374q0 97 57.5 162T604-121q9 3 12 10t1 \
15q-2 7-8 12t-15 3q-104-26-170-103.5T358-374q0-50 36-84t87-34q51 0 87 34t36 84\
q0 33 25 55.5t59 22.5q34 0 58-22.5t24-55.5q0-116-85-195t-203-79q-118 0-203 79\
t-85 194q0 24 4.5 60t21.5 84q3 9-.5 16T208-205q-8 3-15.5-.5T182-217q-15-39 \
-21.5-77.5T154-374q0-133 96.5-223T481-687Zm0-192q64 0 125 15.5T724-819q9 5 \
10.5 12t-1.5 14q-3 7-10 11t-17-1q-53-27-109.5-41.5T481-839q-58 0-114 13.5T260-\
783q-8 5-16 2.5T232-791q-4-8-2-14.5t10-11.5q56-30 117-46t124-16Zm0 289q93 0 \
160 62.5T708-374q0 9-5.5 14.5T688-354q-8 0-14-5.5t-6-14.5q0-75-55.5-125.5T481-\
550q-76 0-130.5 50.5T296-374q0 81 28 137.5T406-123q6 6 6 14t-6 14q-6 6-14 6t-\
14-6q-59-62-90.5-126.5T256-374q0-91 66-153.5T481-590Zm-1 196q9 0 14.5 6t5.5 14\
q0 75 54 123t126 48q6 0 17-1t23-3q9-2 15.5 2.5T744-191q2 8-3 14t-13 8q-18 5 \
-31.5 5.5t-16.5.5q-89 0-154.5-60T460-374q0-8 5.5-14t14.5-6Z"/></svg>
"""


class HuellaWidget(QWidget):
    """Insignia circular con el icono de huella (Material Symbols, SVG).

    Fondo circular en superficie elevada + icono centrado, recolorizado
    segun el estado (verde esperando, blanco al autenticar).
    """

    def __init__(self, parent=None, ancho=96, alto=96):
        super().__init__(parent)
        self.setFixedSize(ancho, alto)
        self._autenticado = False
        self._renderer = QSvgRenderer()

    def set_autenticado(self, valor):
        self._autenticado = valor
        self.update()

    def _svg_con_color(self):
        tono = (style.color("texto") if self._autenticado
                else style.color("exito"))
        return SVG_HUELLA.replace("{color}", tono)

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Fondo circular (insignia). Colores del tema ACTIVO.
        p.setPen(QPen(QColor(style.color("borde")), 2))
        if self._autenticado:
            fondo = QColor(style.color("exito"))
            fondo.setAlpha(30)
        else:
            fondo = QColor(style.color("elevada"))
        p.setBrush(fondo)
        p.drawEllipse(0, 0, self.width() - 1, self.height() - 1)

        # Icono centrado con margen.
        margen = 14
        rect = self.rect().adjusted(margen, margen, -margen, -margen)
        if self._renderer.load(self._svg_con_color().encode("utf-8")):
            self._renderer.render(p, rect)
        else:
            # Respaldo por si QtSvg no pudiera cargar el icono.
            p.setPen(QPen(QColor(style.color("exito")), 3, Qt.SolidLine,
                          Qt.RoundCap))
            p.drawEllipse(rect)
        # SIEMPRE cerrar el painter: un return sin `p.end()` deja el painter
        # activo y Qt inunda con "QBackingStore::endPaint() called with active
        # painter" en TODO repintado posterior (cascada).
        p.end()


class HuellaModal(QDialog):
    def __init__(self, parent, biometrico, titulo, mensaje,
                 on_autenticado=None, on_cancelar=None,
                 mostrar_cancelar=True, cerrable=True, pedir_causa=False,
                 validador=None, pedir_trabajo=False, qr_solo=False,
                 on_trabajo_escaneado=None, permitir_sin_trabajo=False,
                 on_confirmado=None, mostrar_dev=False, on_dev=None):
        super().__init__(parent)
        self.biometrico = biometrico
        self.titulo = titulo
        self.mensaje = mensaje
        self.on_autenticado = on_autenticado
        self.on_cancelar = on_cancelar
        self.on_confirmado = on_confirmado
        self.mostrar_cancelar = mostrar_cancelar
        self.cerrable = cerrable
        self.validador = validador
        self.pedir_trabajo = pedir_trabajo
        self.pedir_causa = pedir_causa
        # Boton "Entrar como DEV (sin lector)": visible cuando `mostrar_dev`
        # es True (modo desarrollo). Al pulsarlo se cierra el modal y se
        # invoca `on_dev` para iniciar sesion con el operador temporal.
        self.mostrar_dev = mostrar_dev
        self.on_dev = on_dev
        # Permite CONFIRMAR con la huella aunque no se haya escaneado ningun
        # QR. El callback on_autenticado recibe folio/num_part/cantidad como
        # None para distinguirlo de una carga con trabajo. El autorizador de
        # ese caso (permiso) se valida en el callback, fuera del modal.
        self.permitir_sin_trabajo = permitir_sin_trabajo
        # Modo SOLO QR: no pide huella; al leer un QR valido acepta y
        # notifica via on_trabajo_escaneado(folio, num_part, cantidad).
        self.qr_solo = qr_solo
        self.on_trabajo_escaneado = on_trabajo_escaneado
        # Trabajo escaneado (folio, num_part, cantidad_total) o None hasta
        # que el escaner entregue un QR con formato valido.
        self.trabajo_escaneado = None

        self._autenticado = False
        self._abierto = True
        # La captura de huella ya fue iniciada (evita relanzar el hilo con
        # pulsaciones repetidas del boton Confirmar).
        self._emprendido = False
        # Evita notificar on_cancelar dos veces si se cancela por mas de una
        # via (boton Cancelar -> reject, o ESC -> reject directo).
        self._cancel_notificado = False
        # (operador_id, nombre, causa_id) del exito pendiente de notificar
        # una vez cerrado el modal.
        self._datos_exito = None
        # (folio, num_part, cantidad_total) pendiente en modo qr_solo.
        self._datos_qr = None
        self.cola = queue.Queue()
        self.selector_causas = None

        self.setWindowTitle(titulo)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._crear_interfaz(pedir_causa)
        # El modal corre en el kiosco touch: scroll con el dedo en la lista de
        # causas (QScrollArea) sin que el arrastre vaya a la ventana nativa.
        desplazamiento_tactil(self)
        if self.pedir_causa:
            # Tamano base del modal de causa/zona: suficientemente amplio para
            # que el croquis (y su letra proporcional) se vea grande, pero sin
            # desbordar pantallas pequenas (1280x720): `centrar_y_ajustar`
            # recorta el minimo al tamano de la pantalla si no cabe.
            self.setMinimumSize(1100, 640)
        centrar_y_ajustar(self, parent)

        self._timer_cola = QTimer(self)
        self._timer_cola.setInterval(60)
        self._timer_cola.timeout.connect(self._revisar_cola)
        self._timer_cola.start()
        # En un paro con causa (pedir_causa) la captura de huella arranca
        # hasta pulsar Confirmar (el operador primero elige causa + zona).
        if not self.qr_solo and not self.pedir_causa:
            self._empezar()

        # El escaner USB tipo teclado escribe aqui y manda Enter.
        if self.pedir_trabajo:
            self.input_qr.setFocus()

    # ------------------------------------------------------------------
    # Cierre (X / ESC)
    # ------------------------------------------------------------------

    def closeEvent(self, evento):
        # La ventana de paro (huella) NO puede cerrarse (X/ESC) hasta
        # autenticar. En qr_solo no hay huella. En pedir_causa (solo elige
        # causa+zona, sin huella aun) el cierre lo decide `cerrable` via
        # `reject`: se deja pasar aqui.
        if not self.pedir_causa and not self._autenticado and not self.qr_solo:
            self._estado("No se puede cerrar. Identifica tu huella.", "error")
            evento.ignore()
            return
        super().closeEvent(evento)

    def reject(self):
        if not self.cerrable and not self._autenticado:
            self._estado("No se puede cerrar. Identifica tu huella.", "error")
            return
        # Cierre sin autenticar (ESC u otra via de `reject`): equivale a
        # pulsar Cancelar, notificando on_cancelar UNA sola vez. Sin esto,
        # el ESC cerraba el modal sin avisar y la ventana quedaba en un
        # estado intermedio (p. ej. el modo Primera pieza quedaba activo sin
        # la validacion de permisos correspondiente).
        if not self._autenticado and not self._cancel_notificado:
            self._cancel_notificado = True
            if self.on_cancelar:
                self.on_cancelar()
        super().reject()

    def done(self, result):
        self._abierto = False
        try:
            self._timer_cola.stop()
        except Exception:  # noqa: BLE001
            pass
        super().done(result)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _crear_interfaz(self, pedir_causa):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        lbl_titulo = QLabel(self.titulo, self)
        lbl_titulo.setObjectName("Title")
        lbl_titulo.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_titulo)

        # En el modo selector (pedir_causa) NO hay captura de huella aun: es
        # el PRIMER paso del flujo de 2 modales (zona+causa -> reanudacion).
        if not pedir_causa:
            self.huella = HuellaWidget(self)
            layout.addWidget(self.huella, alignment=Qt.AlignHCenter)

        lbl_mensaje = QLabel(self.mensaje, self)
        lbl_mensaje.setObjectName("EstadoInfo")
        lbl_mensaje.setAlignment(Qt.AlignCenter)
        lbl_mensaje.setWordWrap(True)
        layout.addWidget(lbl_mensaje)

        if pedir_causa:
            self.selector_causas = SelectorCausaZona(
                self, on_cambio=self._actualizar_confirmar
            )
            layout.addWidget(self.selector_causas, stretch=1)

        if self.pedir_trabajo:
            self.input_qr = QLineEdit(self)
            self.input_qr.setPlaceholderText(
                "Escanea el QR del trabajo (folio|num_part|cantidad_total)"
            )
            self.input_qr.returnPressed.connect(self._leer_qr)
            layout.addWidget(self.input_qr)

            self.lbl_trabajo = QLabel("Sin trabajo escaneado.", self)
            aplicar_estado(self.lbl_trabajo, "procesando")
            self.lbl_trabajo.setAlignment(Qt.AlignCenter)
            self.lbl_trabajo.setWordWrap(True)
            layout.addWidget(self.lbl_trabajo)

        if self.pedir_causa:
            texto_estado = (
                "Selecciona la causa del paro (y la zona si la requiere) "
                "y pulsa CONFIRMAR."
            )
        else:
            texto_estado = (
                "Escanea el QR del trabajo..." if self.qr_solo
                else "Coloca tu huella..."
            )
        self.lbl_estado = QLabel(texto_estado, self)
        self.lbl_estado.setObjectName("EstadoInfo")
        self.lbl_estado.setAlignment(Qt.AlignCenter)
        self.lbl_estado.setWordWrap(True)
        layout.addWidget(self.lbl_estado)

        if self.mostrar_cancelar:
            btn_cancelar = QPushButton("Cancelar", self)
            # El escaner USB termina su lectura con Enter: sin esto,
            # un Enter con el foco fuera del QLineEdit pulsa Cancelar
            # y aborta el escaneo sin motivo.
            btn_cancelar.setAutoDefault(False)
            btn_cancelar.setDefault(False)
            btn_cancelar.clicked.connect(self._cancelar)
            layout.addWidget(btn_cancelar)

        if self.mostrar_dev:
            btn_dev = QPushButton("Entrar como DEV (sin lector)", self)
            btn_dev.setToolTip(
                "Modo desarrollo: inicia sesion con el operador temporal "
                "sin usar el lector biometrico."
            )
            btn_dev.setAutoDefault(False)
            btn_dev.setDefault(False)
            btn_dev.clicked.connect(self._entrar_dev)
            layout.addWidget(btn_dev)

        # En un paro con causa, el flujo es: elegir causa (+ zona) -> boton
        # CONFIRMAR -> huella que autoriza.
        if pedir_causa:
            self.btn_confirmar = QPushButton("CONFIRMAR CAUSA", self)
            self.btn_confirmar.setObjectName("Success")
            self.btn_confirmar.setEnabled(False)
            self.btn_confirmar.clicked.connect(self._confirmar)
            layout.addWidget(self.btn_confirmar)

    # ------------------------------------------------------------------
    # Escaneo del QR de trabajo (escaner USB tipo teclado)
    # ------------------------------------------------------------------

    def _leer_qr(self):
        """Procesa la linea que el escaner escribio (termina en Enter).

        Formato exigido: folio|num_part|cantidad_total, con folio y cantidad
        enteros positivos. Invalido -> error, limpia y vuelve a esperar.

        Los escaneres USB tipo teclado NO mandan caracteres: mandan codigos
        de tecla de una distribucion US y Windows los traduce segun la
        disposicion activa. Con la PC en ES/Latinoamericano, el separador
        '|' llega como ']' u otro simbolo vecino (p. ej. Steren): se aceptan
        las variantes tipicas como separadores.
        """
        texto = self.input_qr.text().strip()
        partes = [p.strip() for p in re.split(r"[|]", texto)]
        if len(partes) != 3:
            self._rechazar_qr(
                "Formato invalido: se esperan 3 campos "
                "folio|num_part|cantidad_total."
            )
            return
        folio_txt, num_part, cantidad_txt = partes
        try:
            folio = int(folio_txt)
        except ValueError:
            self._rechazar_qr(f"Folio no numerico: '{folio_txt}'.")
            return
        try:
            cantidad_total = int(cantidad_txt)
        except ValueError:
            self._rechazar_qr(f"Cantidad no numerica: '{cantidad_txt}'.")
            return
        if folio <= 0:
            self._rechazar_qr("El folio debe ser mayor que cero.")
            return
        if not num_part:
            self._rechazar_qr("El numero de parte viene vacio.")
            return
        if cantidad_total <= 0:
            self._rechazar_qr("La cantidad total debe ser mayor que cero.")
            return
        self.trabajo_escaneado = (folio, num_part, cantidad_total)
        self.lbl_trabajo.setText(
            f"\u2713 Folio {folio} \u00b7 Parte {num_part} \u00b7 "
            f"{cantidad_total} pzs"
        )
        aplicar_estado(self.lbl_trabajo, "exito")
        self.input_qr.clear()
        if self.qr_solo:
            # Sin huella: el QR valido ES el exito del modal.
            self._estado(f"\u2713 Trabajo {folio} cargado.", "exito")
            self._datos_qr = (folio, num_part, cantidad_total)
            QTimer.singleShot(250, self._cerrar_y_notificar_qr)
            return
        self._estado(
            "Trabajo escaneado. Coloca tu huella para confirmar.", "procesando"
        )

    def _rechazar_qr(self, motivo):
        log.warning("QR de trabajo rechazado: %s", motivo)
        self.trabajo_escaneado = None
        self.lbl_trabajo.setText("Sin trabajo escaneado.")
        aplicar_estado(self.lbl_trabajo, "error")
        self.input_qr.clear()
        self._estado(f"{motivo} Escanea de nuevo.", "error")
        self.input_qr.setFocus()

    # ------------------------------------------------------------------
    # Captura automatica
    # ------------------------------------------------------------------

    def _empezar(self):
        self._emprendido = True
        threading.Thread(target=self._escanea, daemon=True).start()

    def _actualizar_confirmar(self):
        """Habilita/deshabilita el boton CONFIRMAR segun causa (+ zona)."""
        if self.pedir_causa and hasattr(self, "btn_confirmar"):
            self.btn_confirmar.setEnabled(
                self.selector_causas.puede_confirmar()
            )

    def _confirmar(self):
        """Valida causa+zona, cierra el modal y notifica la seleccion via
        `on_confirmado` (flujo de 2 modales: aqui SOLO se elige; la huella de
        reanudacion se pide en el segundo modal, en inicio_view)."""
        if not self.selector_causas.puede_confirmar():
            self._estado(
                "Selecciona la causa del paro (y la zona si la requiere).",
                "error",
            )
            return
        sel = self.selector_causas
        resultado = (
            sel.seleccion_id,
            sel.seleccion_descripcion,
            sel.seleccion_zona_id(),
            sel.seleccion_zona_nombre(),
            sel.seleccion_zona_maquina_encendida(),
        )
        # Cierra PRIMERO y despues notifica (MISMO patron que
        # _cerrar_y_notificar), para que el segundo modal no se apile sobre este.
        self.accept()
        if self.on_confirmado:
            self.on_confirmado(*resultado)

    def _escanea(self):
        if not getattr(self.biometrico, "disponible", True):
            log.error(
                "Biometria NO disponible al intentar autenticar "
                "(BiometricService.disponible=False). Ver biometric_sdk.py."
            )
            self.cola.put(
                ("ERROR", "Biometria no disponible en este equipo (driver de DigitalPersona no instalado).")
            )
            return
        try:
            resultado = self.biometrico.autenticar_operador(
                on_progress=self._progreso
            )
            self.cola.put(("RESULTADO", resultado))
        except RuntimeError as e:
            # Fallos esperables de operacion (sin lector, lectura rechazada,
            # driver ausente): mensaje claro en el modal, sin traceback que
            # ensucie la depuracion.
            log.warning("Autenticacion sin exito: %s", e)
            self.cola.put(("ERROR", str(e)))
        except Exception as e:  # noqa: BLE001
            # Fallo NO esperado: conservar el stack para depurar.
            log.error("Autenticacion fallo: %s", e, exc_info=True)
            self.cola.put(("ERROR", str(e)))

    def _progreso(self, mensaje):
        self.cola.put(("PROGRESO", mensaje))

    # ------------------------------------------------------------------
    # Cola (hilo principal)
    # ------------------------------------------------------------------

    def _revisar_cola(self):
        if not self._abierto:
            return
        try:
            while True:
                ev, data = self.cola.get_nowait()
                try:
                    if ev == "PROGRESO":
                        self._estado(data or "Coloca tu huella...", "procesando")
                    elif ev == "RESULTADO":
                        self._procesar_resultado(data)
                    elif ev == "ERROR":
                        self._estado(f"Intenta de nuevo: {data}", "error")
                        if "no disponible" not in str(data):
                            QTimer.singleShot(2500, self._reintentar)
                except Exception as e:  # noqa: BLE001
                    # Un fallo puntual no debe apagar el bucle de mensajes.
                    log.error("Error procesando evento %s: %s", ev, e, exc_info=True)
        except queue.Empty:
            pass

    def _procesar_resultado(self, resultado):
        if resultado:
            op_id, nombre = resultado
            causa_id = None
            if self.selector_causas is not None:
                causa_id = self.selector_causas.seleccion_id
                if causa_id is None:
                    # Sin preseleccion de causa: exigir eleccion explicita
                    # antes de autorizar (evita paros registrados sin causa).
                    log.info("Huella %s autentica; falta seleccionar causa.",
                             nombre)
                    self._estado(
                        "\u2713 Huella autenticada. Selecciona la causa del "
                        "paro y vuelve a colocar tu huella.", "error"
                    )
                    QTimer.singleShot(2500, self._reintentar)
                    return
            if self.pedir_trabajo and self.trabajo_escaneado is None \
                    and not self.permitir_sin_trabajo:
                # Misma puerta que la causa: exigir el escaneo antes de
                # aceptar (evita trabajos sin QR).
                log.info("Huella %s autentica; falta escanear el trabajo.",
                         nombre)
                self._estado(
                    "Escanea el qr del trabajo (folio|num_part|cantidad).",
                    "error",
                )
                self.input_qr.setFocus()
                QTimer.singleShot(2500, self._reintentar)
                return
            if self.validador is not None:
                valido, mensaje = self.validador(op_id, nombre, causa_id)
                if not valido:
                    log.warning(
                        "Huella %s (%s) SIN autorizacion: %s", op_id, nombre, mensaje
                    )
                    self._estado(mensaje or "Sin autorizacion para reanudar.", "error")
                    QTimer.singleShot(2500, self._reintentar)
                    return
            self._autenticado = True
            self.huella.set_autenticado(True)
            self._estado(f"\u2713 {nombre} autenticado.", "exito")
            # Guarda los datos y CIERRA primero: on_autenticado se invoca
            # desde _cerrar_y_notificar, con este modal ya cerrado, para que
            # los flujos que reaccionan abriendo OTRO modal (el QR del
            # trabajo al arrancar la maquina, el reintento tras un folio
            # rechazado, etc.) no queden apilados sobre este.
            self._datos_exito = (op_id, nombre, causa_id)
            QTimer.singleShot(300, self._cerrar_y_notificar)
        else:
            log.warning("Huella no reconocida; reintentando.")
            self._estado("Huella NO reconocida. Intenta de nuevo.", "error")
            QTimer.singleShot(2500, self._reintentar)

    def _reintentar(self):
        if not self._autenticado and self._abierto:
            threading.Thread(target=self._escanea, daemon=True).start()

    def _cerrar_y_notificar(self):
        """Cierra el modal y DESPUES invoca on_autenticado."""
        self.accept()
        if not self.on_autenticado or self._datos_exito is None:
            return
        op_id, nombre, causa_id = self._datos_exito
        if self.pedir_trabajo:
            # Si no hay QR (solo posible con permitir_sin_trabajo) notificamos
            # los campos de trabajo como None; el callbacks decide/valida.
            if self.trabajo_escaneado is None:
                self.on_autenticado(
                    op_id, nombre, causa_id, None, None, None
                )
                return
            folio, num_part, cantidad_total = self.trabajo_escaneado
            self.on_autenticado(
                op_id, nombre, causa_id,
                folio, num_part, cantidad_total,
            )
        else:
            zona_id = None
            if self.selector_causas is not None:
                zona_id = self.selector_causas.seleccion_zona_id()
            if zona_id is not None:
                self.on_autenticado(op_id, nombre, causa_id, zona_id)
            else:
                self.on_autenticado(op_id, nombre, causa_id)

    def _cerrar_y_notificar_qr(self):
        """Modo qr_solo: cierra y notifica el trabajo escaneado."""
        self.accept()
        if self.on_trabajo_escaneado and self._datos_qr is not None:
            self.on_trabajo_escaneado(*self._datos_qr)

    def _cancelar(self):
        if not self._autenticado and not self._cancel_notificado:
            self._cancel_notificado = True
            if self.on_cancelar:
                self.on_cancelar()
        self.reject()

    def _entrar_dev(self):
        """Accion del boton 'Entrar como DEV (sin lector)'."""
        self._autenticado = True
        self.accept()
        if self.on_dev:
            self.on_dev()

    def _estado(self, texto, estado):
        self.lbl_estado.setText(texto)
        aplicar_estado(self.lbl_estado, estado)
        self._reajustar()

    def _reajustar(self):
        """Si el mensaje de estado crecio, reajusta el modal para que nada se
        solape con la huella (la ventana queda fija con resize())."""
        hint = self.sizeHint()
        if hint.width() > self.width() + 2 or hint.height() > self.height() + 2:
            centrar_y_ajustar(self, self.parent())
