"""
export_auto.py - Exportacion automatica del reporte del dia a Excel.

Envuelve `exportar_dia()` para que la app genere los reportes sola, sin que
nadie tenga que entrar a Sesiones. Tres cosas distintas:

    hora     Snapshot PARCIAL del dia en curso, una vez por hora. Es el
             archivo "en vivo" que un supervisor abre para ver como va el
             turno (tendra filas 'En curso').
    hoy      Cierre FINAL del dia EN CURSO. Como el horario de fin de turno
             varia, NO se espera a la medianoche: lo pide el usuario al
             cerrar la sesion (o al cerrar la app) y se genera al instante,
             con la PC todavia encendida.
    dia      Cierre FINAL de un dia ya terminado (ayer o mas atras). El tick
             lo exporta solo cuando ese dia YA no tiene sesiones abiertas, y
             es lo que recupera el `catchup` tras un apagon (ventana acotada
             a `DIAS_CATCHUP_MAX`).

Decisiones de diseno:

    - Este modulo NO toca Qt ni crea hilos: `pendientes()` decide (puro, con
      los providers inyectables) y `ejecutar()`/`confirmar()` hacen el I/O.
      El QTimer, el hilo de trabajo y los eventos de la GUI los pone
      `main.py`, que es quien sigue el patron "hilo -> queue.Queue ->
      QTimer" del proyecto.
    - El dia EN CURSO no se "sella" al cerrarlo: `ultimo_dia` solo avanza
      con dias ya terminados. Si el cierre de anoche fallo o hubo un receso,
      el tick del dia siguiente lo reexporta con los datos finales.
    - La escritura es atomica (temp + `os.replace`) para no dejar un .xlsx a
      medias si se va la luz, y si el destino esta ABIERTO en Excel (bloqueo)
      guarda una copia con marca de hora al lado en vez de perder el reporte.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

# Tope de dias hacia atras que `catchup` reexporta de una sola pasada (evita
# inundar de archivos si la app estuvo semanas apagada).
DIAS_CATCHUP_MAX = 14

# Estado de una sesion ABIERTA (ver `sesiones_produccion.estado` en database).
ESTADO_SESION_ACTIVA = "Activa"


@dataclass(frozen=True)
class TrabajoExport:
    """Un archivo a generar. `tipo` es informativo (logs); `parcial` decide el
    nombre del archivo y su sufijo (snapshot en vivo vs. cierre del dia)."""

    tipo: str          # 'hora' | 'hoy' | 'dia' | 'catchup'
    fecha: str         # 'YYYY-MM-DD'
    parcial: bool      # True = snapshot en vivo; decide nombre y carpeta


@dataclass
class EstadoExport:
    """Lo ya hecho, para no repetirlo. Se conserva entre ticks."""

    ultima_hora: str = ""   # 'YYYY-MM-DD HH' del ultimo snapshot por hora
    ultimo_dia: str = ""    # 'YYYY-MM-DD' del ultimo cierre de dia confirmado


def ruta_export(dir_auto: str, fecha: str, parcial: bool) -> str:
    """Ruta del archivo de `fecha`: cada dia en SU PROPIA carpeta.

    Todo lo de un dia vive en `<dir_auto>/<fecha>/`: el snapshot parcial
    (una vez por hora, para monitoreo en vivo) y el cierre final. El sufijo
    `_parcial` deja claro que ese archivo todavia no es el cierre del dia.
    """
    carpeta = os.path.join(dir_auto, fecha)
    if parcial:
        return os.path.join(carpeta, f"Sesiones_{fecha}_parcial.xlsx")
    return os.path.join(carpeta, f"Sesiones_{fecha}.xlsx")


def _ruta_con_marca(ruta: str, ahora: datetime) -> str:
    """Copia alternativa cuando el destino esta bloqueado por Excel."""
    base, ext = os.path.splitext(ruta)
    return f"{base}_{ahora.strftime('%H%M')}{ext or '.xlsx'}"


def decidir(ahora: datetime, estado: EstadoExport, *, cada_hora: bool,
            hoy: str, hoy_tiene_sesiones: bool, limite: str,
            dias_pendientes):
    """Decision PURA del TICK: que exportar ahora mismo por el reloj.

    `dias_pendientes` es una lista ascendente de `(fecha, tiene_sesiones,
    cerrado)` con los dias candidatos a cierre (desde el dia siguiente al
    ultimo exportado hasta el dia limite), ya resueltos por el llamador.
    `hoy_tiene_sesiones` es el del dia en curso (para el snapshot por hora).
    Aqui no se toca la BD ni el disco, para poder probarlo con datos fijos.

    Devuelve la lista de trabajos. El estado NO se aplica aqui: lo avanza
    `ProgramadorExport.confirmar` SOLO cuando el export termino bien.

    El cierre del dia EN CURSO no entra aqui: lo decide `decidir_hoy`, que
    solo se invoca cuando el usuario cierra sesion o cierra la app.
    """
    trabajos = []

    # Horario primero: es el que un supervisor esta mirando en vivo.
    clave_hora = ahora.strftime("%Y-%m-%d %H")
    if cada_hora and clave_hora != estado.ultima_hora and hoy_tiene_sesiones:
        trabajos.append(TrabajoExport("hora", hoy, True))

    # Cierre final de los dias ya terminados (incluye el catch-up).
    for fecha, tiene_sesiones, cerrado in dias_pendientes:
        if not tiene_sesiones or not cerrado:
            # Sin datos no hay archivo; un dia con sesion abierta se reintenta
            # en el siguiente tick (no se marca como hecho).
            continue
        tipo = "dia" if fecha == limite else "catchup"
        trabajos.append(TrabajoExport(tipo, fecha, False))

    return trabajos


def decidir_hoy(fecha: str, tiene_sesiones: bool, cerrado: bool):
    """Decision PURA: cerrar el dia EN CURSO o no.

    Solo se cierra `fecha` si ya tiene sesiones y NO le queda ninguna abierta
    (asi no se congela un dia a medias ni se exporta el receso de mediodia
    como si fuera el final). Devuelve `None` en cualquier otro caso.
    """
    if tiene_sesiones and cerrado:
        return TrabajoExport("hoy", fecha, False)
    return None


def _confirmar_estado(estado: EstadoExport, trabajo: TrabajoExport,
                      ahora: datetime) -> EstadoExport:
    """Aplica un trabajo exitoso al estado (funcion pura).

    `hoy` NO sella el dia: `ultimo_dia` solo avanza con dias ya terminados.
    """
    if trabajo.tipo == "hora":
        return EstadoExport(ahora.strftime("%Y-%m-%d %H"), estado.ultimo_dia)
    if trabajo.tipo == "hoy":
        return estado
    nuevo_dia = max(estado.ultimo_dia, trabajo.fecha)
    return EstadoExport(estado.ultima_hora, nuevo_dia)


class ProgramadorExport:
    """Planifica y ejecuta los exports automaticos.

    Los providers (`reloj`, `tiene_sesiones`, `esta_cerrado`, `exportar`,
    `leer_estado`, `persistir`) se inyectan para poder probar el programador
    sin reloj real, sin BD y sin escribir archivos. `desde_config()` arma el
    programador de produccion con los valores reales.
    """

    def __init__(self, *, dir_auto: str,
                 cada_hora: bool = True, activo: bool = True,
                 reloj=None, tiene_sesiones=None, esta_cerrado=None,
                 exportar=None, leer_estado=None, persistir=None):
        self.dir_auto = dir_auto
        self.cada_hora = bool(cada_hora)
        self.activo = bool(activo)
        self._reloj = reloj or _reloj_local
        self._tiene_sesiones = tiene_sesiones or _tiene_sesiones_db
        self._esta_cerrado = esta_cerrado or _dia_cerrado_db
        self._exportar = exportar
        self._persistir = persistir or _persistir_ultimo_dia
        ultimo_dia = (leer_estado or _leer_ultimo_dia)() or ""
        self.estado = EstadoExport(ultimo_dia=ultimo_dia)

    @classmethod
    def desde_config(cls):
        """Programador de produccion: lee la config y usa la BD/export real."""
        from .. import config

        cfg = config.EXPORT_AUTO_CONFIG
        return cls(
            dir_auto=cfg["dir"] or os.path.join(config.DIR_DATOS, "exportaciones"),
            cada_hora=cfg["cada_hora"],
            activo=cfg["activo"],
        )

    # ------------------------------------------------------------------
    # Planificacion
    # ------------------------------------------------------------------

    def ahora(self) -> datetime:
        """Reloj del programador (inyectable en tests)."""
        return self._reloj()

    def pendientes(self, ahora: datetime | None = None, *,
                   incluir_hoy: bool = False):
        """Trabajos a ejecutar AHORA (lista vacia si no hay nada o esta off).

        Por defecto (el tick) solo salen el snapshot por hora y el cierre de
        los dias ya terminados. El cierre del dia EN CURSO no se pregunta
        aqui: quien cierra sesion o cierra la app lo pide con
        `incluir_hoy=True`, para generar el archivo en el momento, con la PC
        todavia encendida.
        """
        if not self.activo:
            return []
        ahora = ahora or self._reloj()
        hoy_d = ahora.date()
        # Ayer ya es un dia terminado: no recibe sesiones nuevas (las de
        # madrugada caen en el dia siguiente), asi que en cuanto deja de
        # tener sesiones abiertas se puede cerrar. No hace falta esperar a
        # ninguna hora del reloj, porque el horario de fin de turno varia.
        limite_d = hoy_d - timedelta(days=1)
        fecha_hoy = hoy_d.isoformat()
        fecha_limite = limite_d.isoformat()

        dias = []
        d = _inicio_ventana(self.estado.ultimo_dia, limite_d)
        while d <= limite_d:
            f = d.isoformat()
            tiene = self._tiene_sesiones(f)
            dias.append((f, tiene, self._esta_cerrado(f) if tiene else True))
            d += timedelta(days=1)

        clave_hora = ahora.strftime("%Y-%m-%d %H")
        necesita_hora = self.cada_hora and clave_hora != self.estado.ultima_hora
        hoy_tiene = (
            self._tiene_sesiones(fecha_hoy)
            if necesita_hora or incluir_hoy else False
        )

        trabajos = decidir(
            ahora, self.estado,
            cada_hora=self.cada_hora,
            hoy=fecha_hoy, hoy_tiene_sesiones=hoy_tiene,
            limite=fecha_limite, dias_pendientes=dias,
        )

        if incluir_hoy:
            cierre = decidir_hoy(
                fecha_hoy, hoy_tiene,
                self._esta_cerrado(fecha_hoy) if hoy_tiene else False,
            )
            if cierre:
                trabajos.insert(0, cierre)
        return trabajos

    # ------------------------------------------------------------------
    # Ejecucion
    # ------------------------------------------------------------------

    def ejecutar(self, trabajo: TrabajoExport, ahora: datetime | None = None):
        """Genera el archivo. Devuelve (ok, mensaje). No toca el estado."""
        ahora = ahora or self._reloj()
        ruta = ruta_export(self.dir_auto, trabajo.fecha, trabajo.parcial)
        try:
            os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
        except OSError as e:
            return False, f"No se pudo crear la carpeta {ruta!r}: {e}"

        # `exportar_dia` escribe a un temporal y luego se reemplaza: el archivo
        # final nunca queda a medias.
        tmp = ruta + ".tmp.xlsx"
        exportar = self._exportar or _exportar_dia
        ok, msg, _stats = exportar(trabajo.fecha, tmp)
        if not ok:
            _borrar_silencioso(tmp)
            return False, msg

        try:
            os.replace(tmp, ruta)
        except PermissionError:
            # El destino esta abierto (Excel lo bloquea): se guarda al lado
            # con la hora, para no perder el reporte ni romper el flujo.
            alt = _ruta_con_marca(ruta, ahora)
            try:
                os.replace(tmp, alt)
            except OSError as e:
                _borrar_silencioso(tmp)
                return False, f"No se pudo guardar {ruta!r}: {e}"
            return True, (
                f"{msg} (el archivo estaba abierto; se guardo "
                f"{os.path.basename(alt)})"
            )
        except OSError as e:
            _borrar_silencioso(tmp)
            return False, f"No se pudo guardar {ruta!r}: {e}"

        return True, msg

    def confirmar(self, trabajo: TrabajoExport, ahora: datetime | None = None):
        """Marca un trabajo exitoso como hecho (y persiste el cierre de dia).

        Un cierre de `hoy` no persiste nada: el dia se sella recien al dia
        siguiente, cuando ya esta de verdad terminado.
        """
        ahora = ahora or self._reloj()
        anterior = self.estado.ultimo_dia
        self.estado = _confirmar_estado(self.estado, trabajo, ahora)
        if trabajo.tipo != "hora" and self.estado.ultimo_dia != anterior:
            try:
                self._persistir(self.estado.ultimo_dia)
            except Exception:  # noqa: BLE001 - no perder el export por esto
                log.warning("No se pudo persistir el ultimo dia exportado",
                            exc_info=True)


# ---------------------------------------------------------------------------
# Providers reales (import perezoso: el modulo se puede cargar sin BD)
# ---------------------------------------------------------------------------


def _reloj_local() -> datetime:
    from zoneinfo import ZoneInfo

    from ..config import ZONA_HORARIA

    return datetime.now(ZoneInfo(ZONA_HORARIA))


def _tiene_sesiones_db(fecha: str) -> bool:
    from ..database import listar_sesiones_por_fecha

    return bool(listar_sesiones_por_fecha(fecha))


def _dia_cerrado_db(fecha: str) -> bool:
    """True si el dia no tiene ninguna sesion 'Activa' (ya se puede cerrar)."""
    from ..database import listar_sesiones_por_fecha

    for sesion in listar_sesiones_por_fecha(fecha):
        if str(sesion["estado"] or "").strip() == ESTADO_SESION_ACTIVA:
            return False
    return True


def _exportar_dia(fecha: str, ruta: str):
    from .export_dia import exportar_dia

    return exportar_dia(fecha, ruta)


def _leer_ultimo_dia() -> str:
    from .. import config

    return str(config.leer_config("EXPORT_ULTIMO_DIA", "") or "")


def _persistir_ultimo_dia(fecha: str) -> None:
    from .. import config

    config.guardar_config("EXPORT_ULTIMO_DIA", fecha)


def _borrar_silencioso(ruta: str) -> None:
    try:
        os.remove(ruta)
    except OSError:
        pass


def _inicio_ventana(ultimo_dia: str, limite: date) -> date:
    """Primer dia candidato a cierre.

    Si nunca se exporto nada, solo se mira el dia limite (evita inundar de
    archivos el primer arranque). Si ya hay historial, desde el dia siguiente
    y acotado a `DIAS_CATCHUP_MAX` hacia atras.
    """
    if not ultimo_dia:
        return limite
    try:
        inicio = date.fromisoformat(ultimo_dia) + timedelta(days=1)
    except ValueError:
        return limite
    return max(inicio, limite - timedelta(days=DIAS_CATCHUP_MAX - 1))


# Reexportado para quien arme el programador a mano.
__all__ = [
    "DIAS_CATCHUP_MAX",
    "EstadoExport",
    "ProgramadorExport",
    "TrabajoExport",
    "decidir",
    "decidir_hoy",
    "ruta_export",
]
