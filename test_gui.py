import os
os.environ["GDK_BACKEND"] = "x11"

import customtkinter as ctk

app = ctk.CTk()
app.title("Prueba GUI Pi")
app.geometry("400x300")

label = ctk.CTkLabel(app, text="CustomTkinter funcionando en Raspberry Pi 4")
label.pack(pady=20)

app.mainloop()
