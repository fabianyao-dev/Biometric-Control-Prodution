# Biometric-Control-Prodution

Sistema de **control biométrico de producción** para una planta de corte.
Se despliega como **kiosco de pantalla completa** en una PC fanless junto a la
máquina: el operador arranca y para la máquina con su huella, el sistema
registra sesiones y cortes por turno, y deja un historial de paros con causa y
autorización.

- GUI en **PySide6 (Qt)** con tema oscuro propio (QSS + Fusion).
- Autenticación por huella (SDK **DigitalPersona**, Windows-only).
- Control de relés y contador de cortes vía **Modbus TCP** (módulo Advantech),
  con **modo simulación** cuando no hay hardware.
- Todo el código, la UI y los logs están en **español**.

---

## Funcionalidades

- **Arranque de máquina con huella**: pulsar PLAY abre un modal que pide la
  huella; al autenticar se abre la sesión automáticamente y la máquina arranca.
- **Cierre de sesión**: requiere la huella del operador de la sesión o de un
  rol con autoridad (admin/supervisor).
- **Paros de producción**: botón PARO o paro automático por inactividad
  (`PARO_IDLE_TIMEOUT_S`). Pide motivo (cuadrícula de causas frecuentes) +
  huella para autorizar la reanudación.
- **Recuperación tras apagón**: si la app se cierra con una sesión "Activa"
  (corte de luz, crash), al reiniciar se detecta, se restaura el operador y el
  total de cortes del último checkpoint, y se exige autorizar o cerrar antes de
  iniciar una sesión nueva.
- **Checkpoint de cortes**: el total de la sesión activa se guarda cada
  `CORTES_GUARDAR_INTERVALO_MS` como respaldo ante cortes de luz.
- **Panel de Sesiones**: historial de sesiones (operador, inicio, cortes,
  estado, duración, número de paros) y detalle de paros por sesión.
- **Administración** (protegida por huella + rol `admin`):
  - **Operadores**: registro con captura de huella y rol, cambio de rol,
    eliminación (soft-delete).
  - **Causas de paro**: agregar / eliminar motivos (soft-delete).
  - **Roles**: agregar, renombrar y desactivar, y gestionar **permisos por rol**
    (autorizar paro, ver sesiones, acceder a administración).
- **Control de acceso por permiso**: Sesiones y Administración piden huella y
  verifican el permiso del rol contra la BD (no hay tuplas en `config.py`).

---

## Requisitos y plataforma

- **Windows** (dev y PC fanless de producción). La biometría usa el SDK de
  DigitalPersona (`dpfpdd.dll`/`dpfj.dll` vía ctypes). En el `.exe` los DLLs se
  **empaquetan** (ver [Empaquetado](#empaquetado-pc-fanless-pyinstaller)); en
  desarrollo necesitan estar instalados en el sistema. Sin DLLs ni lector, la
  app **sigue corriendo** (la biometría queda "no disponible" y se avisa al
  operador; el acceso por huella se deshabilita, pero el resto no crashea).
- **Python 3.12** con `venv/` del proyecto. Dependencias en `requirements.txt`.
- `tzdata` es obligatorio en Windows para `ZoneInfo("America/Monterrey")`; sin
  él `main.py` no arranca.

---

## Instalación

```bash
# Clonar / copiar el proyecto y crear el entorno (Python 3.12)
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# Configurar el entorno
copy .env.example .env
```

> En la PC de producción no hace falta Python: se instala el `.exe` empaquetado
> (ver [Empaquetado](#empaquetado-pc-fanless-pyinstaller)).

---

## Configuración (`.env`)

Copia `.env.example` a `.env` y ajusta los valores. El `.env` local está en
`.gitignore`; **nunca se sube al repo**.

| Variable | Descripción |
| --- | --- |
| `MODBUS_HOST` | IP del módulo Advantech. **Vacío** o `MODBUS_SIMULACION=1` → modo simulación (sin red). |
| `MODBUS_PORT` | Puerto Modbus TCP (default `502`). |
| `MODBUS_UNIT_ID` | Unit ID del esclavo (default `1`). |
| `MODBUS_START_COIL` | Coil del relevador START (arranque). |
| `MODBUS_PAUSE_COIL` | Coil del relevador PAUSE (paro). |
| `MODBUS_START_COIL_INVERTIDO` / `MODBUS_PAUSE_COIL_INVERTIDO` | `0` (default): pulso activo `True` (contacto cerrado, botón NA en paralelo). `1`: pulso invertido, activo `False` (contacto abierto) para cableados donde la máquina actúa al abrir el circuito (botón NA en serie / lógica NC). Ajusta solo el coil que lo requiera. |
| `MODBUS_COUNTER_REGISTER` / `MODBUS_COUNTER_WORDS` | Registro contador interno del módulo. El conteo de cortes lo hace el **módulo por hardware**; la PC solo hace polling y suma deltas. |
| `MODBUS_COUNTER_LITTLE_ENDIAN` | `1` (default, WISE-4060LAN) = contador de 32 bits con palabra baja primero; `0` = big-endian (alta primero). |
| `MODBUS_POLL_MS` | Intervalo de polling (default `500`). |
| `MODBUS_COUNTER_MAX_DELTA` | Delta máximo aceptable entre lecturas; saltos mayores se ignoran (reset del módulo). |
| `PULSO_DURACION_MS` | Duración del pulso a los coils (tipo botón). |
| `SEGURO_PARO_SEGUNDOS` | Seguro anti-paro/anti-apagado: bloquea PARO y apagado mientras la máquina esté en marcha y haya recibido un **corte real** en los últimos N segundos (default `3`). |
| `DB_PATH` | Ruta de la base SQLite. En el `.exe` empaquetado **no hace falta definirlo**: `DB_PATH` y `LOG_DIR` se generan solos en la carpeta de datos persistente (ver Empaquetado). Definir solo si se quiere otra ubicación. |
| `LOG_DIR` | Directorio de logs diarios (rotación a 30 días). En empaquetado apunta por defecto a `%USERPROFILE%\WTSControlData\logs`. |
| `BIOMETRICO_DIR_DATOS` | (Solo empaquetado) Variable de entorno del sistema para cambiar la carpeta de datos persistente (default `%USERPROFILE%\WTSControlData`). No se lee del `.env`. |
| `BIOMETRICO_KIOSKO` | `1` = kiosco pantalla completa (default); `0` = ventana normal. |

---

## Ejecutar (desarrollo)

```bash
python main.py                # kiosco (pantalla completa)
set BIOMETRICO_KIOSKO=0       # ventana normal (PowerShell)
python main.py
```

El punto de entrada es `main.py` desde la raíz (usa el paquete `src`). En
desarrollo, sin `MODBUS_HOST`, el sistema corre completo en **modo simulación**
(la GUI no cambia: mismo flujo, sin hardware).

---

## Flujo de operación

Estados de la máquina en la vista **Inicio**:

1. **EN ESPERA** → el operador pulsa PLAY, coloca su huella; se abre la sesión
   y la máquina pasa a **LISTA**.
2. **LISTA** → la máquina cuenta cortes. Si no hay cortes durante
   `PARO_IDLE_TIMEOUT_S`, se dispara un **paro automático**.
3. **PARO** → el operador (o un rol autorizado) elige la causa y coloca su
   huella; al autorizar, la máquina **reanuda**. El modal de paro **no se puede
   cerrar** hasta autorizar.
4. **Cierre**: pulsar el botón de poder pide huella y cierra formalmente la
   sesión (se guarda el total de cortes).

**Roles y permisos**: roles (`admin`, `operador`, ...) y **permisos por rol** se
gestionan desde **Administración → Roles** (no están hardcodeados). Permisos del
sistema: `autorizar_paro` (reanudar paros de otra persona, además del dueño de
la sesión), `acceso_sesiones` (ver Sesiones) y `acceso_admin` (entrar a
Administración). Por defecto `admin` tiene los tres y `supervisor` dos; al menos
un rol activo debe conservar `acceso_admin` (protección contra quedarse fuera).

> Al cambiar autorizaciones, edítalas en Administración, no en el código.

---

## Base de datos

SQLite (`planta_corte.db` en la raíz, o `DB_PATH` del `.env`), creado
automáticamente por `init_db()` en `src/database.py`.

Esquema relacional:

- `roles` — catálogo de roles (soft-delete).
- `operadores` — operadores (soft-delete) con rol; **una o varias huellas** en
  `huellas_operador` (una fila por plantilla; el registro pide mínimo 2 huellas
  distintas y rechaza si ya se capturó esa huella).
- `causas_paro` — motivos configurables de paro (soft-delete).
- `sesiones_produccion` — entrada/salida por turno (estado `Activa`/`Finalizada`).
- `paros_produccion` — paros vinculados a una sesión (causa, inicio/fin,
  autorizador).

Convenciones:

- **Soft-delete** (`activo=0`) en roles, operadores y causas de paro.
- Timestamps SIEMPRE en `America/Monterrey` (funciones `ahora_monterrey()` /
  `ahora_local()`), **no** `CURRENT_TIMESTAMP` nativo de SQLite (es UTC).
- `PRAGMA foreign_keys=ON`; conexiones `check_same_thread=False` (los hilos de
  la GUI y el polling escriben a la BD).

---

## Logs

`src/logging_config.py` → `configurar_logging()` se llama al importar `main.py`:

- Consola (desarrollo) + archivo diario en `LOG_DIR` (`produccion.log`).
- Rotación a medianoche, retención de 30 días.
- En un `.exe` sin consola `sys.stdout` es `None`; ya está protegido en
  `biometric_service.py`.

---

## Scripts de prueba (`test/`, manuales)

Muchos requieren hardware (lector / módulo Modbus). Se ejecutan con `venv`
desde la raíz del proyecto:

| Script | Uso |
| --- | --- |
| `test\test_lector.py` | Carga `dpfpdd.dll` directo (prueba del driver). |
| `test\test_captura.py [salida.fmd]` | Captura huella a archivo (Windows + lector). |
| `test\test_fmd.py` | Dos capturas y compara 1:1 y 1:N. |
| `test\test_flujo.py registrar <fmd> <nombre> \| identificar <fmd>` | Flujo contra la BD. |
| `test\test_modbus.py` | Diagnóstico del módulo Advantech (coils + registro contador). Usa el `.env`; sin `MODBUS_HOST` sale limpio. |
| `test\simulador_modbus.py` | Emulador Modbus TCP del módulo (contador auto-incremental + coils) para probar todo lo anterior SIN hardware. |

`test\test_modbus.py` admite flags: `--ip`, `--port`, `--reg`, `--words`,
`--coil 0 --pulso` (pulso de 300 ms tipo botón),
`--coil 1 --pulso-invertido` (pulso activo `False`, para cableado NC),
`--coil 1 --on/--off`.

Sin hardware, corre en **dos terminales**:

```bash
venv\Scripts\python test\simulador_modbus.py --velocidad 2   # terminal 1
venv\Scripts\python test\test_modbus.py --ip 127.0.0.1 --coil 0 --pulso   # terminal 2
```

En la terminal 1 puedes **controlar el contador** y ver los cambios de relevadores
(pulsos) y del contador en vivo:

```
Enter o +   +1 corte manual        c = correr contador     p = pausar contador
v N         velocidad a N cortes/seg (v 0 = pausar)         h/? = ayuda
q/salir     detener el simulador
```

Y para probar la GUI / `ModbusController` contra el simulador, apunta el `.env`
a `MODBUS_HOST=127.0.0.1` (y `MODBUS_PORT` si usas otro puerto).

---

## Empaquetado (PC Fanless, PyInstaller)

La PC de producción no debe tener Python. Build en **`onedir`** (más confiable
que `onefile` para Qt + SQLite) usando el `.spec` del proyecto:

```bash
venv\Scripts\pip install pyinstaller
venv\Scripts\pyinstaller --noconfirm WTSControl.spec
```

El resultado queda en `dist\WTSControl\` (`WTSControl.exe` + `_internal\`).
Copiar la **carpeta completa** a la PC de producción.

Notas:

- **Los DLLs de DigitalPersona se empaquetan**: `WTSControl.spec` toma los DLLs
  de `sdk/vendor/dpf/` (copiados del System32 de una máquina con el SDK 3.2.0.89)
  y los agrega con `binaries`, de modo que el `.exe` ya **no** depende de tener
  el SDK instalado en el sistema (la app los carga por nombre, y el bootloader
  de PyInstaller busca en `_internal`). Si se reinstala el paquete, los DLLs
  sobreviven porque viven en el repo (`sdk/vendor/`), no en `dist/`.
- **Driver USB del lector aparte**: empaquetar los DLLs no instala el driver
  del lector (el que hace que encienda al conectarlo). En la PC de producción
  se instala una vez con el MSI autocontenido `assets/SDK/x64/setup-x64.msi`
  (U.are.U 4500 Driver 4.1.0.217; requiere admin/UAC).
- El logo e íconos de la aplicación se encuentran en la carpeta `assets/` y se
  empaquetan automáticamente usando el `.spec` (`--add-data`/`--icon`; la
  aplicación los carga con `sys._MEIPASS`).
- **Datos persistentes fuera de la instalación**: en la primera ejecución el
  `.exe` crea la carpeta `%USERPROFILE%\WTSControlData` y ahí coloca el `.env`,
  `planta_corte.db` y `logs/`. Si ya existe un `.env`/`.db`/`logs` junto al
  `.exe` (o en `_internal`), **se migran una sola vez** a esa carpeta (nunca
  sobrescribe datos). Así, al actualizar solo se reemplaza la carpeta
  `dist\WTSControl` y toda la información persiste sin reconfigurar nada.
  Para otra ubicación: variable de entorno del sistema `BIOMETRICO_DIR_DATOS`.
- El `.env.example` se empaqueta (`--add-data ".env.example;."` en el `.spec`)
  como plantilla para instalaciones nuevas.
- Verifica con `test\test_lector.py` y `test\test_fmd.py` antes del rollout.

---

## Deployment (procedimiento de TI, requiere admin/UAC)

1. **Autostart**: crea una tarea en el Programador de Tareas que ejecute
   `ControlBiometrico.exe` al iniciar sesión (usuario del kiosco, privilegios
   normales; el sistema no debe pedir contraseña).
2. **Windows Update desactivado**: desactiva las actualizaciones automáticas
   (Política de Grupo o Regedit
   `HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU`, `NoAutoUpdate=1`)
   y planifica ventanas de mantenimiento para parches.

> ⚠️ Estos cambios son de sistema operativo: requieren confirmación explícita
> y privilegios de administrador.

---

## Arquitectura

```
main.py                       Orquesta app Qt, servicios compartidos y HAL
WTSControl.spec               Build PyInstaller onedir (empaqueta assets y DLLs)
sdk/vendor/dpf/               DLLs de DigitalPersona empaquetados (SDK 3.2.0.89)
assets/                       Logo, ícono y MSI del driver USB del lector
src/
├── config.py                 Config central (.env, simulación, Modbus)
├── database.py               SQLite: operadores, sesiones, paros, causas, permisos
├── logging_config.py         Logs consola + archivo diario (rotación 30 días)
├── gui/
│   ├── style.py              Tema oscuro propio (QSS + Fusion)
│   ├── inicio_view.py        Vista principal (máquina de estados, paros, 1.ª pieza)
│   ├── sessions_view.py      Historial de sesiones y paros
│   ├── admin_view.py         CRUD operadores/causas/roles/permisos (captura en hilo)
│   ├── huella_modal.py       Modal de autenticación reutilizable (SVG huella)
│   ├── selector_causas.py    Cuadrícula de causas de paro + buscador
│   ├── switch.py             Interruptor estilo iOS (QAbstractButton)
│   └── util.py               Helpers de UI (centrado, diálogos)
└── hardware/
    ├── biometric_sdk.py      ctypes sobre dpfpdd.dll/dpfj.dll (tolerante a faltantes)
    ├── biometric_service.py  Alto nivel: capturar, comparar, autenticar
    ├── modbus_controller.py  HAL Modbus TCP (módulo Advantech)
    └── simulacion_controller.py  HAL simulación (fallback / dev)
```

**Decisiones de diseño (no romperlas):**

- **El contador de cortes VIVE EN EL MÓDULO**: la PC solo hace polling y suma
  deltas del registro. NUNCA detectes flancos del sensor en Windows (no es
  RTOS; un micro-congelamiento perdería conteos).
- **Relevadores ACTIVOS-BAJO, tipo botón**: enviar pulso = pin/coil en
  OUTPUT/LOW (`True`) durante `PULSO_DURACION_MS` y volver a `False`. NUNCA
  dejar un relevador energizado (ver docstring de `modbus_controller.py`). La
  **polaridad del pulso es configurable por coil** (`.env`), para cableados
  donde la máquina actúa al abrir el circuito.
- **HAL intercambiable**: `crear_controlador()` en `main.py` elige Modbus o
  simulación según `MODBUS_HOST`. Respeta la interfaz común
  (`maquina_lista`, `maquina_pausada`, `reprisar_maquina`, `cortes_totales`,
  `reset_conteo`, `establecer_conteo`, `segundos_sin_corte`,
  `segundos_desde_arranque`, `simular_corte`, `maquina_detenida`, `conectado`,
  `cleanup`) para que la GUI no cambie.
- **Los hilos secundarios nunca tocan widgets de la GUI**: se comunican por
  `queue.Queue()` drenada en el hilo principal con `QTimer`.

---

## Troubleshooting

| Síntoma | Causa probable | Solución |
| --- | --- | --- |
| La biometría falla / "no hay lector" | Driver USB del lector no instalado o DLLs ausentes | Instala el driver `assets/SDK/x64/setup-x64.msi`; verifica con `test\test_lector.py` y `test\test_fmd.py`. |
| `main.py` no arranca con error de zona horaria | Falta el paquete `tzdata` | `venv\Scripts\pip install tzdata`. |
| "database is locked" en logs | Varias conexiones escribiendo sin `busy_timeout`/WAL | Ver `Diagnostico.md` §2.1. |
| La máquina no responde a START/PARO | Coils mal configurados en `.env` o cableado | `python test\test_modbus.py --ip <IP> --coil 0 --pulso`. |
| No cuenta cortes en simulación | La GUI no llama a `simular_corte()` | El contador simulado solo sube con la acción del botón de prueba. |
| El contador salta / cuenta basura | Delta mayor a `MODBUS_COUNTER_MAX_DELTA` (reset del módulo) | Ajusta `MODBUS_COUNTER_MAX_DELTA` y revisa el cable del sensor. |
| Sesión "Activa" al arrancar | Apagón o cierre abrupto anterior | Es el mecanismo de recuperación: autorizar o cerrar formalmente. |

---

## Documentación relacionada

- `Diagnostico.md` — revisión de seguridad y mejoras pendientes (checklist
  con severidad y orden sugerido de atención).
- `AGENTS.md` — reglas del agente y convenciones del proyecto.
