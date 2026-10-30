# AGENTS.md

## Proyecto

Demo de automatización de clics y teclado para una **estación Windows embebido de 32 bits con Python 3.8.10**. Una PC de la red envía un texto; el agente de la estación ejecuta una rutina y responde cuando termina. No es producción: sin cifrado ni autenticación por defecto.

- `Servidor/agente.py`: escuchador TCP; carga `rutinas/<nombre>.py`, llama a `ejecutar(texto)` y responde al terminar.
- `Servidor/acciones.py`: primitivas (`click`, `texto`, `tecla`, `atajo`, `esperar`), validación 1024x768 y aborto con `Esc`. pyautogui se importa de forma perezosa y admite un backend falso.
- `Servidor/mapeador.py`: grabador con pynput; escribe `mapeos/*.txt` con clics, texto, teclas, ventana activa y tiempos. **Ese .txt no se ejecuta**; las rutinas se escriben a mano.
- `Servidor/agente.py`: escuchador TCP; ejecuta pasos dinámicos y responde.
- `Servidor/ejecutor.py`: validación y ejecución de la allowlist de pasos.
- `Servidor/acciones.py`: primitivas (`click`, `texto`, `tecla`, `atajo`, `esperar`), validación 1024x768 y aborto con `Esc`.
- `Servidor/mapeador.py`: grabador con pynput; escribe `mapeos/*.txt` con clics para transcribir coordenadas a pasos. Solo en la estación; requiere pynput.
- `Servidor/probar_pasos.py`: prueba segura del ejecutor con backend falso.

## Ejecutar

```powershell
python Servidor\agente.py --forzar        # este PC de desarrollo (1920x1080)
python Servidor\probar_pasos.py           # prueba segura del ejecutor (sin raton)
python Servidor\mapeador.py --nombre buscar   # solo en la estación; requiere pynput
```

- En la estación real **no** usar `--forzar`: el agente exige 1024x768.
- Agente y mapeador necesitan una sesión de escritorio iniciada; pyautogui/pynput no funcionan headless, como servicio ni con RDP desconectado.
- Abrir el puerto 5000 en el firewall de Windows.
- Variables: `AGENTE_HOST`, `AGENTE_PUERTO`, `AGENTE_RUTINA`, `AGENTE_TOKEN`, `AGENTE_FORZAR`, `AGENTE_PERMITIR_PASOS`. Con `--token`, el JSON debe incluir el token.
- El entorno de Python 3.8.10 de 32 bits se instala en la estación según `requirements.txt`.

## Protocolo

Solo se acepta el protocolo v2 (pasos dinámicos). Una línea JSON por conexión:

```json
{"version": 2, "rutina": "buscar_easy",
 "variables": {"num_part": "Camara IP"},
 "pasos": [{"accion": "click", "x": 10, "y": 20}],
 "token": "opcional"}
```

Respuesta al terminar (no antes):

```json
{"ok": true, "rutina": "buscar_easy", "pasos": 5, "segundos": 6.2, "version": 2}
{"ok": false, "rutina": "buscar_easy", "error": "...", "paso": 3, "accion": "texto"}
```

- Una rutina a la vez (`Lock`), hilos por conexión y timeout de lectura de 60 s.
- El cliente espera hasta 300 s; ajustar `--timeout` si la rutina tarda más.
- `Esc` aborta; la respuesta trae `"abortado": true`.
- El agente sigue vivo tras JSON inválido o petición vacía.
- Ya no se cargan rutinas `.py` ni se acepta `{"rutina","texto"}`.

## Protocolo v2 (pasos dinamicos)

Ademas del protocolo legacy (`{"rutina","texto"}`), el agente acepta una lista
de pasos ya resueltos por el cliente:

```json
{"version": 2, "rutina": "buscar_easy", "variables": {"num_part": "ABC"},
 "pasos": [{"accion": "click", "x": 10, "y": 20},
           {"accion": "texto", "valor": "{num_part}"},
           {"accion": "tecla", "valor": "enter"}]}
```

Acciones permitidas: `click`, `doble_click`, `click_derecho`, `mover`,
`texto`, `tecla`, `atajo`, `esperar`. La lista se valida completa antes de
ejecutar; un paso invalido no mueve el raton. La respuesta incluye `paso` y
`accion` cuando falla. Desactivar con `--sin-pasos` o `AGENTE_PERMITIR_PASOS=0`.

## Pasos dinamicos

Las rutinas viven en la base de datos de la app (`rutinas_easy` + `rutinas_easy_pasos`)
y se envian como lista de pasos (JSON) al agente. El agente no carga archivos
`.py`: solo ejecuta la allowlist de `ejecutor.py`.

- Coordenadas absolutas 0..1023 x 0..767; se validan antes de cada clic.
- `texto()` escribe letra por letra (tecleo directo con pyautogui.write); normaliza espacios. Fiable solo con caracteres ASCII.
- “Éxito” significa que los pasos corrieron sin excepción, **no** que la app haya encontrado el resultado. No hay verificación visual.
- Para mapear: grabar con `mapeador.py`, leer `mapeos/*.txt` y copiar coordenadas y esperas a los pasos de la rutina en la app.

## Python 3.8.10 / 32 bits

- `requirements.txt` fija `Pillow==10.4.0` (última con wheel cp38-win32), `pyautogui==0.9.54`, `pynput==1.7.7`.
- Instalador completo de python.org, no el ZIP embebible (no trae pip ni tkinter). Si hace falta, `python -m pip install "pip<25"`.
- Sin sintaxis posterior a 3.8: nada de `match`, `removeprefix`, `functools.cache`, `list[int]` ni `X | Y`. UTF-8 explícito en archivos y logs.
- Verificar sintaxis con `ast.parse(..., feature_version=(3,8))`; el `venv` 3.14 no reproduce 3.8.

## Convenciones

- Texto visible, comentarios y logs en español.
- Sin git, tests ni CI en el repo; la prueba real es en la estación. `rutinas/prueba.py` valida red y protocolo sin efectos.
- No reintroducir `CMD:` ni ejecución de shell arbitrario.
- Sin cifrado: LAN confiable y token opcional; no presentarlo como producción.
