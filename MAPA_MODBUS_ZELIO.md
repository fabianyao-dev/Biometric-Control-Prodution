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
| 18 | J3XT1 | PC -> PLC | libre (reset / heartbeat) |
| 19 | J4XT1 | PC -> PLC | libre |
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
- La torre (verde / ambar / roja) y la alarma las maneja el PLC: la app no
  las escribe.

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
