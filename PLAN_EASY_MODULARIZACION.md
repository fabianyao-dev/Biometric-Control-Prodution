# Plan — Easy v2 y modularización por módulos

> **Estado:** pendiente de ejecución
> **Creado:** 2026-10-29
> **Objetivo:** que la app controle las rutinas de Easy desde la base de datos y
> que el proyecto evolucione a un pequeño MES con módulos, sin reescribir de
> golpe las vistas actuales.
> **Regla del repo:** contenido, código y mensajes en español.

---

## 1. Dónde estamos parados

**Fase actual:** Fase 6 — División interna de `InicioView` (opcional, posterior).

| Fase | Contenido | Estado |
| --- | --- | --- |
| 0 | Dominio Easy, tablas y repositorio | **Hecho** |
| 1 | Servidor Easy v2 (`ejecutor.py` + `agente.py`) | **Hecho** |
| 2 | Cliente v2, servicio y editor de rutinas | **Hecho** |
| 3 | Componentes compartidos (`src/gui/componentes/`) | **Hecho** |
| 4 | Registro de módulos, selector y `InicioShell` | **Hecho** |
| 5 | Administración por módulo | **Hecho** (5a: show/hide por modulo) |
| 6 | División interna de `InicioView` (posterior) | Pendiente |

**Decisiones cerradas**

- `Easy/PruebaControlRemoto` **es** el código desplegado en la estación: se
  modifica y se redespliega desde este repo.
- El selector de módulos va en el **header global**, junto al título.
- Contrato de la app: `rutina(nombre_rutina, num_part)`. La app busca la rutina
  completa en la BD, la renderiza y envía los pasos al servidor.
- **Sin soporte legacy:** el servidor solo acepta pasos (v2); la app solo envía
  v2. Se eliminó `enviar_numero_parte`, el fallback y `EASY_PROTOCOLO`/
  `EASY_FALLBACK_LEGACY`.
- Entrega por fases, empezando por el protocolo v2.

---

## 2. Diagnóstico actual

**App → Easy (hoy)**

1. Al cargar un trabajo, `InicioView._trabajo_cargado`
   (`src/gui/inicio_view.py:2155`) llama a `_enviar_easy_num_part(...)`.
2. `_enviar_easy_num_part` (`inicio_view.py:2157`) lee `config.EASY_CONFIG`
   (`EASY_HOST`, `EASY_PUERTO`, `EASY_RUTINA`, `EASY_TIMEOUT`) y llama a
   `enviar_numero_parte()`.
3. `src/easy_agente.py:28` arma una línea JSON
   `{"rutina": "...", "texto": "<num_part>"}` y la envía por TCP en un hilo
   daemon. El callback corre en ese hilo; la UI se actualiza con
   `QTimer.singleShot(0, ...)`.
4. El servidor (`Easy/PruebaControlRemoto/Servidor/agente.py:220-265`) lee
   `rutina` y `texto`, carga `rutinas/<nombre>.py` con `importlib` y ejecuta
   `ejecutar(texto)`.
5. `acciones.py` ya tiene las primitivas (`click`, `doble_click`,
   `click_derecho`, `mover`, `texto`, `tecla`, `atajo`, `esperar`), validación
   0..1023 × 0..767, aborto con `Esc`, contador de pasos y backend falso.

**Problema:** el contrato es “nombre de rutina” y la rutina es un `.py` en la
estación. Cambiar coordenadas, orden o agregar variantes obliga a editar y
redesplegar código en la PC embebida. No hay datos, auditoría ni control desde
la app.

**Modularización (hoy)**

- `main.py` fija 3 entradas de sidebar y `mostrar_vista()` instancia
  `InicioView`, `SessionsView` y `AdminView` con `if/elif`
  (`main.py:588-613`).
- El título del header es literal `"Control de Corte"` (`main.py:205`).
- `AdminView` agrega 5 tabs fijas (`admin_view.py:447-451`).
- `huella_modal`, `checkbox`, `switch`, `resplandor`, `notificaciones` y
  `util` viven sueltos en `src/gui/`; `huella_modal` depende de
  `SelectorCausas`, que es específico de corte.
- `InicioView` tiene ~2,778 líneas; moverlo completo ahora es riesgoso.

---

## 3. Diseño

### 3.1 Contrato de la app

```python
# src/servicios/easy.py
def ejecutar_rutina(nombre, num_part, *, folio=None, sesion_id=None,
                    variables=None, callback=None) -> None:
    """Busca la rutina en BD, renderiza los pasos y los envía en un hilo."""
```

- `nombre` viene de `EASY_RUTINA` (hoy) o de `modulos.rutina_easy_id`
  (después).
- Si la rutina no existe o está inactiva, error controlado: **no** se ejecuta
  nada.
- Renderiza `{num_part}`, `{folio}`, `{sesion}` y variables extra.
- Registra el resultado en `easy_ejecuciones`.
- `callback(ok, error)` corre en el hilo secundario.

`InicioView` queda reducido a:

```python
self.easy.ejecutar_rutina(
    cfg["rutina"], res["num_part"],
    folio=res["folio"], sesion_id=self.sesion_id,
    callback=_on_resultado,
)
```

### 3.2 Protocolo Easy v2

Una línea JSON por conexión:

```json
{
  "version": 2,
  "rutina": "buscar_easy",
  "token": "opcional",
  "variables": {"num_part": "ABC-123", "folio": 1234},
  "pasos": [
    {"accion": "click",   "x": 312, "y": 208},
    {"accion": "texto",   "valor": "{num_part}"},
    {"accion": "tecla",   "valor": "enter"},
    {"accion": "esperar", "segundos": 1.5}
  ]
}
```

Respuestas:

```json
{"ok": true,  "rutina": "buscar_easy", "pasos": 4, "segundos": 6.2, "version": 2}
{"ok": false, "rutina": "buscar_easy", "error": "...", "paso": 3,
 "accion": "texto", "abortado": false}
```

**Reglas del ejecutor** (`Servidor/ejecutor.py`, archivo nuevo):

- Allowlist cerrada: `click`, `doble_click`, `click_derecho`, `mover`,
  `texto`, `tecla`, `atajo`, `esperar`.
- Se valida **toda la lista antes de ejecutar**: un paso inválido no mueve el
  ratón ni escribe.
- Coordenadas enteras 0..1023 × 0..767; `atajo` con teclas normalizables;
  `esperar` acotado.
- Sustitución `{variable}` solo contra `variables`, sin expresiones ni `eval`.
- Límites: 200 pasos, 600 s acumulados, texto máximo.
- Reutiliza `BLOQUEO`, `reiniciar_aborto`, `reiniciar_contador` y el aborto
  con `Esc`.
- `{"rutina", "texto"}` sigue funcionando para rollback y para el cliente de
  pruebas.

La estación **no** conoce la BD ni nombres de rutina: solo recibe una lista
validada. Eso mantiene el servidor sin estado y permite cambiar rutinas desde
la app sin tocar la estación.

### 3.3 Modelo de datos (aditivo en `init_db()`)

```text
modulos
  id, clave UNIQUE, nombre, icono, orden, activo, permiso,
  rutina_easy_id, predeterminado

rutinas_easy
  id, nombre UNIQUE, descripcion, activo, orden,
  timeout_s, creado, actualizado

rutinas_easy_pasos
  id, rutina_id FK, orden, accion, parametros TEXT (JSON), activo

easy_ejecuciones
  id, rutina_id, rutina_nombre, num_part, folio, sesion_id,
  inicio, fin, ok, pasos, error, origen
```

- `modulos` solo guarda metadatos: las vistas siguen siendo código. El
  registro de código siembra/actualiza la tabla; el header lee de ahí.
- Se siembran `corte` y `buscar_easy` copiada de `rutinas/buscar.py`, pero
  **inactiva**: ese `.py` hoy se niega a correr con
  `COORDENADAS_LISTAS = False`.
- `parametros` en JSON evita columnas nulas por tipo de acción; la validación
  fuerte vive en `src/domain/easy.py`.
- Las asignaciones por patrón de `num_part` quedan fuera de la primera
  entrega; se pueden agregar después sin cambiar el protocolo.

### 3.4 Capas nuevas

- `src/domain/easy.py` (puro): `PasoEasy`, `RutinaEasy`, allowlist,
  `validar_rutina()`, `renderizar_pasos()`, `construir_peticion()`.
- `src/repositorios/easy.py`: CRUD de rutinas/pasos y log, usando
  `obtener_conexion()`.
- `src/servicios/easy.py`: resolución por nombre, renderizado, envío y log.
  Recibe el transporte inyectado.
- `src/easy_agente.py`: se mantiene como transporte; se agrega
  `enviar_pasos()` y se conserva `enviar_numero_parte()`.

### 3.5 Módulos en la GUI

- `src/gui/modulos/base.py`: `ContextoApp` y `Modulo` (`clave`, `nombre`,
  `icono`, `orden`, `permiso`, `crear_vista`, `admin_tabs`).
- `src/gui/modulos/registro.py`: registro, orden y módulo predeterminado.
- `src/gui/modulos/corte/modulo.py`: **adaptador** que devuelve el
  `InicioView` actual sin moverlo todavía, más sus tabs de administración.
- `main.py`: arma el `ContextoApp`, llena el selector del header y delega
  Inicio a un `InicioShell` con `QStackedWidget` y creación perezosa.
- `InicioShell` protege el cambio de módulo: si hay máquina en marcha, paro
  abierto o modal activo, no cambia en silencio; pide confirmación o revierte
  el combo.
- `AdminShell`: tabs globales (Operadores, Roles, Sistema) + tabs del módulo
  activo (Corte: Causas, Zonas, Rutinas Easy). Al cambiar de módulo se
  reconstruyen solo las tabs del módulo.
- `SessionsView` queda global; se le puede agregar columna “Módulo” después.

### 3.6 Componentes compartidos

- Nuevo paquete `src/gui/componentes/`: `huella_modal`, `checkbox`, `switch`,
  `resplandor`, `notificaciones`, `util`.
- `selector_causas`, `modalidades_cierre` y `croquis_zonas` viven en
  `src/gui/modulos/corte/`.
- `huella_modal` no debe importar `SelectorCausas`: se invierte la dependencia
  (el módulo inyecta el selector o el flag `pedir_causa`).
- Se actualizan imports y `tests/test_arquitectura.py`: `componentes` no
  importa `modulos`; un módulo no importa el paquete de otro.

---

## 4. Fases

### Fase 0 — Contrato y datos

- `src/domain/easy.py` (puro): tipos, allowlist, validación y renderizado.
- `src/repositorios/easy.py`: CRUD de rutinas/pasos y log.
- `init_db()`: tablas nuevas + seed idempotente.

**Resultado:** la app puede leer y guardar rutinas completas con sus pasos
ordenados. `init_db()` se puede correr dos veces sin duplicar; la rutina
sembrada queda inactiva.

### Fase 1 — Servidor Easy v2

- `Servidor/ejecutor.py` con `validar_pasos()` y `ejecutar_pasos()`.
- `agente.py`: solo acepta pasos (v2); petición sin pasos → error.
- `Servidor/probar_pasos.py`: prueba con el backend falso de `acciones.py`.
- `Cliente/controlador.py --pasos archivo.json`.
- Actualizar `Easy/PruebaControlRemoto/AGENTS.md`.

**Resultado:** la estación ejecuta pasos en orden sin depender de archivos
`.py`. Un paso inválido en medio no ejecuta ninguno; `Esc` aborta; la respuesta
indica el paso que falló. Ya no se aceptan rutinas `.py`.

**Despliegue:** copiar `ejecutor.py` y `agente.py` a la estación, ejecutar
`probar_pasos.py`, reiniciar el agente. Recién después se toca la app.

### Fase 2 — Cliente v2 y editor

- `src/gui/modulos/corte/easy/agente.py`: `enviar_pasos()` reutilizando el transporte.
- Config: `EASY_TOKEN` (opcional). Sin `EASY_PROTOCOLO` ni
  `EASY_FALLBACK_LEGACY`.
- `src/gui/modulos/corte/easy/service.py`: resolución por nombre, renderizado, envío y log.
- `InicioView`: reemplazar `_enviar_easy_num_part` por el servicio.
- Admin → tab **Rutinas Easy**: lista, editor de pasos en tabla
  (`EditorPasosEasy`, sin JSON a mano), activar/desactivar, duplicar,
  validar y “ejecutar en estación” con confirmación.
- Admin → **Historial Easy**: últimas ejecuciones.

**Resultado:** la estación recibe pasos (v2). Un error de red o de paso se
muestra en `_estado` y queda en el log; no se ejecuta nada si la rutina está
inactiva.

### Fase 3 — Componentes compartidos

- Nuevo paquete `src/gui/componentes/` con los widgets genéricos.
- `selector_causas`, `modalidades_cierre` y `croquis_zonas` al módulo de
  corte.
- Desacoplar `huella_modal` de `SelectorCausas`.
- Actualizar imports y `tests/test_arquitectura.py`.

**Resultado:** los componentes genéricos se pueden usar en cualquier módulo y
`huella_modal` deja de arrastrar dependencias de corte.

### Fase 4 — Módulos e Inicio dinámico

- `src/gui/modulos/base.py`: `ContextoApp` y `Modulo`.
- `src/gui/modulos/registro.py` y `src/gui/modulos/corte/modulo.py`
  (adaptador del `InicioView` actual).
- `main.py`: `ContextoApp`, selector en el header, título = módulo activo,
  `InicioShell` con `QStackedWidget`.
- Guard de cambio: máquina en marcha, paro abierto o modal activo.
- Sincronizar `modulos` con el registro al arrancar.

**Resultado:** el selector cambia la vista de Inicio sin tocar la lógica de
corte; el cambio se bloquea cuando la máquina está en marcha.

### Fase 5 — Administración por módulo

- 5a (segura): `AdminView.set_modulo(clave)` muestra/oculta tabs;
  Causas/Zonas/Rutinas Easy solo con corte.
- 5b (limpia): extraer cada tab a su widget y que el módulo declare sus tabs;
  Operadores/Roles/Sistema quedan globales.
- Mover el estado compartido de captura (`_hilo_captura`, `_capturas`) a un
  servicio antes de separar Operadores.

**Resultado:** las tabs globales siempre están; las de corte aparecen solo con
corte y no se duplica el estado de captura.

### Fase 6 — División interna de `InicioView` (posterior)

- Separar panel de máquina, trabajo/QR, paro y estado en subwidgets, con la
  app ya modularizada.

---

## 5. Riesgos y criterios

- **Compatibilidad:** ya no hay protocolo legacy. El servidor y la app deben
  actualizarse juntos (servidor primero). Un cliente viejo contra el servidor
  nuevo falla con "faltan los pasos a ejecutar"; un cliente nuevo contra un
  servidor viejo ejecutaría la rutina por defecto con texto vacío (evitar).
- **Timeout:** `EASY_TIMEOUT=30` puede quedarse corto; la rutina en BD lleva
  `timeout_s`.
- **`num_part`:** se envía con puntos en lugar de espacios (compatibilidad con
  el comportamiento original). La variable `{num_part}` ya va compactada; se
  expone además `{num_part_crudo}` por si una rutina necesita el valor original.
- **Concurrencia:** el agente ejecuta una rutina a la vez (`BLOQUEO`); la app
  debe evitar encolar dos cargas o asumir la espera.
- **Ruff:** se corre sobre lo tocado; la deuda actual de
  `tests/test_inicio_view.py` se reporta, no se barre.
- **Despliegue:** la estación es 3.8/32 bits y se actualiza a mano; cada fase
  del servidor se valida con `probar_pasos.py` antes de cambiar la app.

---

## 6. Bitácora

| Fecha | Fase | Nota |
| --- | --- | --- |
| 2026-10-29 | — | Plan creado. Sin cambios de código todavía. |
| 2026-10-29 | 0 | `src/domain/easy.py`, `src/repositorios/easy.py`, tablas nuevas en `init_db()` y seed de `corte`/`buscar_easy`. Tests verdes. |
| 2026-10-29 | 1 | `Servidor/ejecutor.py`, dispatch v2 en `agente.py`, `probar_pasos.py`, `controlador.py --pasos`, AGENTS.md Easy actualizado. |
| 2026-10-29 | 2 (parcial) | `src/easy_agente.py` con `enviar_pasos`, `EASY_CONFIG` ampliado, `src/servicios/easy.py`, hook en `InicioView`. Tests verdes y ruff limpio. |
| 2026-10-29 | 2 | Editor en Administración: tabs "Rutinas Easy" (CRUD + validación) e "Historial Easy". Smoke OK. |
| 2026-10-29 | 3 | Movidos `util`, `checkbox`, `switch`, `resplandor`, `notificaciones`, `huella_modal` a `src/gui/componentes/` (shims eliminados). `huella_modal` desacoplado de `SelectorCausas` (inyección). Tests verdes y ruff limpio. |
| 2026-10-29 | 4 | `src/gui/modulos/` (base, registro, corte), `InicioShell`, selector en header, sync de `modulos`. App arranca y cierra limpio. |
| 2026-10-29 | — | Movidos `croquis_zonas`, `modalidades_cierre`, `selector_causas` e `inicio_view` a `src/gui/modulos/corte/`. Tests y smoke OK. |
| 2026-10-29 | — | Subcarpetas en `modulos/corte/`: `componentes/` (croquis, modalidades, selector) y `easy/` (agente, service, repo). Menos archivos sueltos. |
| 2026-10-29 | — | Eliminados todos los `__init__.py` de `modulos/`, `corte/`, `componentes/`, `easy/`. Auto-descubrimiento via `src/gui/modulos/loader.py` leyendo `MODULO_INFO`/`crear_vista` de `inicio_view.py`. Paquetes ahora son namespace packages. |
| 2026-10-29 | — | Fix: el loader solo registraba modulos sin `crear_vista`. Ahora registra siempre. `WTSControl.spec` agrega los modulos como `hiddenimports` + vista como data (PyInstaller no ve imports dinamicos). Test de regresion en `tests/test_modulos_loader.py`. |
| 2026-10-29 | — | Eliminados los `__init__.py` restantes (`src/`, `domain/`, `gui/`, `hardware/`, `reportes/`). Todo el proyecto usa namespace packages. Build de PyInstaller verificado: el exe descubre `['corte']` en runtime. |
| 2026-10-29 | — | Rutinas: quitado `modulo_clave` del esquema, repo y Admin (migracion `DROP COLUMN`). El textarea JSON se reemplazo por `EditorPasosEasy` (tabla + formulario por accion, reordenar y activar pasos). |
| 2026-10-29 | 5 | `AdminView.set_modulo()` muestra/oculta tabs por modulo; admin ajusta tabs al cambiar de modulo. |
| 2026-10-29 | — | Easy agrupado en `src/gui/modulos/corte/` (easy_agente, easy_service, easy_repo). Eliminados `src/servicios` y `src/repositorios` (vacios). |
| 2026-10-29 | — | Eliminado el soporte legacy: servidor solo pasos, app solo v2, sin fallback ni `EASY_PROTOCOLO`. |
