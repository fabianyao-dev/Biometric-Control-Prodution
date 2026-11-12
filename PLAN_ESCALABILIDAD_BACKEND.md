# Plan de escalabilidad — WTSControl (Backend separado + BD centralizada)

**Fecha:** Thu Nov 12 2026  
**Estado:** Plan (sin cambios de código aún)  
**Autor:** Agente OpenCode (Plan mode)  
**Referencia:** `WTSCOSystemDB.pgerd` (PostgreSQL 14)

---

## 1. Resumen de decisiones tomadas

| Decisión | Valor |
|----------|-------|
| Arquitectura | **Backend API separado** (no se mete en el IIS existente) |
| Base de datos | PostgreSQL 14 del servidor, nuevo esquema `wtscontrol` |
| Identificador de máquina | `MAQUINA_ID` fijo por máquina, configurado por el admin (config local o tabla de máquinas) |
| QR de trabajo | **Solo folio**; la app consulta `num_part` y `cantidad_total` al backend |
| Tabla de trabajos de la web | Se usa `production.ordenes_trabajo_local` existente; no se crea tabla propia en `wtscontrol` |
| Caché offline | Pendiente definir (SQLite local temporal si se cae la red de planta) |
| Lenguaje/docs | Español |

---

## 2. Análisis del ERD existente (`WTSCOSystemDB.pgerd`)

La BD del servidor está organizada en esquemas:

### Esquema `production` (catálogo y producción)
- `material_db` — `part_num` PK; catálogo maestro de partes (`description`, `clase`, `tipo`, `producto`, `updated_at`, `is_active`).
- `terminal_db` — `part_num` PK; terminales/cables por parte con FK `terminal_a-d` → `material_db.part_num`; incluye `maquina_asignada`, `equipo_a`, `updated_at`, `is_active`.
- `ordenes_trabajo_local` — `id` serial PK; `folio`, `fecha`, `no_parte`, `cantidad`, `status_impresion`, `fecha_impresion`. Es lo más cercano hoy al concepto de trabajo/QR.
- `espejo_jobhead` — `job_num` PK; espejo de jobs (`part_num`, `start_date`, `prod_qty`, `qty_completed`, `class_id`, `job_closed`).
- `espejo_partwhse`, `espejo_inventario_cables`, `espejo_forecast`, `espejo_partmtl`, `map_ensambles`, `pz_hra` — tablas de espejo/inventario/ensamble.

### Esquema `quality` (calidad)
- `arnes` — `numero_parte` PK; `descripcion`, `creado_en`.
- `configuracion` — `id` PK; `numero_parte` FK → `arnes`; `rois` (jsonb), `patron` (bytea), `activo`, `creado_en`.
- `inspeccion` — `id` PK; `configuracion_id` FK → `configuracion`; `fecha_hora`, `resultado`, `total_ok`, `total_fail`.

### Esquema `security` (usuarios y permisos)
- `users` — `id` PK; `nombre`, `apellido`, `username`, `password_hash`, `created_at`, `is_active`.
- `roles` — `id` PK; `name`, `description`, `is_active`.
- `user_roles` — (`user_id`, `role_id`) composite PK; FK a `users` y `roles`.
- `views` — `id` PK; `parent_id` (jerarquía), `name`, `display_name`, `route`, `icon`, `type`, `is_public`, `sort_order`, `is_active`.
- `role_views` — (`role_id`, `view_id`) composite PK; FK a `roles` y `views`.

### Esquema `public`
- `alembic_version` — control de migraciones.

### Observaciones clave para WTSControl
- No existen tablas de **sesiones de producción**, **huellas biometricas**, **paros**, **primera pieza** ni **contador de cortes del PLC**. Esas viven hoy en `planta_corte.db` (SQLite local) y deben crearse/migrarse en el esquema `wtscontrol`.
- `ordenes_trabajo_local` ya tiene `folio`, `no_parte`, `cantidad`: punto de partida natural para la consulta por folio desde el backend.
- `terminal_db.maquina_asignada` puede servir para asociar sesiones a una máquina física.

---

## 3. Arquitectura propuesta

```
+---------------------+      HTTP/JSON      +----------------------+
|  PC fanless (planta)| <-----------------> |  Backend API (separado)|
|  PySide6 + WTSControl|                    |  (puerto propio, no IIS)|
+---------------------+                    +----------------------+
         |                                          |
         |                                          | JDBC/ODBC
         |                                          v
         |                                 +------------------+
         |                                 |  PostgreSQL 14   |
         |                                 |  esquema wtscontrol|
         |                                 |  esquema production|
         |                                 |  esquema security  |
         |                                 +------------------+
         |
         v (caché offline opcional)
   +------------------+
   | SQLite local     |  (planta_corte.db, solo si se cae la red)
   | (planta_corte.db)|  se sincroniza al recuperar conexión
   +------------------+
```

**¿Por qué backend separado y no IIS?**
- No divides el desarrollo del backend/web existente.
- Puedes elegir el lenguaje/framework que mejor convenga (FastAPI/Node/Go/etc.) sin afectar el IIS.
- Las PC de planta solo consumen endpoints REST; no necesitan credenciales de BD directa.
- Es más fácil auditar quién, cuándo y desde qué máquina (`MAQUINA_ID`) hizo cada operación.

---

## 4. Diseño de base de datos — esquema `wtscontrol`

Se crea un **esquema nuevo `wtscontrol`** en el mismo PostgreSQL 14. No se modifican las tablas de `production`, `quality` ni `security` salvo las relaciones de solo lectura necesarias.

### 4.1 Tablas propias de WTSControl

#### `wtscontrol.maquinas`
Identifica cada PC fanless. Un registro por máquina instalada.

| Columna | Tipo | Nota |
|---------|------|------|
| id | serial PK | |
| maquina_id | varchar(50) unique | Ej. "SELTEC-01" (lo que se muestra en esquina superior izquierda) |
| nombre | varchar(100) | Nombre descriptivo |
| ubicacion | varchar(100) | Área/planta |
| plc_host | varchar(100) | IP del PLC (Zelio/Advantech) |
| modo_dev | boolean | true en desarrollo/sin lector |
| activo | boolean | default true |
| creado_en | timestamptz | |
| actualizado_en | timestamptz | |

#### `wtscontrol.usuarios` (propia de WTSControl)
Usuarios de la app de planta. Son **diferentes** a `security.users` (son dos aplicaciones distintas), por lo que se crea una tabla propia.

| Columna | Tipo | Nota |
|---------|------|------|
| id | serial PK | |
| username | varchar(50) unique | |
| nombre_completo | varchar(255) | |
| rol | varchar(50) | operador, admin, mantenimiento... |
| activo | boolean | default true |
| creado_en | timestamptz | |

#### `wtscontrol.huellas`
Huellas digitales por operador (un operador puede tener varias).

| Columna | Tipo | Nota |
|---------|------|------|
| id | serial PK | |
| usuario_id | int FK → usuarios.id | |
| plantilla | bytea | plantilla de huella (DigitalPersona) |
| dedo | varchar(20) | ej. "pulgar derecho" |
| activo | boolean | default true |
| creado_en | timestamptz | |

#### `wtscontrol.sesiones` (inicio de sesión de máquina)
Una sesión se inicia con **usuario + módulo + máquina** (no con folio). El folio se asocia después, al cargar el trabajo.

| Columna | Tipo | Nota |
|---------|------|------|
| id | serial PK | |
| maquina_id | varchar(50) FK → maquinas.maquina_id | máquina física (SELTEC-01, etc.) |
| usuario_id | int FK → usuarios.id | operador que inicia la sesión |
| modulo | varchar(50) | módulo de la app: corte, admin, etc. |
| fecha_inicio | timestamptz | |
| fecha_fin | timestamptz | nullable (abierta mientras esté activa) |
| estado | varchar(20) | Activa / Cerrada |
| folio | varchar(50) | folio del trabajo cargado (desnormalizado, opcional al iniciar) |
| creado_en | timestamptz | |
| actualizado_en | timestamptz | |

#### `wtscontrol.paros` (estado de máquina — paros reales, aparte de transacciones)
Registra los paros reales de la máquina (PARO manual / automático / MODO PARO / Mantenimiento / Primera pieza). Esta tabla va **aparte** de `transacciones`; no se mezcla con las transacciones de producción.

| Columna | Tipo | Nota |
|---------|------|------|
| id | serial PK | |
| sesion_id | int FK → sesiones.id | a qué sesión pertenece |
| folio | varchar(50) | desnormalizado para consultas rápidas por trabajo |
| maquina_id | varchar(50) | SELTEC-01, etc. |
| tipo_paro | varchar(20) | PARO manual / automático / MODO PARO / Mantenimiento / Primera pieza |
| inicio | timestamptz | |
| fin | timestamptz | |
| causa_zona | varchar(100) | causa o zona del paro |
| autorizado_por | int FK → usuarios.id | quien autorizó el paro (huella) |
| tolerancia_vencida | boolean | |
| creado_en | timestamptz | |

#### `wtscontrol.transacciones` (transacciones de producción — tipo MES)
Registra transacciones de producción (cortes, descartes, re trabajo, etc.). **Una sesión tiene muchas transacciones; una transacción pertenece a una sola sesión** (`sesion_id` es FK). Los paros van en su propia tabla `paros` aparte. No se envía una petición por cada corte detectado; se acumulan localmente y se envían al **finalizar el trabajo** (o ante corte de luz, guardando la última cantidad válida).

| Columna | Tipo | Nota |
|---------|------|------|
| id | serial PK | |
| sesion_id | int FK → sesiones.id | a qué sesión pertenece (1:N) |
| folio | varchar(50) | folio del trabajo (desnormalizado, se consulta de `production.ordenes_trabajo_local`) |
| maquina_id | varchar(50) | SELTEC-01, etc. |
| tipo_transaccion | varchar(50) | tipo de transacción de producción: corte, descarte, re_trabajo, etc. |
| cantidad | int | cantidad asociada (número de piezas/cortes) |
| estado | varchar(20) | OK / descarte / re trabajo |
| observacion | varchar(200) | motivo o detalle de la transacción |
| timestamp_transaccion | timestamptz | momento en que ocurrió la transacción |
| enviado | boolean | default false; indica si ya se sincronizó con el backend |
| creado_en | timestamptz | |

> **Origen de los datos de producción:** el contador físico de cortes vive en el PLC en **O1 (dir 20), 1 palabra de 16 bits**. El PC no cuenta flancos localmente; solo hace polling al PLC y detecta el cambio en O1 entre lecturas. El HAL resuelve el wrap a 65535. O2 es la palabra de pulsos, no la palabra alta; leer 2 palabras corrompe el valor. Las transacciones se acumulan localmente y se envían al finalizar el trabajo (o ante corte de luz, con la última cantidad guardada).

> **Nota:** `sesion_segmentos` y `auditoria` no se crean como tablas. La auditoría se resuelve con consultas con joins sobre las tablas existentes (`sesiones`, `transacciones`, `paros`, `usuarios`, `maquinas`).

### 4.2 Relaciones con esquemas existentes (solo lectura / FK suaves)

- `wtscontrol.sesiones.folio` → `production.ordenes_trabajo_local.folio` (relación lógica; se consulta para obtener `no_parte` y `cantidad` del trabajo. El folio se asocia al cargar el trabajo, no al iniciar sesión).
- `wtscontrol.transacciones.folio` → `production.ordenes_trabajo_local.folio` (desnormalizado para consultas rápidas por trabajo).
- `wtscontrol.transacciones.sesion_id` → `wtscontrol.sesiones.id` (una transacción de producción pertenece a una sesión; 1:N).
- `wtscontrol.paros.folio` → `production.ordenes_trabajo_local.folio` (desnormalizado; un paro pertenece a un trabajo).
- `wtscontrol.paros.sesion_id` → `wtscontrol.sesiones.id` (un paro pertenece a una sesión).
- `wtscontrol.sesiones.maquina_id` ↔ `production.terminal_db.maquina_asignada` (para saber en qué terminal/máquina se produce cada parte).
- `wtscontrol.usuarios` es tabla propia de WTSControl, no se vincula con `security.users` (dos apps distintas).

---

## 5. Identificador de máquina (`MAQUINA_ID`)

- Es **fijo por máquina**, no se elige en pantalla por el operador.
- Se guarda en `config.json` de cada PC (o en `wtscontrol.maquinas` al instalar).
- Se muestra en la **esquina superior izquierda** del shell/inicio (ej. "SELTEC-01").
- Se envía en cada petición al backend para auditar y filtrar por máquina.
- Si se necesita mover la app a otra PC, se cambia ese valor en el config de destino.

---

## 6. Flujo de sesión y trabajo

1. El operador inicia sesión con **usuario + módulo + máquina** (no con folio).
2. Luego escanea el QR (solo folio) para cargar el trabajo en la sesión activa.
3. La app llama al backend: `GET /trabajos/{folio}` para obtener `num_part`, `cantidad_total`, estado, etc. (consultando `production.ordenes_trabajo_local`).
4. Durante la corrida, la app lee el contador del PLC (O1) y acumula las transacciones de producción localmente (no se envía una petición por cada corte).
5. Los paros de máquina se registran aparte en `wtscontrol.paros` (no se mezclan con `transacciones`).
6. Al **finalizar el trabajo** (o ante corte de luz, guardando la última cantidad válida), la app envía las transacciones de producción acumuladas a `wtscontrol.transacciones`.

---

## 7. Fases de implementación (propuesta)

### Fase 1 — Diseño y esquema
- [ ] Crear esquema `wtscontrol` en PostgreSQL 14.
- [ ] Crear tablas: `maquinas`, `usuarios` (propia de WTSControl, no security.users), `huellas`, `sesiones`, `paros` (estado de máquina, aparte), `transacciones` (producción/cortes).
- [ ] Definir FKs y relaciones con `production` y `security`.
- [ ] Revisar y validar este `.md`.

### Fase 2 — Backend API
- [ ] Elegir framework y levantar servicio en puerto separado del IIS.
- [ ] Endpoints: autenticación, consulta de trabajo por folio, inicio/cierre de sesión, registro de transacciones de producción, registro de paros, consulta de máquinas.
- [ ] Middleware de auditoría con `MAQUINA_ID`.

### Fase 3 — App de planta (PySide6)
- [ ] Agregar `MAQUINA_ID` a `config.json` / `.env`.
- [ ] Mostrar identificador en esquina superior izquierda del shell.
- [ ] Cambiar lectura de QR: solo folio + petición al backend (se carga en sesión activa iniciada con usuario + módulo + máquina).
- [ ] Reemplazar escritura directa a SQLite local por llamadas al backend (con fallback opcional).
- [ ] Mantener `ContextoApp`, HAL y `BiometricService` sin depender del HAL real en pruebas.

### Fase 4 — Offline y sincronización (opcional)
- [ ] SQLite local como caché cuando falte red de planta.
- [ ] Cola de sincronización al recuperar conexión.
- [ ] Resolver conflictos de sesión si dos máquinas intentan tocar el mismo folio.

### Fase 5 — Empaquetado y release
- [ ] Actualizar `.spec` de PyInstaller sin regenerar a ciegas.
- [ ] `version.txt` + `tools/hacer_version.py` para bump y release.
- [ ] El updater sigue yendo primero.

---

## 8. Riesgos y consideraciones

| Riesgo | Mitigación |
|--------|------------|
| Caída de red local de planta | Evaluar SQLite local como caché temporal y sincronizar al volver |
| Credenciales expuestas | Las PC de planta no tienen credenciales de BD; solo consumen el API con token/API key por `MAQUINA_ID` |
| Caída del servicio API | Las máquinas no pueden operar; considerar modo offline limitado |
| Dos máquinas en el mismo folio | Validación en el backend: una sesión activa por folio + máquina |
| Migración de usuarios/huellas desde SQLite | Migración gradual; `security.users` ya existe en el servidor |

---

## 9. Próximos pasos inmediatos

1. Revisar este `.md` y confirmar el diseño de tablas del esquema `wtscontrol`.
2. Definir si se reusa `security.users` o se crea tabla propia de usuarios de planta.
3. Definir si se necesita caché SQLite offline (Fase 4) o si la red de planta es lo suficientemente estable.
4. Elegir tecnología del backend API (FastAPI, Node.js, Go, etc.).
5. Una vez aprobado, pasar a implementar Fase 1 (esquema de BD).

---

## 10. Reglas del proyecto a respetar (AGENTS.md)

- No editar `.env`, `planta_corte.db`, `logs/`, `dist/`, `build/`, `release/` ni `test/`.
- `tests/` es la suite automática; `test/` son scripts manuales de planta.
- Docs, comentarios y código en español.
- `ruff check tests\` es el gate de lint; lo que se agregue debe quedar limpio.
- No modificar `.spec` a ciegas; `version.txt` es fuente de la versión.
