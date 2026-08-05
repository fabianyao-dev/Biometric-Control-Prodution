import platform
from tkinter import ttk

FAMILIA_FUENTE = "Segoe UI" if platform.system() == "Windows" else "DejaVu Sans"

COLOR_FONDO = "#1a1a1a"
COLOR_SUPERFICIE = "#2a2a2a"
COLOR_TEXTO = "#e8e8e8"
COLOR_TEXTO_SECUNDARIO = "#bdbdbd"
COLOR_ACCENTE = "#1f538d"
COLOR_ACCENTE_CLARO = "#2a6cb8"
COLOR_EXITO = "#2fa572"
COLOR_EXITO_CLARO = "#35c182"
COLOR_ADVERTENCIA = "#d98e04"
COLOR_ERROR = "#e74c3c"
COLOR_DESACTIVADO = "#555555"

ESTILOS_ESTADO = {
    "pendiente": "Pendiente.TLabel",
    "procesando": "Procesando.TLabel",
    "exito": "Exito.TLabel",
    "error": "Error.TLabel",
    "info": "Info.TLabel",
}


def aplicar_estilo(root):
    estilo = ttk.Style(root)
    estilo.theme_use("clam")

    estilo.configure(".", font=(FAMILIA_FUENTE, 14))

    estilo.configure("TFrame", background=COLOR_FONDO)
    estilo.configure("Header.TFrame", background=COLOR_SUPERFICIE)

    estilo.configure("TLabel", background=COLOR_FONDO, foreground=COLOR_TEXTO)
    estilo.configure(
        "Header.TLabel", background=COLOR_SUPERFICIE, foreground=COLOR_TEXTO
    )
    estilo.configure("Title.TLabel", font=(FAMILIA_FUENTE, 22, "bold"))

    estilo.configure("Pendiente.TLabel", foreground=COLOR_ADVERTENCIA)
    estilo.configure("Procesando.TLabel", foreground=COLOR_ADVERTENCIA)
    estilo.configure("Exito.TLabel", foreground=COLOR_EXITO)
    estilo.configure("Error.TLabel", foreground=COLOR_ERROR)
    estilo.configure("Info.TLabel", foreground=COLOR_TEXTO_SECUNDARIO)

    estilo.configure(
        "ResultadoInfo.TLabel", font=(FAMILIA_FUENTE, 22, "bold"), foreground=COLOR_TEXTO
    )
    estilo.configure(
        "ResultadoExito.TLabel",
        font=(FAMILIA_FUENTE, 22, "bold"),
        foreground=COLOR_EXITO,
    )
    estilo.configure(
        "ResultadoError.TLabel",
        font=(FAMILIA_FUENTE, 22, "bold"),
        foreground=COLOR_ERROR,
    )

    estilo.configure(
        "TButton",
        font=(FAMILIA_FUENTE, 15, "bold"),
        padding=(20, 12),
        background=COLOR_ACCENTE,
        foreground="white",
        bordercolor=COLOR_ACCENTE_CLARO,
        lightcolor=COLOR_ACCENTE_CLARO,
        darkcolor=COLOR_ACCENTE,
    )
    estilo.map(
        "TButton",
        background=[("active", COLOR_ACCENTE_CLARO), ("disabled", COLOR_DESACTIVADO)],
        foreground=[("disabled", "#999999")],
    )

    estilo.configure(
        "Nav.TButton", font=(FAMILIA_FUENTE, 13, "bold"), padding=(24, 10)
    )

    estilo.configure(
        "Success.TButton",
        background=COLOR_EXITO,
        bordercolor=COLOR_EXITO_CLARO,
        lightcolor=COLOR_EXITO_CLARO,
        darkcolor=COLOR_EXITO,
    )
    estilo.map(
        "Success.TButton",
        background=[("active", COLOR_EXITO_CLARO), ("disabled", COLOR_DESACTIVADO)],
        foreground=[("disabled", "#999999")],
    )

    estilo.configure(
        "TEntry",
        font=(FAMILIA_FUENTE, 16),
        fieldbackground="#3a3a3a",
        foreground=COLOR_TEXTO,
        insertcolor=COLOR_TEXTO,
        bordercolor="#555555",
        padding=8,
    )
    estilo.map("TEntry", fieldbackground=[("focus", "#444444")])
