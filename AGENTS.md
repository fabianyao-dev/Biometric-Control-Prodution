# Guía Rápida para Agentes: Biometric-Control-Prodution

Este archivo contiene información crucial y específica del repositorio para que los agentes de OpenCode operen eficientemente y eviten errores comunes.

## Investigación y Contexto

Prioriza estas fuentes para entender el proyecto:

- **Fuentes Ejecutables (Preferir sobre Prose):**
  - Archivos de configuración (`README*`, `package.json`, `requirements.txt`, `*.spec`, `*.config.json`, `.env*`)
  - Scripts de `test/` (ejecutables y manuales) y suite automatizada en `tests/`
  - Flujos de CI/CD y pre-commit hooks
  - Configuración de OpenCode local (`opencode.json`)
- **Análisis de Código:** Si la arquitectura no está clara, inspecciona archivos clave que conectan el sistema (entrypoints, límites de paquetes, flujo de ejecución) en lugar de archivos aleatorios.

## Extracción de Información Clave

Busca hechos de alto impacto para un agente:

- **Comandos Exactos:** Comandos de desarrollo, construcción, pruebas (unitarias, integración), linting, formateo y type checking. Incluye secuencias obligatorias (ej. `lint -> typecheck -> test`).
- **Puntos de Entrada y Flujo:** Dónde inicia la aplicación (`python main.py` desde raíz), cómo se activan los HALs (Modbus vs. Simulación basado en `MODBUS_HOST`), y el punto de entrada para la GUI (`src/gui`).
- **Quirks Específicos del Repo:**
  - **Biometría (DigitalPersona):** Manejo de DLLs (`dpfpdd.dll`, `dpfj.dll`) en desarrollo vs. empaquetado (`_MEIPASS`, `os.add_dll_directory`). Tolerancia a ausencia de DLLs y hot-plug del lector. Filtrado de lectores por producto/fabricante (NO VID/`info.name`).
  - **Hardware Abstraction Layer (HAL):** Interfaz común para `ModbusController` y `SimulacionController`. El contador de cortes VIVE EN EL MÓDULO Modbus (no detectar flancos en Windows RTOS). Módulo actual: Advantech WISE-4060LAN (IP `10.0.0.1`, mapa Modbus en `.env`, little-endian para contador ch0).
  - **Empaquetado (PyInstaller):** Build `onedir` (`venv\Scripts\pyinstaller --noconfirm WTSControl.spec`), DLLs de SDK en `sdk/vendor/dpf/`, datos persistentes en `%USERPROFILE%\WTSControlData` (vía `BIOMETRICO_DIR_DATOS`), `config.json` en producción (migrado desde `.env`).
  - **Actualizaciones:** Vía HTTP local a demanda. El updater (`WTSControlUpdater.exe`) se lanza como subproceso, con `cwd=config.DIR_DATOS` para evitar problemas de bloqueo de archivo.
  - **Modo "Primera Pieza"**: Activado por defecto al abrir sesión. Suprime auto-paro por inactividad, maneja cortes temporales, y requiere huella para iniciar/finalizar. Usa escaneo QR para cargar trabajos.
  - **Trabajos por QR:** Formato `folio|num_part|cantidad_total`. El separador es ESTRICTO: solo `|`. La validación vive en `parsear_qr()` (`src/gui/huella_modal.py`, función pura) y `abrir_trabajo()` (`src/database.py`); ambas rechazan el resto de símbolos. Manejo de trabajos abiertos/cerrados, reanudación y finalización.
  - **Seguridad:** Seguro anti-paro/apagado (`SEGURO_PARO_SEGUNDOS`), seguro anti-corrida (`SEGURO_RAFAGA_SEGUNDOS`/`CORTES`).
- **Base de Datos:** SQLite (`planta_corte.db`), timestamps en `America/Monterrey`, soft-delete (`activo=0`), manejo de múltiples huellas por operador, tabla `trabajos` (folio PK, estado 'Abierto'/'Cerrado').
- **Configuración y Logs:** Carga vía `.env` (dev) o `config.json` (prod). Logs diarios rotados.
- **Permisos y Roles:** Gestión en `Administración → Roles`. Verificación vía `rol_tiene_permiso_operador()`. El rol `mantenimiento` tiene `autorizar_paro` por defecto.

## Comandos

```bash
# Suite automatizada: rápida, sin hardware y sin BD real
venv\Scripts\python -m pytest -q

# Lint
venv\Scripts\ruff check tests\

# Build
venv\Scripts\pyinstaller --noconfirm WTSControl.spec
```

- **`test/` NO es `tests/`:** `test/` son scripts MANUALES de diagnóstico (tocan hardware y BD real, y hacen `sys.exit(1)`); `tests/` es la suite automatizada. `pyproject.toml` fija `testpaths = ["tests"]` para que pytest no recolecte `test/`.
- **La suite nunca toca la BD real:** `tests/conftest.py` redirige `DB_PATH`/`LOG_DIR` a un temporal **antes** de importar `src`. Sin eso, `src/config.py` resuelve `DB_PATH` a `<raiz>/planta_corte.db` (el `.env` de dev lo deja vacío a propósito) y los tests migrarían la BD de la planta.
- **Límites de capa verificados por test:** `tests/test_arquitectura.py` falla si `src/domain/` importa Qt/SQLite, si `src/hardware/` importa `src/gui/`, o si `src/gui/` toca `biometric_sdk` sin pasar por `BiometricService`.
- **Refactor en curso:** la arquitectura objetivo es Ports & Adapters. `tests/test_arquitectura.py` y `tests/test_smoke_imports.py` ya vigilan las fronteras, así que no se pueden romper en silencio.

## Reglas de Escritura

- **Concisión:** Incluye solo información verificada y de alto impacto que un agente podría pasar por alto.
- **Verificabilidad:** Prefiere comandos y configuraciones sobre documentación narrativa.
- **Idioma:** Todo el contenido en español.
- **Omisión:** Excluye consejos genéricos, tutoriales largos, o información obvia del lenguaje/framework.
- **Formato:** Secciones cortas, listas con viñetas.
