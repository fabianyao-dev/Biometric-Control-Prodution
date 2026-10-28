# Mapa Modbus del PLC Zelio (SR3 + SR3NET01BD)

Contrato entre el programa del PLC y la app de la PC. Lo que dice este
documento es lo que el codigo espera (`src/hardware/modbus_controller.py` y
el bloque Modbus de `.env`), contrastado con **mediciones reales** contra el
PLC en `192.158.1.80`.

## 1. Red: cable directo en dev y en planta

| | Dev (PC de desarrollo) | Planta (PC Fanless) |
|---|---|---|
| NIC del PLC (cable directo) | `192.158.1.241/24` | `192.158.1.241/24` |
| PLC (SR3NET01BD) | `192.158.1.80` | `192.158.1.80` |
| NIC de planta | `192.168.1.240/24` | la que da la planta |
| Puerto Modbus TCP | 502 | 502 |

**El PLC NO debe quedarse en `192.168.1.80`.** `192.168.1.0/24` es la red de
planta: si la NIC del PLC de la PC Fanless tomara una IP de ese mismo `/24`,
Windows tendria dos interfaces en la misma red y la ruta de la LAN se volveria
ambigua (el trafico a la LAN se va por el cable del PLC y la PC pierde la
red de planta). Es exactamente lo que se midio en la PC de desarrollo:
`Find-NetRoute 192.168.1.80` resolvia por la NIC de planta, no por la del PLC.

`192.158.1.0/24` es una subred privada que no existe en la planta: misma
configuracion en dev y en produccion, un solo `.env`, cero ambiguedad.

## 2. Cambio de IP del PLC (Zelio Soft 2)

1. PC conectada por cable al NET01BD. Si el modulo conserva la IP de
   fabrica (`85.16.124.124` segun la MAC `00:80:F4:85:7C:7C`), configurar
   esa IP en la tarjeta de red del PC antes de abrir Zelio Soft 2.
2. `Edit > Program configuration > Ethernet extension`:
   - IP address: **Static** (desmarcar BOOTP / Dynamic)
   - Address: `192.158.1.80`
   - Subnet mask: `255.255.255.0`
   - Gateway: vacio
3. `Transfer > Transfer from PC to PLC` (con el PLC en RUN).
4. Comprobar: `ping 192.158.1.80` y puerto 502 abierto.

## 3. Mapa de palabras del SR3NET01BD (MEDIDO)

El NET01BD **no expone coils**. Medido con un sondeo palabra a palabra:

| Funcion | Resultado medido |
|---|---|
| FC03 (holding) dir **16-23** | responde -> J1..J4 (16-19) + O1..O4 (20-23) |
| FC03 fuera de 16-23 | excepcion (el mapa es solo ese) |
| FC04 (input registers) | no soportado |
| **Coils (FC01/FC05)** | **no soportado** -> por eso el modo "registro" (FC06) |

| Direccion | Palabra | Sentido | Uso en esta app |
|---|---|---|---|
| 16 | J1XT1 | PC -> PLC | bit 0 = **START** (pulso de 300 ms) |
| 17 | J2XT1 | PC -> PLC | bit 0 = **PARO** (latch sostenido) |
| 18 | J3XT1 | PC -> PLC | **torre**: bit0=verde, bit1=ambar, bit2=roja, bit3=alarma |
| 19 | J4XT1 | PC -> PLC | bit0 = **heartbeat** (la PC lo conmuta cada 2 s) |
| 20 | O1XT1 | PLC -> PC | **contador de cortes (16 bits)** |
| 21 | O2XT1 | PLC -> PC | **pulsos** (destella en cada corte) |
| 22 | O3XT1 | PLC -> PC | libre |
| 23 | O4XT1 | PLC -> PC | libre |

START y PARO pueden compartir una misma palabra J con bits distintos
(`MODBUS_START_REGISTER` / `MODBUS_START_BIT` / `MODBUS_PAUSE_REGISTER` /
`MODBUS_PAUSE_BIT`); por defecto van en J1 y J2.

### Nota: O2 es la palabra de PULSOS, NO la palabra alta del contador

Diseno del PLC: **O1 = contador** y **O2 = pulsos**. O2 se enciende a 1
durante un instante en cada corte y se apaga solo (medido: el destello es
mas corto que el periodo de sondeo de 500 ms de la PC).

Consecuencia: **O1 y O2 NO son un entero de 32 bits partido en dos**. Si se
leen las 2 palabras como un entero de 32 bits, en el instante del pulso el
valor sale como `N + 65536`:

```
O1=13 O2=1 -> 65549   (el valor real es 13)
O1=13 O2=0 -> 13
```

El HAL descartaba ese salto por anomalo y **se perdia 1 corte por cada
pulso** (medido: 15 cortes reales -> 11 contados).

**Por eso `MODBUS_COUNTER_WORDS=1`**: la app lee SOLO O1, que si es
fiable (siempre avanza de 1 en 1). El HAL solo necesita *deltas*, y el
wraparound a 65535 ya lo resuelve (`_max_valor`). Con 1 palabra el conteo
medido fue **15 reales = 15 contados**.

Nota: la app **no puede contar por pulsos**, porque duran ~200 ms y el sondeo
es de 500 ms: se perderia la mayoria. El conteo va por el delta de O1, que
es exacto. O2 queda como palabra libre para el PLC (o para un heartbeat, si
lo quieres usar).

### Medicion de referencia (boton de prueba del PLC)

Captura en alta velocidad (periodo medio 52 ms) con el boton de prueba del
PLC pulsado 17 veces:

| | |
|---|---|
| Incrementos de O1 | 17 |
| Destellos de O2 | 17 (uno por cada incremento) |
| Conteo de la app | **17** |
| Duracion del pulso en O2 | ~150-200 ms |
| Periodo de sondeo de la app | 500 ms (`MODBUS_POLL_MS`) |

El pulso en O2 dura ~200 ms y el sondeo de la app es de 500 ms: **contar por
pulsos perderia aproximadamente el 60% de los cortes**. Por eso la app
cuenta por el delta de O1, que no pierde nada.

### Casos limite del contador de 16 bits

- **Wraparound**: al pasar de 65535 a 0, el delta es 1 (el HAL lo resuelve con
  `_max_valor`). Con la maquina real a ~2 cortes/s, el wrap llega cada ~9 h.
- **Reset del PLC** (reinicio, pierde la cuenta): el contador vuelve a 0 y el
  HAL lo interpreta como wraparound -> cuenta 1 corte de mas. Es un error de
  1 pieza por reinicio del PLC; no afecta al conteo normal.

## 4. Lo que debe hacer el programa del PLC

- **El contador de cortes lo cuenta el PLC**, no la PC: la PC solo hace
  polling por red (Windows no es un SO en tiempo real y perderia conteos).
- El programa debe estar en **FBD**: en LADDER las palabras J y O no son
  accesibles desde el programa.
- Traduccion en el PLC (verificada en campo):
  - `J1 bit0` -> salida "boton verde" (marcha). La PC lo pulsa 300 ms y lo
    devuelve a 0: en el PLC hay que detectar el flanco/impulso, no dejarlo
    como nivel (seria un "marcha" permanente).
  - `J2 bit0` -> salida "boton rojo" (pausa). Aqui si es un **nivel
    sostenido** (latch): la PC lo mantiene en 1 hasta que se reanuda.
  - El contador de la entrada fisica -> **O1** (16 bits).
- La torre (verde / ambar / roja) y la alarma las maneja el **PLC a partir de
  los bits de J3**; la app solo escribe esos bits (ver seccion 4.1).

### 4.1 Torre de luces y heartbeat (requisitos del FBD)

La PC **no puede escribir** las salidas O, asi que la torre viaja por J3 y el
programa del PLC la copia a las salidas fisicas:

| Bit de J3 (dir 18) | Salida del PLC | Significado |
|---|---|---|
| bit0 | Q3 | verde: maquina en marcha |
| bit1 | Q4 | ambar: detenida (cualquier causa) |
| bit2 | Q5 | roja: detenida mas alla del tiempo de tolerancia |
| bit3 | Q6 | alarma: parpadeo de 3 s al ENTRAR en rojo |

Requisitos del programa (FBD):

1. Copiar **cada bit de J3 a su salida** de la torre (`J3.0 -> Q3`,
   `J3.1 -> Q4`, `J3.2 -> Q5`, `J3.3 -> Q6`). No hace falta logica: la
   decision del color es de la app.
2. Copiar **J2.0 a Q2** (paro). La app escribe la logica **invertida**
   (`MODBUS_PAUSE_COIL_INVERTIDO=1`): `J2.0 = 1` = maquina habilitada
   (Q2 cerrado), `J2.0 = 0` = PARO (Q2 abierto, fail-safe). Si el cableado
   del tablero es al reves, invertir la bobina y avisar para cambiar el .env.
3. **Watchdog del heartbeat**: si `J4.0` (dir 19) no cambia durante ~10 s,
   apagar Q2..Q6. Asi la maquina no queda habilitada (ni la torre encendida)
   con la PC caida. La PC conmuta el bit cada 2 s (`TORRE_HEARTBEAT_MS`).
4. Al cerrar la app se escriben **cero** a J3 y a J4 (torre apagada) antes de
   soltar el enlace. J2 se latchea al PARO (cierre seguro).

#### Estado medido en el PLC real (24/10/2026)

| Ruta | Resultado |
|---|---|
| PC escribe J1/J2/J3/J4 y FC03 las devuelve | **OK** (el PLC guarda los valores) |
| `J4.0` heartbeat conmutando cada 2.2 s | **OK** (medido) |
| `J1.0` -> Q1 (marcha) | **OK**: el relevador Q1 pulsa con la app |
| `J2.0` -> Q2 (paro) | **NO MAPEADO**: J2=0 durante 6 s y Q2 no se movio |
| `J3.0..3` -> Q3..Q6 | **NO MAPEADO**: se probaron 1, 2, 4 y 8; ningun relevador |

O sea: **hoy el FBD solo traduce J1**. Mientras no se agreguen las rutas 2 y
1 de esta lista, el PARO de la app es solo logico (no detiene la maquina) y
la torre no enciende.


Comportamiento de la app (`src/gui/inicio_view.py`, `_estado_torre`):

| Situacion | Verde | Ambar | Roja |
|---|---|---|---|
| Sin sesion | 0 | 0 | 0 |
| Maquina en marcha (produciendo) | 1 | 0 | 0 |
| Primera pieza / Mantenimiento / PARO con maquina encendida por zona | 0 | 1 | 0 |
| Esperando trabajo (maquina apagada, sin paro abierto) | 0 | 1 | 0 |
| Paro real menos de `PRIMERA_PIEZA_TIMEOUT_S` | 0 | 1 | 0 |
| Paro real mas de `PRIMERA_PIEZA_TIMEOUT_S` | 0 | 0 | 1 |

"Paro real" = un PARO abierto (manual o automatico) o el modo PARO, mas el
modo Mantenimiento con la maquina detenida. La tolerancia es la MISMA para
todos (`PRIMERA_PIEZA_TIMEOUT_S`, configurable en `.env`/`config.json`), no
solo para Primera pieza, y el ancla se toma al detenerse la maquina
(autorizar el paro NO reinicia el conteo). La espera de trabajo no se pone
roja: no hay paro que resolver. **No confundir** con `PARO_IDLE_TIMEOUT_S`
(60 s, el auto-paro por inactividad con la maquina en marcha sin cortes):
son dos tiempos distintos.

La alarma (`J1` bit5 -> Q6) solo se dispara en la **transicion a rojo** y
parpadea 500 ms encendida / 500 ms apagada durante 3 s (`TORRE_ALARMA_*`). La
roja (`J1` bit4 -> Q5) **permanece** hasta que se sale del paro.

Claves de configuracion (`MODBUS_CONFIG`, con sus variables de entorno):

| Clave | Env | Por defecto |
|---|---|---|
| `tower_register` | `MODBUS_TOWER_REGISTER` | 18 |
| `tower_heartbeat_register` | `MODBUS_TOWER_HEARTBEAT_REGISTER` | 19 |
| `tower_green_bit` / `amber` / `red` / `alarm` | `MODBUS_TOWER_*_BIT` | 0 / 1 / 2 / 3 |
| `tower_heartbeat_bit` | `MODBUS_TOWER_HEARTBEAT_BIT` | 0 |
| `tower_alarm_pulso_on_ms` / `off_ms` | `TORRE_ALARMA_PULSO_*_MS` | 500 / 500 |
| `tower_alarm_duracion_s` | `TORRE_ALARMA_DURACION_S` | 3 |
| `tower_heartbeat_ms` | `TORRE_HEARTBEAT_MS` | 2000 |
| Tolerancia ambar -> rojo de la torre | `PRIMERA_PIEZA_TIMEOUT_S` | 900 |
| Auto-paro por inactividad (NO es la tolerancia de la torre) | `PARO_IDLE_TIMEOUT_S` | 60 (fijo en codigo) |

Para probar sin PLC: `venv\Scripts\python test\simulador_modbus.py --modo
registro` imprime cada escritura de J3 con los nombres (`VERDE`, `AMBAR`,
`ROJA`, `ALARMA`) y cada conmutacion de J4.

## 5. Verificacion desde la PC

```bash
# 1) Red (PowerShell como administrador)
test\\red_plc_directo.ps1 -Accion Test

# 2) Diagnostico del NET01BD (solo lectura por defecto)
venv\\Scripts\\python test\\test_modbus_zelio.py --ip 192.158.1.80 --seguir 20

# 3) Consola EN VIVO (lo que ve la app, en tiempo real)
venv\\Scripts\\python test\\monitoreo_zelio.py --hal
venv\\Scripts\\python test\\monitoreo_zelio.py --hal --marcha
venv\\Scripts\\python test\\monitoreo_zelio.py --hal --paro

# 4) La app contra el PLC
#    (el .env ya apunta a MODBUS_HOST=192.158.1.80 y MODBUS_CMD_MODE=registro)
venv\\Scripts\\python main.py
```

## 6. Red de la PC (script)

`test\\red_plc_directo.ps1` (PowerShell **como administrador**):

| Accion | Que hace |
|---|---|
| `-Accion Test` | Muestra IP, ruta hacia el PLC, ping, puerto 502 y ARP |
| `-Accion Apply` | Deja la NIC del PLC en `192.158.1.241/24`, sin gateway ni DNS |
| `-Accion Apply -Alias` | Si el PLC todavia esta en `192.168.1.80`: alias `/32` + ruta host persistente, sin duplicar `192.168.1.0/24` |
| `-Accion Undo` | Quita lo anterior y restaura la config previa (respaldo automatico en `test/red_plc_backup.json`) |

La NIC del PLC se detecta sola (la que esta Up y no es la de la ruta por
defecto); con varias candidatas hay que indicar `-Adaptador "Ethernet 2"`.

## 7. Resumen de lo medido en el PLC real

| Prueba | Resultado |
|---|---|
| Socket Modbus TCP `192.158.1.80:502` | OK |
| Mapa J1..J4 / O1..O4 (dirs 16-23) | OK, el resto da excepcion |
| Coils / FC04 | no soportados |
| FC06 escritura (J3 = 1 y volver a 0) | OK, la palabra retiene el valor |
| Latch de PARO al conectar (J2 = 1) | OK |
| MARCHA: suelta PARO (J2 = 0) + pulso START (J1 = 1 -> 0) | OK, la maquina arranca |
| Contador O1 avanzando con la maquina cortando | OK, +1 por corte |
| O2 = palabra de PULSOS (destella en cada corte) | CONFIRMADO (no es la palabra alta) |
| Conteo del HAL con `MODBUS_COUNTER_WORDS=1` | **15 reales = 15 contados** |
| Captura con el boton de prueba (17 pulsaciones) | **17 incrementos = 17 pulsos = 17 contados** |
