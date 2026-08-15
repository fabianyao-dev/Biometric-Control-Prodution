# Diagnostico de seguridad y mejoras

> Revision del codigo del sistema de control biometrico de produccion.
> Fecha: 2026-08-11. Alcance: codigo fuente (Python), configuracion y operacion.
> Estado de cada hallazgo: desmarca el checkbox al resolverlo y anota la fecha.

---

## 1. Vulnerabilidades y riesgos de seguridad

### 1.1 Carga de DLLs por nombre (DLL hijacking) — MEDIA

- **Donde:** `src/hardware/biometric_sdk.py` (`ctypes.WinDLL("dpfpdd.dll")`, `ctypes.WinDLL("dpfj.dll")`).
- **Problema:** los DLLs de DigitalPersona se cargan por nombre, siguiendo el orden de
  busqueda de Windows (directorio de la app primero, luego CWD, luego PATH). Si un atacante
  coloca un `dpfpdd.dll` o `dpfj.dll` malicioso junto al `.exe` empaquetado o en el
  directorio de trabajo, Windows lo cargara en lugar del legitimo.
- **Impacto:** ejecucion arbitraria de codigo con los privilegios del proceso (operador del
  kiosco).
- **Mitigacion sugerida:** cargar los DLLs por ruta absoluta (`C:\Windows\System32\...`) o
  desde un directorio fijo de la instalacion, y/o verificar la firma digital antes de
  cargar. Documentar el directorio de instalacion de DigitalPersona como requisito.

- [ ] Resuelto (fecha: ______)

### 1.2 Plantillas biometricas en claro — MEDIA

- **Donde:** `src/database.py` (tabla `huellas_operador`, columna `huella_template`).
- **Problema:** las plantillas FMD de huellas se almacenan sin cifrado en un SQLite plano
  (`planta_corte.db`). Si se roba o copia el archivo, se obtienen las plantillas biometricas
  de todos los operadores.
- **Impacto:** compromiso de datos biometricos personales (datos sensibles); si el lector
  permite verificar contra plantillas externas, podria haber suplantacion.
- **Mitigacion sugerida:** cifrado a nivel de disco (BitLocker) en la PC fanless de
  produccion, permisos NTFS restrictivos sobre el archivo de BD, y/o cifrado del campo
  `fmd` en la aplicacion (caveat: habria que descifrar en memoria para comparar).

- [ ] Resuelto (fecha: ______)

### 1.3 Modbus TCP sin autenticacion ni cifrado — MEDIA

- **Donde:** `src/hardware/modbus_controller.py`.
- **Problema:** el protocolo Modbus TCP es plano (sin cifrado ni autenticacion). Cualquier
  equipo en la misma LAN que alcance la IP del modulo puede leer el contador y **escribir
  coils** (arrancar/pausar la maquina).
- **Impacto:** interrupcion o manipulacion de la produccion desde la red.
- **Mitigacion sugerida:** aislar la red industrial (VLAN dedicada) y restringir el acceso
  por firewall al puerto 502; nunca exponer `MODBUS_HOST` a redes no confiables.

- [ ] Resuelto (fecha: ______)

### 1.4 Sin bootstrap del primer operador admin — MEDIA

- **Donde:** `src/gui/admin_view.py` y `src/database.py` (roles).
- **Problema:** en una instalacion limpia la BD no tiene operadores; el acceso a
  Administracion requiere huella con rol `admin`, pero no existe nadie con ese rol. No hay
  forma de registrar al primer operador desde la UI (quien registra necesita ya ser admin).
- **Impacto:** riesgo de quedarse bloqueado fuera del sistema en una instalacion nueva o
  tras perder la BD; hay que crear operadores por fuera (p. ej. `test_flujo.py`).
- **Mitigacion sugerida:** definir un procedimiento de arranque (primer operador registrado
  se vuelve admin) o una clave de inicializacion unica; documentar el procedimiento.

- [ ] Resuelto (fecha: ______)

### 1.5 Sin bloqueo ni rate-limit en autenticacion — BAJA

- **Donde:** `src/gui/huella_modal.py`.
- **Problema:** los intentos de huella son infinitos y sin contador de fallos ni lockout.
  No hay registro visible de intentos fallidos consecutivos.
- **Impacto:** bajo (la autenticacion es biometrica), pero no hay mitigacion frente a
  fuerza bruta con plantillas falsas o dedos de todos los operadores.
- **Mitigacion sugerida:** contador de fallos por modal, aviso y espera tras N intentos,
  y registro en log de cada fallo.

- [ ] Resuelto (fecha: ______)

### 1.6 Fuga de hilos en HuellaModal — BAJA

- **Donde:** `src/gui/huella_modal.py` (`_escanea`/`_reintentar`) y
  `src/hardware/biometric_service.py` (`autenticar_operador`, `_lock_lector`).
- **Problema:** si el usuario cancela el modal mientras una captura esta en vuelo, el hilo
  de escaneo sigue corriendo (daemon) y retiene `_lock_lector` hasta el timeout de captura
  (~60 s). Cada reintento lanza un hilo nuevo que se encola en el lock; con la cola del
  modal ya drenada, los eventos quedan huerfanos y los hilos se acumulan.
- **Impacto:** lector ocupado por mas tiempo del esperado y consumo residual de memoria en
  usos repetidos.
- **Mitigacion sugerida:** bandera de cancelacion consultada dentro del ciclo de captura,
  y/o timeout de espera del lock en el hilo.

- [ ] Resuelto (fecha: ______)

### 1.7 Concurrencia del lector: enroll sin lock — BAJA

- **Donde:** `src/hardware/biometric_service.py`.
- **Problema:** `_lock_lector` solo protege `autenticar_operador`. `enrollar` y
  `capturar_huella` acceden al mismo SDK/lector sin lock, por lo que un registro de
  operador (AdminView) podria coincidir con una identificacion en curso y golpear el SDK
  simultaneamente.
- **Impacto:** comportamiento indefinido del SDK DigitalPersona.
- **Mitigacion sugerida:** serializar **todas** las operaciones del lector con el mismo
  `threading.Lock`.

- [ ] Resuelto (fecha: ______)

### 1.8 `dpfj_identify` con buffer de un solo candidato — BAJA

- **Donde:** `src/hardware/biometric_sdk.py` (`identificar`, buffer
  `DPFJ_CANDIDATE * 1` con `candidate_cnt = 1`).
- **Problema:** se asume que el SDK escribe como maximo un candidato. Si el SDK llena el
  buffer con mas entradas o no respeta la capacidad, hay riesgo de corrupcion de memoria.
  Ademas no se distingue el codigo `DPFJ_E_MORE_DATA`.
- **Impacto:** potencial corrupcion de memoria / resultados incorrectos.
- **Mitigacion sugerida:** asignar un buffer con la cantidad maxima de candidatos que se
  espera, validar el codigo de retorno y no confiar ciegamente en el tamano devuelto.

- [ ] Resuelto (fecha: ______)

---

## 2. Robustez y bugs potenciales

### 2.1 WAL y busy_timeout no configurados

- **Donde:** `src/database.py` (`obtener_conexion`).
- **Problema:** el codigo comenta "(SQLite + WAL)" pero **no** se ejecuta
  `PRAGMA journal_mode=WAL` ni se fija `busy_timeout`. Con varias conexiones
  (`check_same_thread=False`) escribiendo desde distintos hilos, puede aparecer
  "database is locked".
- **Accion:** habilitar WAL y `PRAGMA busy_timeout` en cada conexion, y corroborar el
  comportamiento con el checkpoint del turno corriendo en paralelo.

- [ ] Resuelto (fecha: ______)

### 2.2 Hilo de polling Modbus sin proteccion global

- **Donde:** `src/hardware/modbus_controller.py` (`_bucle_polling`).
- **Problema:** el try/except cubre la lectura del registro, pero una excepcion inesperada
  fuera de ese bloque (p. ej. en `_combinar_regs` o al obtener la conexion) mataria el hilo
  y el conteo se congelaria silenciosamente sin alerta.
- **Accion:** envolver el cuerpo del bucle en try/except para mantenerlo vivo, registrar el
  error y marcar el estado de conexion (ya hay `conectado()`).

- [ ] Resuelto (fecha: ______)

### 2.3 El lector no se cierra al salir

- **Donde:** `main.py` (`_salir`) y `src/hardware/biometric_service.py` (`cerrar`).
- **Problema:** al cerrar la app se llama a `controlador.cleanup()` pero no a
  `biometrico.cerrar()`, dejando el lector abierto.
- **Accion:** llamar a `cerrar()` en `_salir` (con try/except para no impedir el cierre).

- [ ] Resuelto (fecha: ______)

### 2.4 Vistas muertas: `register_view.py` e `identify_view.py` ~~Eliminadas~~

- **Donde:** ~~`src/gui/register_view.py`, `src/gui/identify_view.py` (junto con
  `main_original.py`, el backup que las usaba).~~
- **Problema:** ~~no se importan desde `main.py` (navegacion real: inicio, sesiones,
  admin, huella_modal). Cada una crea su propio `BiometricService`, lo que sugiere un
  uso incorrecto del singleton del SDK.~~
- **Accion:** ~~eliminar, o conservar solo como referencia documentada y quitar la
  creacion de servicios propios.~~

- [x] Resuelto (fecha: 2026-08-13): eliminados `register_view.py`, `identify_view.py`
  y `main_original.py`. Quedo pendiente purgar las dependencias que solo usaba el
  backup (ver 3).

### 2.5 Sin validacion del directorio de `DB_PATH` al arrancar

- **Donde:** `main.py` / `src/config.py`.
- **Problema:** si `DB_PATH` apunta a un directorio inexistente o no escribible,
  `sqlite3.connect` falla con un error opaco.
- **Accion:** validar directorio padre al arrancar y mostrar un mensaje claro.

- [ ] Resuelto (fecha: ______)

---

## 3. Mejoras operativas y de mantenimiento

- [ ] **Documentar el pin de version de los DLLs de DigitalPersona** (los que se cargan
      son "cualquiera que este en el sistema"; documentar versiones probadas en
      `requirements.txt`/README).
- [x] **Purgar dependencias no usadas por la app real**: ~~`customtkinter`, `darkdetect`,
      `pillow`, `packaging` solo los usa `main_original.py` (backup viejo)~~. Eliminadas
      de `requirements.txt` junto con el backup (2026-08-13).
- [ ] **Nota de red en README**: abrir el puerto 502 saliente en el firewall para el
      modulo Advantech, y recomendar VLAN dedicada (refuerza 1.3).
- [ ] **Estrategia de respaldo de la BD**: el checkpoint del turno no respalda; definir
      copia periodica de `planta_corte.db` (p. ej. tarea programada / copia al final del
      turno).
- [ ] **Path absoluto para `DB_PATH` en produccion**: documentar que con tareas
      programadas el CWD puede variar; usar rutas absolutas en el `.env` del fanless.
- [ ] **Revisar umbral de disimilitud** (`UMBRAL_DISIMILARIDAD`): calibrarlo con datos
      reales de la planta para balancear falsos rechazos vs. falsas aceptaciones.

---

## 4. Orden sugerido de atencion

1. **1.4** bootstrap admin (evita quedar bloqueado) y **2.1** WAL/busy_timeout
   (estabilidad diaria).
2. **1.1** carga segura de DLLs y **1.3** aislamiento de red (seguridad).
3. **1.2** cifrado/ACLs de la BD (biometria en reposo).
4. **1.7** y **1.6** (concurrencia y hilos del lector).
5. Resto de mejoras y documentacion.

---

## 5. Comandos de verificacion tras cambios

- `python main.py` (con `BIOMETRICO_KIOSKO=0` para ventana).
- `python test_modbus.py` (diagnostico del modulo, si hay `MODBUS_HOST`).
- `python test_flujo.py identificar <fmd>` (flujo contra la BD, requiere lector).
- Revisar `LOG_DIR` por errores de "database is locked" o hilos muertos.
