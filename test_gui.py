import platform
if platform.system() != "Windows":
    import ctypes
    x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    x11.XInitThreads()

import customtkinter as ctk

app = ctk.CTk()
app.title("Prueba GUI Pi")
app.geometry("400x300")

label = ctk.CTkLabel(app, text="CustomTkinter funcionando en Raspberry Pi 4")
label.pack(pady=20)

app.mainloop()
