import sys
import os
import platform
import logging

# Configurar logs con formato preciso y marcas de tiempo
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] (%(threadName)s) %(message)s',
    datefmt='%H:%M:%S'
)

logging.info("=== INICIANDO APLICACIÓN EN LINUX ===")

# 1. FORZAR X11 Y MODOS SÍNCRONOS A NIVEL DE ENTORNO
os.environ["GDK_BACKEND"] = "x11"
os.environ["TK_SILENCE_DEPRECATION"] = "1"

# NOTA: XInitThreads() fue ELIMINADO a propósito.
# Causaba el abort de XCB "Unknown sequence number ... You called XInitThreads,
# this is not your fault" al crear los primeros widgets de Tk.
# Tkinter no lo requiere: nuestros hilos secundarios jamás tocan Tk
# (se comunican por colas thread-safe drenadas en el hilo principal).

logging.info("Importando CustomTkinter...")
import customtkinter as ctk
logging.info("CustomTkinter importado con éxito.")

logging.info("Importando dependencias del proyecto (Servicios / Hardware)...")

# Agregar logs antes de cada import clave para detectar cuál dispara hilos C
try:
    logging.info("Importando BiometricService...")
    from src.hardware.biometric_service import BiometricService
    logging.info("BiometricService importado.")
except Exception as e:
    logging.error(f"Error al importar BiometricService: {e}")

try:
    logging.info("Importando vistas de la GUI...")
    from src.gui.identify_view import IdentifyView
    from src.gui.register_view import RegisterView
    logging.info("Vistas importadas correctamente.")
except Exception as e:
    logging.error(f"Error al importar Vistas: {e}")


class MainApp(ctk.CTk):
    def __init__(self):
        logging.info("Inicializando ctk.CTk() ventana principal...")
        super().__init__()
        logging.info("Instancia de ctk.CTk() creada correctamente.")

        self.title("Sistema de Control Biométrico")
        self.geometry("800x480")

        logging.info("Inicializando servicios de hardware...")
        self.biometric_service = BiometricService()
        logging.info("Servicios de hardware instanciados.")

        # Construcción de vistas
        logging.info("Cargando vista de identificación...")
        self.container = ctk.CTkFrame(self)
        self.container.pack(fill="both", expand=True)

        self.identify_view = IdentifyView(self.container, self)
        self.identify_view.pack(fill="both", expand=True)
        logging.info("GUI lista para iniciar bucle de eventos.")

if __name__ == "__main__":
    try:
        app = MainApp()
        logging.info("Iniciando app.mainloop() [Hilo Principal]...")
        app.mainloop()
        logging.info("Aplicación cerrada normalmente.")
    except Exception as e:
        logging.critical(f"Excepción no controlada en mainloop: {e}", exc_info=True)
