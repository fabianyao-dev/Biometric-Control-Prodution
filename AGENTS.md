# AGENTS.md — Biometric-Control-Prodution

App de escritorio (PySide6) para control de producción con biometría y PLC. Corre en Windows (PC fanless) y se empaqueta con PyInstaller. **No hay CI ni pre-commit**: los gates son locales.

## Arranque y entorno

- Windows + Python 3.12. Usa siempre `venv\Scripts\...`; el `python` global no tiene las dependencias.
- `venv\Scripts\python main.py` desde la raíz. El proyecto **no se instala** como paquete: `tests/conftest.py` inyecta la raíz en `sys.path`.
- Dependencias de desarrollo: `venv\Scripts\pip install -r requirements-dev.txt` (pytest, ruff, pyinstaller). `requirements.txt` es solo runtime.
- Sin lector de huellas en desarrollo: `set MODO_DEV=true` antes de arrancar (omite la autenticación biométrica). Nunca en producción. En producción, un `config.json` con `MODO_DEV=true` deja la app sin huella y la app lo avisa en el log al arrancar.
- Config de desarrollo: `.env` en la raíz (copia `.env.example`). Producción: `config.json` en la carpeta de datos.
- Carpeta de datos persistente: `%USERPROFILE%\WTSControlData` (override con `BIOMETRICO_DIR_DATOS`). Ahí viven `config.json`, `planta_corte.db` y `logs/`; nunca commitees nada de ahí.
- `config.json` solo **agrega** claves faltantes (`setdefault`); no migra valores viejos. Excepción: el cambio de hardware Advantech → Zelio **se migra solo** al arrancar el `.exe` (mapa J1/O1 + IP del PLC, con aviso en el log). Cualquier otro cambio de valores hay que editarlo a mano.
- HAL: `crear_controlador()` en `main.py` devuelve `ModbusController` si hay `MODBUS_HOST`; si no, `SimulacionController`. La GUI y las pruebas no deben depender del HAL real.

## Comandos

```bat
:: App (kiosco). Sin lector: set MODO_DEV=true primero
venv\Scripts\python main.py

:: Suite automatizada: rápida, sin hardware y sin BD real (~288 tests)
venv\Scripts\python -m pytest -q

:: Un archivo / un test / por palabra clave
venv\Scripts\python -m pytest tests\test_qr_parser.py -q
venv\Scripts\python -m pytest tests\test_export_auto.py -q -k decidir

:: Lint de la suite (gate práctico)
venv\Scripts\ruff check tests\

:: Build: el updater SIEMPRE primero, luego la app
venv\Scripts\pyinstaller --noconfirm tools\updater.spec
venv\Scripts\pyinstaller --noconfirm WTSControl.spec

:: Release completo: bump version.txt + updater + app + verificación + manifest/zip en release/
venv\Scripts\python tools\hacer_version.py <version>
```

- **Lint:** `ruff check .` **no está limpio** (deuda preexistente en `main.py`, `src/gui/*`, `src/database.py`, etc., y `Easy/` no está excluido). No lo uses como criterio de "todo bien" ni reformatees archivos ajenos; el gate es `ruff check tests\`. Config: 100 columnas, `py312`, reglas `F,E,W,I`.
- Si `ruff check tests\` falla en archivos que no tocaste, es deuda/WIP ajeno: repórtalo en vez de barrer el repo. Lo que agregues tú debe quedar limpio.

## Tests: `tests/` ≠ `test/`

- `tests/` es la suite automática (`pyproject.toml` fija `testpaths = ["tests"]`).
- `test/` son **scripts manuales de planta**: tocan hardware/BD real, arrancan el HAL y hacen `sys.exit(1)`. Nunca los metas en pytest ni los ejecutes sin hardware.
- `tests/conftest.py` redirige `DB_PATH` y `LOG_DIR` a un temporal **antes** de importar `src`, y define `MODBUS_HOST=""`, `MODO_DEV=true`, `QT_QPA_PLATFORM=offscreen`. Sin ese blindaje, un test que importe `src` migraría la BD real de la planta.
- Cualquier test nuevo debe usar los fixtures de BD (`db_temporal`, `bd_limpia` o el atajo `db`); no abras `src.database.DB_PATH` directamente.
- `tests/test_arquitectura.py` vigila fronteras: `src/domain/` puro (sin Qt/SQLite/red/`os.environ`), `src/hardware/` no importa `src.gui/` ni `main`, `src/database.py` no importa Qt, y `src/gui/` no toca `biometric_sdk` (solo `BiometricService`). El test de imports relativos está en `skip` como deuda conocida.
- `tests/test_smoke_imports.py` importa dinámicamente los módulos: si mueves/renombras archivos, actualízalo.

## Arquitectura (modular)

- Capas: `src/domain/` (lógica pura, sin Qt/SQLite/red/env), `src/hardware/` (HAL, sin GUI/main), `src/database.py` (sin Qt), `src/gui/` (puede conocer database/config). `src/gui/componentes/` es UI compartida y no debe depender de un módulo concreto.
- Módulos: cada subcarpeta de `src/gui/modulos/` (sin `_`, **sin `__init__.py`**) con `inicio_view.py` o `view.py` se auto-descubre al arrancar (`loader.descubrir()`), se registra y se sincroniza con la BD. El host es `src/gui/inicio_shell.py` (`InicioShell`); el módulo principal vive en `src/gui/modulos/corte/`. Su vista se divide en mixins en `src/gui/modulos/corte/inicio/` (sesión, máquina, paro, mantenimiento, primera pieza, trabajo, seguridad). La administración vive en `src/gui/admin/` (`view.py` + mixins por tab + `widgets.py`; el editor de rutinas Easy en `rutinas_easy/`).
- `main.py` es el composition root: instancia `BiometricService`, HAL, `ContextoApp` y programa el export automático.

## Hardware actual: Zelio Logic 2 SR3 + SR3NET01BD

- El hardware vigente es **Zelio** con `MODBUS_CMD_MODE=registro` (FC06). El modo `coil` (Advantech WISE-4060LAN) queda solo como compatibilidad; no lo tomes como el mapa actual.
- El NET01BD **no expone coils**. Los comandos son bits dentro de palabras J: J1 (dir 16), bits 0=marcha, 1=paro, 2=verde, 3=ámbar, 4=roja, 5=alarma. J2 y J3 no controlan nada; J4 (dir 19) solo lleva el heartbeat.
- El contador de cortes vive en el **PLC**, en O1 (dir 20), 16 bits, **1 palabra**. O2 es la palabra de pulsos, **no** la palabra alta: leer 2 palabras corrompe el valor y pierde cortes. El wrap a 65535 lo resuelve el HAL.
- El PC **nunca** cuenta flancos localmente (Windows no es RTOS); solo hace polling.
- La decisión del color de la torre es de la GUI (`InicioView._estado_torre`, en `inicio/seguridad_mixin.py`); el HAL solo escribe bits. El parpadeo de alarma lo hace el hilo de polling (`pulso_alarma` solo abre la ventana).
- `PRIMERA_PIEZA_TIMEOUT_S` es la tolerancia ámbar→rojo+alarma y aplica a todo paro real. **No** confundir con `PARO_IDLE_TIMEOUT_S` (auto-paro por inactividad, 1 min).
- Mapa y notas de campo: `MAPA_MODBUS_ZELIO.md`. Para Zelio usa `test/simulador_plc.py`, `test/test_modbus_zelio.py` (solo lectura por defecto) y `test/monitoreo_zelio.py`; `test/simulador_modbus.py` y `test/test_modbus.py` son del Advantech legacy.

## Datos y trabajos

- SQLite `planta_corte.db`; `init_db()` aplica migraciones aditivas al arrancar. Timestamps en `America/Monterrey`.
- Soft-delete con `activo=0`; no borres filas de operadores/huellas.
- Un operador puede tener varias huellas. La autenticación y el alta viven en `src/gui/componentes/huella_modal.py`.
- Trabajos por QR: formato **estricto** `folio|num_part|cantidad_total`; el único separador válido es `|`. La validación está duplicada en `parsear_qr()` (`src/gui/componentes/huella_modal.py`, función pura) y `abrir_trabajo()` (`src/database.py`): si cambias una, cambia la otra y su test (`tests/test_qr_parser.py`).
- Estados de trabajo `Abierto`/`Cerrado`, reanudación y cierre. El tiempo efectivo se arma con segmentos en `trabajos_sesiones`, no con un solo timestamp.
- Permisos: `rol_tiene_permiso_operador()`; el rol `mantenimiento` trae `autorizar_paro` por defecto.

## Reportes y export automático

- `src/reportes/export_auto.py`: snapshot **parcial** cada hora (`Sesiones_<fecha>_parcial.xlsx`, se sobrescribe) y cierre **final** del día (`Sesiones_<fecha>.xlsx`), cada uno en `<dir>/<fecha>/`. El dir por defecto es `<carpeta de datos>/exportaciones`.
- Un día se cierra cuando ya no tiene sesiones `Activa`, no a una hora fija. Se dispara al cerrar la última sesión (`sesion_cambiada`) y, como respaldo, en `closeEvent`. Al arrancar hay catch-up de días pendientes (tope `DIAS_CATCHUP_MAX`).
- Las decisiones (`decidir`, `decidir_hoy`) son puras; el hilo, la `queue.Queue` y el `QTimer` viven en `main.py`. Mantén esa separación para poder testear sin Qt/hora real.

## Empaquetado y actualizaciones

- PyInstaller `onedir`. Los `*.spec` son código versionado (no están en `.gitignore`): no los regeneres a ciegas.
- Las DLLs del SDK de DigitalPersona (`dpfpdd.dll`, `dpfj.dll`) se toman de `sdk/vendor/dpf/`; el `.spec` las bundlea.
- Datos persistentes fuera de `dist/` para sobrevivir actualizaciones; `DB_PATH`/`LOG_DIR` se resuelven solos en la carpeta de datos.
- El updater (`WTSControlUpdater.exe`) se lanza como subproceso con `cwd=config.DIR_DATOS` para evitar bloqueos de archivo. La app lo lleva embebido en `_internal/updater/`, por eso se compila antes.
- `version.txt` es la fuente de la versión. `tools/hacer_version.py` hace bump, builds, verifica el exe/DLLs/updater y deja `manifest.json` + zip en `release/`.

## Biometría (DigitalPersona)

- Tolerar ausencia de DLLs y lector desconectado: la app debe arrancar y funcionar en modo simulación/`MODO_DEV`.
- Carga de DLLs distinta en desarrollo vs. empaquetado (`_MEIPASS`, `os.add_dll_directory`).
- Filtra lectores por **producto/fabricante**, no por VID ni `info.name`.
- La GUI no importa `biometric_sdk` directamente: pasa por `BiometricService` (`src/hardware/biometric_service.py`).

## Integración Easy

- `src/gui/modulos/corte/easy/agente.py` envía la petición JSON por TCP al cargar un trabajo (protocolo v2, `enviar_pasos()`). `EASY_HOST` vacío desactiva la integración. La validación pura vive en `src/domain/easy.py`.
- `enviar_pasos()` / `ServicioEasy.ejecutar_rutina()` corre en un hilo daemon y el callback se ejecuta **en ese hilo**. La UI debe publicarse con `QTimer.singleShot(0, ...)`; nunca tocar widgets desde el callback.
- `Easy/` es un proyecto aparte (cliente/servidor de prueba, venv y `AGENTS.md` propios). No lo mezcles con la app ni esperes que pytest/ruff limpios lo cubran.

## Convenciones

- Código, mensajes, comentarios y docs en español; conserva el estilo y los nombres existentes.
- No edites `.env`, `planta_corte.db`, `logs/`, `dist/`, `build/`, `release/` ni `test_pc/`.
- Módulos nuevos: copia `src/gui/modulos/_plantilla/` a `src/gui/modulos/<clave>/` (sin `_`) con `inicio_view.py` o `view.py`; se descubren y registran solos. Expón `MODULO_INFO`, `crear_vista`/`*View` y opcionalmente `admin_tabs`. No crees `__init__.py`.
- Antes de dar por terminado: `venv\Scripts\python -m pytest -q` y `venv\Scripts\ruff check tests\`.
