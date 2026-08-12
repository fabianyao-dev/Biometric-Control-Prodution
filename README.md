# Biometric-Control-Prodution

Sistema de control biométrico de producción para planta de corte (kiosco de
pantalla completa). GUI en `tkinter/ttk`, todo en español.

## Ejecutar

```bash
python main.py                # kiosco (pantalla completa)
set BIOMETRICO_KIOSKO=0       # ventana normal (Windows PowerShell)
python main.py
```

Usa el `venv/` del proyecto (Python 3.12). Dependencias en `requirements.txt`:

```bash
venv\Scripts\pip install -r requirements.txt
```

## Configuración (`config.py` + `.env`)

Copia `.env.example` a `.env` y ajusta:

- `MODBUS_HOST` / `MODBUS_PORT` / `MODBUS_UNIT_ID`: IP del módulo Advantech.
  Si está vacío o `MODBUS_SIMULACION=1`, el controlador corre en simulación
  (sin red).
- `MODBUS_START_COIL` / `MODBUS_PAUSE_COIL`: coils de los relevadores.
- `MODBUS_COUNTER_REGISTER` / `MODBUS_COUNTER_WORDS`: registro contador
  interno del módulo (el conteo de cortes lo hace el módulo por hardware;
  la PC solo hace polling).
- `DB_PATH`: ruta de la base de datos. **Obligatorio en producción**: un
  `.exe` de PyInstaller no puede guardarla junto a su propio código.
- `LOG_DIR`: directorio de logs diarios (rotación a 30 días).

## Plataforma

Plataforma **Windows** (dev y PC fanless de producción). La biometría usa el
SDK DigitalPersona (`dpfpdd.dll`/`dpfj.dll` vía ctypes); los relevadores y el
contador se manejan con `ModbusController` (módulo Advantech) o en simulación.

El HAL se elige solo: si hay `MODBUS_HOST` se usa Modbus, si no
`SimulacionController` (corre en simulación).

## Empaquetado (PC Fanless, PyInstaller)

La PC de producción no debe tener Python. Build en `onedir` (más confiable que
`onefile` para tkinter + SQLite):

```bash
venv\Scripts\pip install pyinstaller
venv\Scripts\pyinstaller --noconfirm --clean --noconsole --onedir --name ControlBiometrico main.py
```

Notas:

- Los DLLs de DigitalPersona (`dpfpdd.dll`, `dpfj.dll`) se cargan por nombre
  (`src/hardware/biometric_sdk.py`); deben estar instalados en el sistema
  (System32 / PATH), no se empaquetan.
- Copia un `.env` junto al `.exe` generado (o al `dist\ControlBiometrico\`)
  apuntando `DB_PATH` y `LOG_DIR` a un directorio persistente (p. ej. `D:\datos`).
- Verifica con `test_lector.py` y `test_fmd.py` antes del rollout.

## Deployment (procedimiento de TI, requiere admin/UAC)

1. **Autostart**: crea una tarea en el Programador de Tareas que ejecute
   `ControlBiometrico.exe` al iniciar sesión (usuario del kiosco, privilegios
   normales; el sistema no debe pedir contraseña).
2. **Windows Update desactivado**: nada peor que un reinicio en medio de un
   lote. Desactiva las actualizaciones automáticas vía Política de Grupo o
   Regedit (`HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU`,
   `NoAutoUpdate=1`) y planifica ventanas de mantenimiento para parches.
   ⚠️ Estos cambios son de sistema operativo: ejecutarlos requiere
   confirmación explícita y privilegios de administrador.

## Scripts de prueba (raíz, manuales)

- `test_lector.py`: carga `dpfpdd.dll` directo (prueba del driver).
- `test_captura.py [salida.fmd]`: captura huella a archivo.
- `test_fmd.py`: dos capturas y compara 1:1 y 1:N.
- `test_flujo.py registrar <fmd> <nombre> | identificar <fmd>`: flujo contra la BD.
- `test_modbus.py`: diagnóstico del módulo Advantech (coils + registro contador).

## Arquitectura

- `src/gui/`: vistas tkinter/ttk (no tocan hardware; solo inyectan el HAL).
- `src/hardware/`: HAL (`modbus_controller.py`, `simulacion_controller.py` en
  simulación) y biometría (`biometric_service.py` + `biometric_sdk.py`).
- `src/database.py`: SQLite (`planta_corte.db`), timestamps en
  `America/Monterrey`, soft-delete (`activo=0`).
- `src/config.py`: configuración centralizada (roles con autoridad,
  simulación, Modbus, .env). Al cambiar autorizaciones, tocar los tuplas de
  aquí, no la lógica de cada vista.
