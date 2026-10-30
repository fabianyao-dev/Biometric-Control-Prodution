# -*- coding: utf-8 -*-
"""Contenedor dinamico de modulos para la vista Inicio."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from src.gui.modulos import registro


class InicioShell(QWidget):
    sesion_cambiada = Signal(str, str)

    def __init__(self, contexto, parent=None):
        super().__init__(parent)
        self.contexto = contexto
        self.contexto.inicio_shell = self
        self._vistas = {}
        self._clave_actual = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)

        predeterminado = registro.modulo_predeterminado()
        if predeterminado is not None:
            self.cambiar_modulo(predeterminado.clave, forzar=True)

    def puede_cambiar(self):
        vista = self._vista_actual()
        if vista is None:
            return True, ""
        metodo = getattr(vista, "puede_cambiar_modulo", None)
        if callable(metodo):
            try:
                ok, motivo = metodo()
                return bool(ok), motivo or ""
            except Exception:  # noqa: BLE001
                return True, ""
        return True, ""

    def _vista_actual(self):
        if self._clave_actual is None:
            return None
        return self._vistas.get(self._clave_actual)

    def cambiar_modulo(self, clave, forzar=False):
        modulo = registro.obtener(clave)
        if modulo is None:
            return False
        if not forzar and self._clave_actual is not None and clave != self._clave_actual:
            ok, motivo = self.puede_cambiar()
            if not ok:
                return False
        if clave not in self._vistas:
            vista = modulo.crear(self.contexto)
            senal = getattr(vista, "sesion_cambiada", None)
            if senal is not None:
                try:
                    senal.connect(self.sesion_cambiada.emit)
                except Exception:  # noqa: BLE001
                    pass
            self._vistas[clave] = vista
            self.stack.addWidget(vista)
        self._clave_actual = clave
        self.stack.setCurrentWidget(self._vistas[clave])
        return True

    def vista_actual(self):
        return self._vista_actual()

    def aplicacion_puede_cerrarse(self):
        vista = self._vista_actual()
        if vista is None:
            return True
        metodo = getattr(vista, "aplicacion_puede_cerrarse", None)
        if callable(metodo):
            try:
                return bool(metodo())
            except Exception:  # noqa: BLE001
                return True
        return True

    def clave_actual(self):
        return self._clave_actual