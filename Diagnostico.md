# Diagnostico de seguridad y mejoras

> Revision del codigo del sistema de control biometrico de produccion.
> Fecha: 2026-08-11 (auditoria inicial), 2026-08-20 (seccion 6) y
> 2026-08-24 (auditoria integral por areas, seccion 7).
> Alcance: codigo fuente (Python), configuracion, empaquetado y operacion.
> Estado de cada hallazgo: desmarca el checkbox al resolverlo y anota la fecha.
> La seccion 7 es el diagnostico vigente: consolida el estado de la seccion 6
> (verificado: TODO sigue abierto) y agrega ~25 hallazgos nuevos con evidencia
> archivo:linea.

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
  tras perder la BD; hay que crear operadores por fuera (p. ej. `test\test_flujo.py`).
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

## 6. Auditoria integral (2026-08-20)

> Re-lectura completa del codigo fuente (`main.py`, `src/config.py`,
> `src/database.py`, `src/logging_config.py`, `src/gui/*`, `src/hardware/*`).
> Estado verificado de cada hallazgo: confirma si los puntos 1-5 siguen
> abiertos y agrega los nuevos. Severidades: Critica / Alta / Media / Baja.

---

### 6.1 Seguridad

#### 6.1.1 [CRITICA] Operador Temporal con rol `admin` y acceso sin huella

- **Donde:** `src/database.py` (`obtener_operador_temporal`, lineas 536-565) y
  `src/hardware/biometric_service.py` (`autenticar_operador`, 114-149).
- **Problema:** cuando `listar_fmds()` esta vacio (instalacion nueva, o porque
  se desactivaron todos los operadores), `autenticar_operador()` devuelve el
  **"Operador Temporal (dev)" sin tocar el lector**, y ese operador se crea con
  **rol `admin`**. Como `admin` tiene `acceso_admin`, cualquier persona puede
  entrar a Administracion y modificar roles/permisos **sin autenticarse**.
  No es solo un modo "dev inocuo": basta con desactivar todos los operadores
  (o que se pierda la BD de operadores) para abrir la puerta.
- **Impacto:** escalada total de privilegios sin credenciales en cualquier
  kiosco sin operadores reales registrados.
- **Mitigacion sugerida:** crear el temporal con un rol **sin** `acceso_admin`
  (p. ej. `operador`), o exigir factor de autenticacion para Administracion
  incluso en modo dev, o implementar un **bootstrap del primer admin** (el
  primer operador registrado se vuelve admin). Documentar en `Diagnostico.md`
  el procedimiento.

- [ ] Resuelto (fecha: ______)

#### 6.1.2 [ALTA] Plantillas biometricas en claro (persiste de 1.2)

- **Confirmado:** la BD `planta_corte.db` guarda los FMD sin cifrado. Sigue
  abierto. Mitigacion: BitLocker + ACLs NTFS sobre el archivo y la carpeta de
  datos (`%USERPROFILE%\WTSControlData`).

- [ ] Resuelto (fecha: ______)

#### 6.1.3 [ALTA] Modbus TCP sin autenticacion ni cifrado (persiste de 1.3)

- **Confirmado:** `src/hardware/modbus_controller.py` habla Modbus TCP plano.
  Cualquier equipo en la LAN puede leer el contador y escribir coils
  (arrancar/parar la maquina). Seguir: VLAN industrial dedicada + firewall al
  puerto 502.

- [ ] Resuelto (fecha: ______)

#### 6.1.4 [MEDIA] Carga de DLLs: mejorada en empaquetado, persiste en dev/fallback

- **Donde:** `src/hardware/biometric_sdk.py` (`_ruta_dll`, 176-203).
- **Estado:** en el `.exe` (frozen) se carga por ruta absoluta desde
  `_MEIPASS`/`_internal` y se registra con `os.add_dll_directory`; esto mitiga
  el secuestro por directorio de trabajo. **Pero** si el DLL no esta en la
  carpeta interna (empaquetado incompleto) o en desarrollo, hace `return
  nombre` y cae a carga por nombre (buscador de Windows: dir de la app, CWD,
  PATH). Un `dpfpdd.dll`/`dpfj.dll` malicioso en el CWD o junto al .exe seria
  cargado.
- **Mitigacion sugerida:** verificar la firma digital de los DLLs antes de
  cargarlos (WinVerifyTrust) o rechazar el fallback por nombre en produccion
  (log fatal + `disponible=False` en lugar de intentar por nombre).

- [ ] Resuelto (fecha: ______)

#### 6.1.5 [MEDIA] Sin bloqueo ni rate-limit de autenticacion (persiste de 1.5)

- **Confirmado:** `src/gui/huella_modal.py` reintenta sin limite ni espera
  progresiva. Falta: contador de fallos, aviso y pausa tras N intentos, y log
  de cada fallo (hoy solo hay `log.warning` en rechazos por rol).

- [ ] Resuelto (fecha: ______)

#### 6.1.6 [MEDIA] `dpfj_identify`: buffer de 1 candidato + `fmd_idx` sin validar

- **Donde:** `src/hardware/biometric_sdk.py` (`identificar`, 553-599).
- **Confirmado (1.8) y ampliado:** `candidates = (DPFJ_CANDIDATE * 1)()` con
  `candidate_cnt=1`; si el SDK devuelve mas candidatos del esperado hay riesgo
  de corrupcion de memoria. Ademas, `lista_fmds[idx]` (linea 594) indexa sin
  verificar `0 <= idx < len(lista_fmds)`: un indice fuera de rango lanza
  IndexError (capturado como error generico, pero es un fallo evitable).
- **Mitigacion:** buffer dimensionado por `candidate_cnt` real, tratar
  `DPFJ_E_MORE_DATA` y validar el indice antes de usar.

- [ ] Resuelto (fecha: ______)

#### 6.1.7 [MEDIA] Concurrencia del lector sin lock global (persiste de 1.7)

- **Confirmado:** `src/hardware/biometric_service.py` protege con
  `_lock_lector` solo a `autenticar_operador`; `enrollar()`/`capturar_huella()`
  (usadas por AdminView) acceden al mismo SDK sin lock. Una captura de registro
  puede solaparse con una identificacion y golpear el SDK en paralelo.
- **Mitigacion:** serializar **todas** las operaciones del lector con el mismo
  `threading.Lock` (tambien `enrollar` y `capturar_huella`).

- [ ] Resuelto (fecha: ______)

#### 6.1.8 [BAJA] Fuga de hilos en HuellaModal (persiste de 1.6)

- **Confirmado:** al cancelar un modal con una captura en vuelo, el hilo
  `_escanea` sigue reteniendo el lector hasta el timeout (~60 s) y cada
  reintento lanza un hilo nuevo. Añadir bandera de cancelacion consultada en el
  ciclo de captura y/o timeout de espera del lock.

- [ ] Resuelto (fecha: ______)

#### 6.1.9 [BAJA] Fuga de informacion: errores SQL expuestos en la UI

- **Donde:** `src/database.py` `guardar_operador` (linea 461) y
  `actualizar_permisos_rol` (linea 401) devuelven `f"Error en base de datos:
  {str(e)}"` a la interfaz.
- **Problema:** el operador ve detalles internos (rutas, mensajes de SQLite)
  en lugar de un mensaje generico. Riesgo bajo, pero innecesario.
- **Mitigacion:** loggear el detalle y mostrar solo "Error interno de base de
  datos".

- [ ] Resuelto (fecha: ______)

#### 6.1.10 [BAJA] Boton "Salir" sin confirmacion ni control del escritorio

- **Donde:** `main.py` (`_salir`, 343-346).
- **Problema:** cualquiera puede cerrar la app con un clic y quedar en el
  escritorio de Windows sin pedir nada. Si el kiosco no bloquea el shell a
  nivel de SO, un operador podria manipular el equipo.
- **Mitigacion:** confirmacion al salir, ocultar el boton al operador (dejarlo
  solo a mantenimiento) y/o reforzar con politicas de kiosco de Windows
  (shell = la app, sin acceso al escritorio).
- **Parcial (7.2.2, 2026-08-24):** el cierre ya esta bloqueado si la maquina
  esta en marcha; quedan pendientes confirmacion/rol y endurecimiento del
  kiosco a nivel SO.

- [ ] Resuelto (fecha: ______)

#### 6.1.11 [BAJA] Sin auditoria de acciones administrativas

- **Problema:** no hay registro persistente de quien registro/elimino
  operadores, cambio roles o permisos, o edito causas (solo logs de aplicacion
  no estructurados). Ante un incidente no hay trazabilidad.
- **Mitigacion:** tabla `auditoria` (fecha, operador, accion, detalle) escrita
  desde AdminView, o al menos lineas de log estructuradas.

- [ ] Resuelto (fecha: ______)

---

### 6.2 Robustez y bugs

#### 6.2.1 [MEDIA] Sin WAL ni busy_timeout en las conexiones (persiste de 2.1)

- **Confirmado:** `src/database.py` `obtener_conexion` (66-73) solo pone
  `PRAGMA foreign_keys=ON`. No hay `journal_mode=WAL` ni `busy_timeout`.
  Escriben desde varios hilos: el checkpoint de la sesion (hilo principal
  cada 30 s) y el hilo de autenticacion (p. ej. `obtener_operador_temporal`
  inserta en un hilo de captura). Riesgo real de "database is locked".
- **Mitigacion:** agregar en cada conexion:
  `PRAGMA journal_mode=WAL;` y `PRAGMA busy_timeout=5000;`.

- [ ] Resuelto (fecha: ______)

#### 6.2.2 [MEDIA] Hilo de polling Modbus sin try/except global (persiste de 2.2)

- **Confirmado:** en `src/hardware/modbus_controller.py` el try/except de
  `_poll_contador` cubre la lectura, pero `_combinar_regs` (linea 208) esta
  fuera del bloque. Una excepcion ahi (o en `_stop.wait`) mataria el hilo y el
  conteo se congelaria sin alerta. Envolver todo el cuerpo del bucle.

- [ ] Resuelto (fecha: ______)

#### 6.2.3 [MEDIA] El lector no se cierra al salir (persiste de 2.3)

- **Confirmado:** `main.py` llama `controlador.cleanup()` pero jamas
  `biometrico.cerrar()`; el lector queda abierto al salir. Agregarlo en
  `_salir`/`closeEvent` con try/except.

- [ ] Resuelto (fecha: ______)

#### 6.2.4 [BAJA] `init_db` crea el directorio pero no valida permisos (2.5 parcial)

- **Estado:** la creacion del directorio de `DB_PATH` ya esta resuelta
  (`os.makedirs`, database.py linea 80). Falta validar **escritura real** al
  arrancar: si la carpeta existe pero no es escribible, `sqlite3.connect`
  falla con un error opaco en el primer `INSERT`.

- [ ] Resuelto (fecha: ______)

#### 6.2.5 [BAJA] Carrera benigna checkpoint vs cierre de sesion

- **Donde:** `src/gui/inicio_view.py` (`_checkpoint_cortes`, 464-474) programa
  su propio `QTimer.singleShot`; `_apagar_maquina` lo deja sin efecto via el
  check `self.sesion_id is not None`. Funciona, pero conviene invalidar el
  timer explícitamente al cerrar para evitar una ultima escritura de un total
  distinto al final.

- [ ] Resuelto (fecha: ______)

#### 6.2.6 [BAJA] F-strings con constantes en SQL (fragil)

- **Donde:** `src/database.py` `listar_fmds` (linea 472) y
  `listar_huellas_operador` (linea 500).
- **Problema:** hoy no son inyectables (las variables son constantes), pero el
  patron f-string en SQL es fragil a futuro. Usar parametros siempre.

- [ ] Resuelto (fecha: ______)

#### 6.2.7 [BAJA] Codigo muerto en `src/database.py`

- `sesion_activa_actual()` (721), `obtener_operador_de_sesion()` (751) y
  `resumen_dia()` (841) no se usan en la app. Eliminar o documentar como API
  de reportes.

- [ ] Resuelto (fecha: ______)

#### 6.2.8 [BAJA] Vistas cacheadas sin refresco al reentrar

- **Donde:** `main.py` `mostrar_vista` (321-337) cachea las vistas.
  `AdminView` no recarga tablas al volver a entrar: si un admin cambio roles en
  otra sesion, la vista muestra datos obsoletos. `SessionsView` tiene boton
  "Actualizar" (mitiga). Recomendacion: recargar en `showEvent` o al hacer
  visible la vista.

- [ ] Resuelto (fecha: ______)

---

### 6.3 Operacion

- [ ] **Respaldo de la BD:** sigue sin estrategia. El checkpoint del turno no
      respalda. Definir copia periodica de `planta_corte.db` (tarea programada
      o copia al cierre del turno).
- [ ] **Documentar "Salir con sesion activa":** al cerrar sin cerrar la
      sesion, esta queda "Activa" y se recupera al reiniciar (por diseno).
      Avisar/confirmar al operador.
- [ ] **Refresco de datos obsoletos** (ver 6.2.8).
- [ ] **Calibrar `UMBRAL_DISIMILARIDAD`** (persiste del punto 3) con datos
      reales de la planta.
- [ ] **Documentar version de los DLLs de DigitalPersona** y del SDK probado
      (persiste del punto 3).

---

### 6.4 Orden sugerido de atencion (2026-08-20)

1. **6.1.1** quitar `acceso_admin` al Operador Temporal / bootstrap admin
   (critica, escalada sin credenciales).
2. **6.2.1** WAL + busy_timeout (estabilidad diaria, evita "database locked").
3. **6.1.4** firma/verificacion de DLLs y eliminar fallback por nombre en
   produccion.
4. **6.1.3** aislamiento de red Modbus (VLAN/firewall) — accion de operacion.
5. **6.1.6 / 6.1.7 / 6.2.3 / 6.2.2** correcciones de robustez del SDK y
   Modbus.
6. **6.1.2** cifrado/ACLs de la BD biometrica (BitLocker).
7. **6.1.10 / 6.1.11** kiosco endurecido + auditoria.

---

### 6.5 Comandos de verificacion tras cambios

- `python main.py` (con `BIOMETRICO_KIOSKO=0` para ventana).
- `python test\test_modbus.py` (diagnostico del modulo, si hay `MODBUS_HOST`).
- `python test\test_flujo.py registrar <fmd> <nombre>` y `identificar <fmd>`
  (requiere lector).
- Revisar `LOG_DIR\produccion.log` por "database is locked" o hilos muertos.

---

## 7. Auditoria integral por areas (2026-08-24)

> Re-auditoria completa dividida en tres frentes: (a) hardware/HAL/biometria,
> (b) datos/config/updater/empaquetado, (c) GUI/flujos de estado. Cada
> hallazgo con evidencia `archivo:linea`. Severidades: Critica/Alta/Media/Baja.
> **Estado de la seccion 6:** verificado hoy, NINGUN hallazgo resuelto; los
> que aqui se amplian se referencian (6.x.y).

---

### 7.1 Estado de la seccion 6 (verificado 2026-08-24)

- **6.1.1 [CRITICA] CONFIRMADO ABIERTO:** `obtener_operador_temporal`
  (`database.py:553-582`) sigue creando el temporal con rol `admin`
  (lineas 566-575) y `biometric_service.py:142` lo devuelve sin tocar el
  lector. Sigue siendo la prioridad #1.
- **6.2.3 CONFIRMADO ABIERTO:** grep de `biometrico.cerrar()` en `main.py`
  sin resultados; solo lo llaman los scripts de `test/`.
- **6.2.1 CONFIRMADO ABIERTO:** `obtener_conexion` sigue poniendo solo
  `PRAGMA foreign_keys=ON`.
- El resto de 6.x: sin cambios observados; todos siguen abiertos.

---

### 7.2 Hallazgos nuevos — ALTA

#### 7.2.1 [ALTA] Escrituras de coils sin verificar el retorno: fallos de START/PAUSE silenciosos

- **Donde:** `src/hardware/modbus_controller.py:201,438,472`
  (`_aplicar_paro_inicial`, `_escribir_coil`, `_pulso_coil`).
- **Problema:** en pyModbusTCP 0.3.x, `write_single_coil` devuelve `False`
  ante CUALQUIER error (de red y respuestas de excepcion Modbus) SIN lanzar
  excepcion. El codigo solo maneja el camino de excepcion, que nunca ocurre;
  un `False` se loguea como exito ("Coil -> ...").
- **Impacto:** el latch PAUSE puede no escribirse y la maquina SIGUE CORTANDO
  con la app creyendo que esta en paro (y viceversa con START). El paro
  inicial seguro puede marcarse aplicado sin haberse escrito. Un error Modbus
  puro ni siquiera dispara `_desconectar()` ni la alerta de enlace.
- **Mitigacion:** chequear el booleano de cada escritura y/o read-back con
  `read_coils` (el patron ya existe en `test\test_modbus.py`); reintentar y
  marcar enlace caido si falla.

- [ ] Resuelto (fecha: ______)

#### 7.2.2 [ALTA] Boton "Salir" cierra la app con maquina en marcha y sesion activa (amplia 6.1.10)

- **Donde:** `main.py:185,422-431`; `modbus_controller.py:492-501`.
- **Problema:** el seguro anti-apagado protege solo al boton PARO/apagado de
  InicioView; `_salir` del header no verifica sesion ni `segundos_sin_corte`.
  Peor: `cleanup()` detiene el polling SIN escribir el coil PAUSE, asi que la
  maquina queda fisicamente cortando, sin conteo ni supervision, hasta el
  siguiente arranque.
- **Impacto:** hueco de SEGURIDAD FISICA de planta, no solo de datos.
- **Mitigacion:** mismo guard que el apagado de InicioView en `_salir`;
  opcionalmente latchear PAUSE en `cleanup()` si la maquina estaba en marcha.

- [x] Resuelto (fecha: 2026-08-24):
  - `InicioView.aplicacion_puede_cerrarse()`: bloquea el cierre con un
    aviso mientras `maquina_detenida()` sea False (hay que parar primero
    con PARO); con maquina detenida se permite salir aunque quede sesion
    'Activa' (se recupera al arrancar, como tras un apagon).
  - `main.py`: el guard vive en `closeEvent` (choke point unico: cubre el
    boton Salir, Alt+F4 y el cierre del sistema); `_salir` solo hace
    `close()`. El doble `cleanup()` previo desaparece.
  - `ModbusController.cleanup()`: escribe el latch PAUSE SINCRONAMENTE
    bajo `_lock_modbus` antes de desconectar (espera pulsos en vuelo),
    verifica el retorno (pyModbusTCP devuelve False sin lanzar) y loguea
    ERROR pidiendo verificacion manual si no pudo. Re-latchear con la
    maquina ya detenida es inocuo.
  - Verificacion: `py_compile` OK en los tres archivos.

#### 7.2.3 [ALTA] Los permisos ignoran el soft-delete del rol

- **Donde:** `src/database.py:354-364` (`rol_tiene_permiso_operador`).
- **Problema:** el JOIN va directo `operadores -> permisos_roles`, sin pasar
  por `roles` ni filtrar `r.activo=1`. Un rol desactivado RETIENE todos sus
  permisos para sus operadores (`autorizar_paro`, `acceso_admin`,
  `actualizar_app`), mientras `roles_con_permiso` (solo mensajes) si filtra.
- **Impacto:** la unica revocacion real es reasignar operador por operador;
  desactivar un rol desde Administracion NO revoca nada.
- **Mitigacion:** agregar `JOIN roles r ON r.id=o.rol_id AND r.activo=1`.

- [x] Resuelto (fecha: 2026-08-24):
  - `rol_tiene_permiso_operador`: ahora pasa por `roles` exigiendo
    `r.activo=1` (la autenticacion ya solo aceptaba operadores activos, asi
    que el filtro de rol cierra el hueco completo).
  - **Guard anti-lockout nuevo en `eliminar_rol`**: devuelva (ok, mensaje) y
    rechaza desactivar al ultimo rol activo con `acceso_admin` (mismo guard
    que `actualizar_permisos_rol`). Necesario porque el bug ENMASCARABA ese
    segundo hoyo: al respetar roles inactivos, desactivar el ultimo rol
    admin habria dejado a nadie con acceso a Administracion. Consumidor
    actualizado (`AdminView._eliminar_rol`) muestra el mensaje de rechazo.
  - Verificado con BD temporal: operador con rol activo tiene el permiso;
    tras desactivar el rol lo pierde; `eliminar_rol(admin)` rechazado.
    `py_compile` OK.

#### 7.2.4 [ALTA] FINALIZAR TRABAJO durante Primera pieza crea doble paro y paro huerfano

- **Donde:** `src/gui/inicio_view.py:936-982` (`_boton_finalizar_trabajo` /
  `_trabajo_finalizado_manual`) y `:817-832` (`_entrar_primera_pieza`).
- **Problema:** el boton es visible en ESPERA TRABAJO (modo activo) y el
  handler llama `_entrar_primera_pieza()` SIN cerrar el paro de Primera pieza
  previo: `_primera_pieza_paro_id` se sobrescribe y la fila vieja queda con
  `fin_paro IS NULL` para siempre ("En curso" eterno en Sesiones). Ademas
  `suspender_conteo()` reinicia el contador de setup a mitad de modo.
- **Mitigacion:** hacer `_entrar_primera_pieza` idempotente (si ya hay modo
  activo, cerrar antes el paro vigente o salir sin re-registrar).

- [x] Resuelto (fecha: 2026-08-24):
  - `_entrar_primera_pieza` ahora es IDEMPOTENTE: si el modo ya esta activo,
    conserva el paro vigente y los cortes de setup acumulados (solo
    reasegura switch/estado visual y loguea); NO re-registra paro ni vuelve a
    llamar `suspender_conteo()`. Cubre tanto FINALIZAR TRABAJO en espera como
    la re-entrada desde `_verificar_meta_trabajo` (mitiga la mitad del doble
    paro de 7.3.2, que sigue abierto por la meta instantanea).
  - Guard defensivo adicional: sin sesion activa la solicitud se ignora con
    log (antes `iniciar_paro(None)` violaria la FK).
  - Verificado con metodo real contra BD temporal + controlador stub:
    entrada normal -> 1 paro abierto; re-entrada -> mismo paro, una sola
    suspension; sin sesion -> ignorado. `py_compile` OK.

#### 7.2.5 [ALTA] Cerrar sesion no finaliza el paro normal/de recuperacion (`self.paro_id`)

- **Donde:** `src/gui/inicio_view.py:272-302` (`_apagar_maquina`) y `:377`
  (paro formalizado en la recuperacion).
- **Problema:** `_apagar_maquina` finaliza solo el paro de Primera pieza; un
  paro normal en curso, o el de la sesion interrumpida recuperada (que SIEMPRE
  abre uno), queda "En curso" perpetuo sobre una sesion ya Finalizada.
- **Mitigacion:** `finalizar_paro(self.paro_id, ...)` en `_apagar_maquina`
  cuando exista.

- [x] Resuelto (fecha: 2026-08-24):
  - `_apagar_maquina(autorizador_id=None)`: antes de `cerrar_sesion`,
    finaliza el paro en curso (`finalizar_paro(paro_id, None, autorizador)`),
    SIN causa (nunca se autorizo; la columna lo permite, igual que
    `_cerrar_primera_pieza` cuando falta la causa) y con autorizador = quien
    autentico el cierre (`_cierre_autenticado` pasa su `id_operador`) o el
    dueno de la sesion por defecto. Envuelto en try/except para no frenar el
    cierre; limpia `self.paro_id`.
  - Verificado contra BD temporal ejecutando el metodo real: paro abierto +
    cierre -> paro con fin_paro/autorizador y sesion Finalizada; sin
    parametro -> atribuye al dueno. (Nota: durante la verificacion se detecto
    y corrijo una errata propia autorisador/autorizador en el llamador.)

---

### 7.3 Hallazgos nuevos — MEDIA

#### 7.3.1 Parser QR solo acepta `|`: la tolerancia documentada NO esta implementada

- **Donde:** `src/gui/huella_modal.py:280` (`re.split(r"[|]", texto)`) vs
  docstring :273-278 y AGENTS.md (prometen `[|\]}\\]`).
- **Impacto:** con escaner tipo teclado en layout US sobre Windows ES/LA, el
  `|` llega como `]` u otro simbolo vecino (Steren): TODO QR valido es
  rechazado como "Formato invalido". Bloquea el flujo completo de trabajos.
- **Mitigacion:** `re.split(r"[|\]}\\]", texto)` (una linea).

- [ ] Resuelto (fecha: ______)

#### 7.3.2 Re-escaneo de folio Abierto sobre-cumplido: meta instantanea + doble paro sin cortar piezas

- **Donde:** `src/gui/inicio_view.py:885-891` (baseline) y `:910-934`
  (`_verificar_meta_trabajo`).
- **Problema:** si un folio queda 'Abierto' con `cantidad_cortada >=
  cantidad_total` persistida (ventana entre checkpoint y tick de meta,
  seguido de "cerrar sesion interrumpida"), al re-escanarlo el baseline sale
  negativo, `_cortes_trabajo() >= meta` de inmediato y `_verificar_meta_
  trabajo` (no excluye `_primera_pieza`) marca 'Cerrado' y llama `_entrar_
  primera_pieza("meta alcanzada")` estando YA en el modo → replica 7.2.4.
- **Mitigacion:** acotar folio en `abrir_trabajo` (ver 7.3.8), guard de
  `_primera_pieza` en la verificacion de meta e idempotencia del modo.

- [ ] Resuelto (fecha: ______)

#### 7.3.3 Lock global del lector: ampliado a lector_presente/_reinit_sdk (amplia 6.1.7)

- **Donde:** `biometric_sdk.py:251-262` (`lector_presente`), `:518-530`
  (`_reinit_sdk`); `biometric_service.py:54-65`; `admin_view.py:445-455`.
- **Nuevo:** el poll del indicador (`main.py`, cada 3 s, hilo principal)
  consulta `dpfpdd_query_devices` MIENTRAS un hilo daemon captura (60 s) o,
  peor, ejecuta `_reinit_sdk` (`dpfpdd_exit/init`) tras un hot-plug fallido:
  ventana de crash nativo. `enrollar` sigue sin lock (capturas concurrentes
  sobre el mismo `h_reader`).
- **Mitigacion:** UN lock comun para captura/enumeracion/reinit/enroll.

- [ ] Resuelto (fecha: ______)

#### 7.3.4 Lectura rechazada por calidad dispara el ciclo hot-plug

- **Donde:** `biometric_sdk.py:617` (umbral "<50% del timeout") y `:700-707`.
- **Problema:** una captura rechazada por calidad retorna en <1 s, muy bajo
  el umbral: cada dedo mal puesto provoca `_cerrar_lector()` -> reabrir ->
  (peor caso) `_reinit_sdk`, mas log confuso de "reconectando lector".
- **Mitigacion:** no reconectar si `success==1` con quality>0 (fallo de
  calidad != handle stale).

- [ ] Resuelto (fecha: ______)

#### 7.3.5 Carrera del singleShot(600 ms) de recuperacion contra otro modal

- **Donde:** `inicio_view.py:387-389` vs `:391-414`.
- **Problema:** si el operador abre el modal de cierre dentro de los 600 ms,
  el singleShot de `_abrir_paro_autorizacion(recuperacion=True)` se ejecuta
  igual: dos HuellaModal apilados y el guard `_modal_abierto` perdido al
  cerrarse el de arriba.
- **Mitigacion:** verificar `_modal_abierto` en el callback del singleShot.

- [ ] Resuelto (fecha: ______)

#### 7.3.6 Falso positivo anti-rafaga al cerrar un modal largo

- **Donde:** `inicio_view.py:1036-1040`.
- **Problema:** con modal abierto la evaluacion retorna temprano SIN
  actualizar `_ultimo_excluidos`; al cerrarse (p. ej. modal QR abierto
  minutos con setup cortando) el delta completo entra como UNA muestra ->
  alarma + pregunta espuria (se rearma sola en ~7 s, pero suena en planta).
- **Mitigacion:** sincronizar `_ultimo_excluidos` al salir del bloqueo.

- [ ] Resuelto (fecha: ______)

#### 7.3.7 Cortes durante caida Modbus se descartan al reconectar (sin documentar)

- **Donde:** `modbus_controller.py:163` (`_conectar`: re-baseline).
- **Problema:** todo lo cortado con `conectado=False` se pierde (tradeoff
  defendible vs reset del modulo, mitigado por checkpoint de 30 s), pero NO
  consta en el contrato/docstring; el operador puede ver piezas no contadas.
- **Mitigacion:** documentarlo y/o registrar el episodio en log/sesion.

- [ ] Resuelto (fecha: ______)

#### 7.3.8 Flag de marcha/paro se fija ANTES de la escritura real (refuerza 7.2.1)

- **Donde:** `modbus_controller.py:401-412`.
- **Problema:** sin read-back ni reintento, el estado de la GUI y el fisico
  pueden quedar opuestos indefinidamente si la escritura fallo.
- **Mitigacion:** verificar retorno (7.2.1) y solo entonces fijar el flag.

- [ ] Resuelto (fecha: ______)

#### 7.3.9 Excepcion en checkpoint mata la cadena de respaldos sin aviso

- **Donde:** `inicio_view.py:603-617` (`_checkpoint_cortes`).
- **Problema:** el `QTimer.singleShot` de re-agenda va AL FINAL sin try/
  except: si `actualizar_cortes_sesion`/`actualizar_cantidad_cortada` lanza
  (p. ej. "database locked"), los checkpoints mueren el resto de la sesion
  sin log.
- **Mitigacion:** try/except alrededor + re-agendar en finally.

- [ ] Resuelto (fecha: ______)

#### 7.3.10 Folio QR enorme -> OverflowError no capturado

- **Donde:** `huella_modal.py:288-300` + `database.py:812-846`.
- **Problema:** el parser rechaza `folio<=0` pero no acota el maximo;
  `int("999...")` parsea y sqlite3 lanza `OverflowError` al bindear, FUERA
  del try de conversiones. Como el modal ya se cerro, el operador no ve
  feedback claro (solo traceback en log).
- **Mitigacion:** acotar folio/cantidad a un maximo razonable en parser y API.

- [ ] Resuelto (fecha: ______)

#### 7.3.11 config.json corrupto puede caer a simulacion silenciosa en planta

- **Donde:** `config.py:162-171,214-230,334`.
- **Problema:** JSON ilegible -> `{}` con warning; si ademas falta el `.env`
  heredado, `MODBUS_HOST` vacio -> modo simulacion. La app deja de controlar
  la maquina real (solo el banner de simulacion como aviso).
- **Mitigacion:** ante JSON corrupto en produccion, avisar fuerte / bloquear
  arranque hasta intervencion; respaldar el ultimo config valido.

- [ ] Resuelto (fecha: ______)

#### 7.3.12 Updates sin autenticidad (HTTP plano, manifest sin firmar)

- **Donde:** `update.py:75-85` (manifest), `:124-155` (descarga+sha256).
- **Problema:** el sha256 protege contra corrupcion pero viaja por el MISMO
  canal: un MITM en LAN sirve manifest+zip coherentes maliciosos. Los hashes
  por archivo del manifest (`hacer_manifest.py`) NADIE los valida despues.
- **Mitigacion:** firma del manifest (minimo hash fuera de banda) y/o HTTPS
  local; validar hashes por archivo post-instalacion en el updater.

- [ ] Resuelto (fecha: ______)

#### 7.3.13 Servidor de actualizaciones expuesto a toda la LAN

- **Donde:** `servidor_actualizaciones.py:43-51`.
- **Problema:** bind `0.0.0.0` sin auth/TLS/listing: cualquier host enumera y
  descarga builds completos incl. DLLs propietarios del SDK.
- **Mitigacion:** bind a IP concreta + firewall estricto; mantener el
  interruptor manual (ya existe).

- [ ] Resuelto (fecha: ______)

#### 7.3.14 Specs de build fuera del VCS: release irreproducible

- **Donde:** `.gitignore:43` (`*.spec`); `WTSControl.spec` y
  `tools/updater.spec` existen solo en disco.
- **Impacto:** clone limpio = build imposible; perdida del equipo = recetas
  perdidas (glob de DLLs, datas, excludes).
- **Mitigacion:** versionar los specs o moverlos a `tools/` con nombre fuera
  del patron ignorado.

- [ ] Resuelto (fecha: ______)

---

### 7.4 Hallazgos nuevos — BAJA

- [ ] **DLL presente pero corrupta revienta el constructor** (la tolerancia
  cubre ausencia, no export faltante): proteger asignaciones de restype y
  `dpfpdd_init` — `biometric_sdk.py:333-370,452-502`.
- [ ] **Clave `'quality'` devuelve `bpp`** — `biometric_sdk.py:698`.
- [ ] **`SimulacionController` sin `conectado()`** (los consumidores compensan
  con getattr; contradice el contrato HAL) — `simulacion_controller.py`.
- [ ] **Hilos efimeros por pulso Modbus sin tope** y `_desconectar()` fuera
  de lock en una rama — `modbus_controller.py:239-241,444,486`.
- [ ] **Migracion legacy `DROP TABLE operadores`** puede morir con FK ON o
  borrar operadores en silencio — `database.py:90-92`.
- [ ] **Conexiones sin try/finally** en rutas de error (mitigado por refcount
  de CPython); `init_db` con atomicidad parcial idempotente — `database.py`.
- [ ] **Updater:** `rmtree(ignore_errors=True)` puede mezclar residuos en
  `_pending`; zip sin `version.txt` se aplica igual; descarga directa al
  nombre final sin temp ni limite de tamano; ventana sin instalacion ante
  apagon entre renombres; `_backup` acumula ~60-200 MB por version —
  `updater.py:89-91,126-132,134-146,136-137`; `update.py:124-128`.
- [ ] **PID reuse aborta seguro con codigo 6** (direccion de fallo correcta;
  documentar el codigo) — `updater.py:196-206`.
- [ ] **Servidor sin `allow_reuse_address`**: WinError 10048 al reiniciarlo
  rapido — `servidor_actualizaciones.py:46`.
- [ ] **UPX activo en ambos builds**: falsos positivos de AV y arranques
  lentos en kiosco corporativo — `WTSControl.spec:37,51`; `updater.spec:32`.
- [ ] **Checkpoint sesion/trabajo en DOS transacciones independientes**:
  apagon entre ambas deja el trabajo desfaseado <30 s (subconteo acotado,
  nunca contaminacion) — `inicio_view.py:603-617`.
- [ ] **Folio Abierto re-vinculado aparece duplicado entre sesiones** en
  reportes (denormalizacion consciente; documentar) — `database.py:823-834`.
- [ ] **Captura de 60 s inabortable**: modal nuevo "mudo" mientras el hilo
  huerfano retiene el lock (amplia 6.1.8) — `huella_modal.py:338,447`.
- [ ] **Maquina detenida por falla durante ESPERA TRABAJO** no genera paro ni
  alarma (matiz de diseño del modo) — observacion operativa.

---

### 7.5 Prioridad sugerida (2026-08-24)

1. **6.1.1** quitar admin al Temporal / bootstrap (critica, abierta).
2. **7.2.1** verificar retorno de `write_single_coil` (fallo silencioso del
   rele de PARO; fix barato).
3. **7.2.2** guard en "Salir" (seguridad fisica de planta).
4. **7.2.3** filtrar `roles.activo=1` en permisos (revocacion rota).
5. **7.3.1** tolerancia de separadores QR (bloquea el flujo nuevo con
   escaner ES; una linea).
6. **7.2.4 + 7.2.5 + 7.3.2** idempotencia del modo, cerrar `paro_id` al
   salir, guard de meta en modo.
7. **7.3.3** lock global del lector.
8. **6.2.1 + 7.3.9** WAL/busy_timeout + try en checkpoints.
9. **7.3.12 + 7.3.14** autenticidad de updates + specs versionados.
10. Resto de medios/bajos y operacion (BitLocker, VLAN 502, respaldo BD).
