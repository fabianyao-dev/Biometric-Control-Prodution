"""
database.py - Capa de persistencia (SQLite) del sistema de control biométrico.

Esquema relacional:
    roles                  Catalogo de roles (admin, operador, ...) soft-delete.
    operadores             Operadores registrados (soft-delete via `activo`).
    huellas_operador       Una fila por huella/plantilla del operador (un
                           operador puede tener varias).
    causas_paro            Motivos configurables de paro (soft-delete).
    sesiones_produccion    Entrada/salida del operador por turno.
    trabajos               Trabajos de corte por QR (folio|num_part|cantidad),
                           vinculados a una sesion; folio es la clave unica.
                           'Cerrado' SOLO al alcanzar cantidad_total; un
                           parcial (FINALIZAR TRABAJO / cierre de sesion) queda
                           'Abierto' con fecha_fin y es retomable.
    paros_produccion       Paros vinculados a una sesion (FK a sesion_id).

Politicas:
    - Soft-delete: roles, operadores y causas_paro marcan `activo=0`.
    - La hora de todos los timestamps es America/Monterrey (ver `ahora_local`),
      no UTC como el `CURRENT_TIMESTAMP` nativo de SQLite.
    - Las FK se respetan con PRAGMA foreign_keys=ON.
    - Las conexiones se abren por operacion (simples) o con
      check_same_thread=False para los hilos de la GUI.
"""

import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, ZONA_HORARIA

ZONA = ZoneInfo(ZONA_HORARIA)

# Operador que el sistema crea en solitario cuando NO hay usuarios reales
# registrados (modo desarrollo/pruebas): permite entrar sin huella. Nunca
# tiene huellas en `huellas_operador`, por lo que no aparece en `listar_fmds`.
OPERADOR_TEMPORAL_NOMBRE = "Operador Temporal (dev)"

# Permisos del sistema (se siembran en la BD). Los roles se asignan desde
# Administracion; aqui solo vive el catalogo y los defaults de primer arranque.
PERMISOS_SISTEMA = [
    ("autorizar_paro", "Autorizar la reanudacion de un paro (ademas del operador de la sesion).", 1),
    ("acceso_sesiones", "Ver la vista de Sesiones.", 2),
    ("acceso_admin", "Acceder a Administracion (incluye la gestion de permisos).", 3),
    ("actualizar_app", "Buscar y aplicar actualizaciones de la aplicacion.", 4),
]

# Permisos por defecto de los roles clasicos. Se aplican en el primer arranque
# (tabla permisos_roles vacia) y a cualquier rol de estos que no tenga ningun
# permiso asignado (p. ej. un rol recien creado en una BD existente).
PERMISOS_POR_DEFECTO = {
    "admin": ["autorizar_paro", "acceso_sesiones", "acceso_admin", "actualizar_app"],
    "supervisor": ["autorizar_paro", "acceso_sesiones"],
    "mantenimiento": ["autorizar_paro"],
}

# Causas de paro que se crean por defecto (modo "Primera pieza").
CAUSAS_PARO_POR_DEFECTO = ["Primera pieza"]

# Permiso que protege el acceso a Administracion; nunca puede quedarse sin
# ningun rol activo con el (evita quedarse fuera del sistema).
PERMISO_ACCESO_ADMIN = "acceso_admin"


def ahora_local() -> str:
    """Timestamp actual en la zona horaria de la planta (America/Monterrey)."""
    return datetime.now(ZONA).strftime("%Y-%m-%d %H:%M:%S")


def obtener_conexion():
    """Conexion utilizable desde cualquier hilo (SQLite + WAL)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # Funcion SQL con la hora local de la planta (para DEFAULTs del esquema).
    conn.create_function("ahora_monterrey", 0, ahora_local)
    return conn


def init_db():
    """Crea el esquema si no existe y migra versiones antiguas de la BD."""
    # La carpeta de la BD puede no existir aun (p. ej. si DB_PATH apunta a un
    # directorio nuevo): crearla antes de abrir la conexion.
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = obtener_conexion()
    cur = conn.cursor()

    cols = [r[1] for r in cur.execute("PRAGMA table_info(operadores)").fetchall()]
    if cols and "activo" not in cols:
        cur.execute("DROP TABLE operadores")

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS permisos (
            nombre TEXT PRIMARY KEY,
            descripcion TEXT NOT NULL,
            orden INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS permisos_roles (
            rol_id INTEGER NOT NULL REFERENCES roles(id),
            permiso TEXT NOT NULL REFERENCES permisos(nombre),
            PRIMARY KEY (rol_id, permiso)
        );

        CREATE TABLE IF NOT EXISTS operadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            huella_template BLOB NOT NULL,
            fecha_registro TIMESTAMP DEFAULT (ahora_monterrey()),
            activo INTEGER NOT NULL DEFAULT 1,
            rol_id INTEGER REFERENCES roles(id)
        );

        CREATE TABLE IF NOT EXISTS huellas_operador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operador_id INTEGER NOT NULL REFERENCES operadores(id),
            huella_template BLOB NOT NULL,
            fecha_captura TIMESTAMP DEFAULT (ahora_monterrey())
        );

        CREATE TABLE IF NOT EXISTS causas_paro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descripcion TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS sesiones_produccion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operador_id INTEGER NOT NULL REFERENCES operadores(id),
            fecha_inicio TIMESTAMP DEFAULT (ahora_monterrey()),
            fecha_fin TIMESTAMP,
            total_cortes INTEGER NOT NULL DEFAULT 0,
            estado TEXT NOT NULL DEFAULT 'Activa'
        );

        CREATE TABLE IF NOT EXISTS trabajos (
            folio INTEGER PRIMARY KEY,
            sesion_id INTEGER NOT NULL REFERENCES sesiones_produccion(id),
            num_part TEXT NOT NULL,
            cantidad_total INTEGER NOT NULL,
            cantidad_cortada INTEGER NOT NULL DEFAULT 0,
            fecha_inicio TIMESTAMP DEFAULT (ahora_monterrey()),
            fecha_fin TIMESTAMP,
            estado TEXT NOT NULL DEFAULT 'Abierto'
        );

        CREATE TABLE IF NOT EXISTS paros_produccion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id INTEGER NOT NULL REFERENCES sesiones_produccion(id),
            causa_id INTEGER REFERENCES causas_paro(id),
            inicio_paro TIMESTAMP DEFAULT (ahora_monterrey()),
            fin_paro TIMESTAMP,
            autorizado_por_operador_id INTEGER REFERENCES operadores(id)
        );
    """)

    # Migracion: agregar la columna de rol a operadores existentes.
    cols = [r[1] for r in cur.execute("PRAGMA table_info(operadores)").fetchall()]
    if "rol_id" not in cols:
        cur.execute(
            "ALTER TABLE operadores ADD COLUMN rol_id INTEGER REFERENCES roles(id)"
        )

    # Migracion multi-huella: mover las plantillas a su propia tabla (una fila
    # por huella) y quitar la columna `huella_template` de operadores.
    cols = [r[1] for r in cur.execute("PRAGMA table_info(operadores)").fetchall()]
    if "huella_template" in cols:
        for op in cur.execute(
            "SELECT id, huella_template FROM operadores "
            "WHERE huella_template IS NOT NULL AND length(huella_template) > 0"
        ).fetchall():
            cur.execute(
                "INSERT INTO huellas_operador (operador_id, huella_template, "
                "fecha_captura) VALUES (?, ?, ?)",
                (op["id"], op["huella_template"], ahora_local()),
            )
        cur.execute("ALTER TABLE operadores DROP COLUMN huella_template")

    # Roles por defecto: los operadores ya existentes quedan como admin.
    # "mantenimiento" viene por defecto (puede autorizar paros).
    for nombre in ("admin", "operador", "mantenimiento"):
        cur.execute("INSERT OR IGNORE INTO roles (nombre) VALUES (?)", (nombre,))
    admin = cur.execute(
        "SELECT id FROM roles WHERE nombre='admin' AND activo=1"
    ).fetchone()
    if admin is not None:
        cur.execute(
            "UPDATE operadores SET rol_id=? WHERE rol_id IS NULL", (admin["id"],)
        )

    # Permisos: catalogo + defaults por rol. Cada rol de PERMISOS_POR_DEFECTO
    # recibe sus permisos si no tiene NINGUNO (primer arranque o rol recien
    # creado en una BD existente); nunca pisa roles ya configurados.
    for nombre, descripcion, orden in PERMISOS_SISTEMA:
        cur.execute(
            "INSERT OR IGNORE INTO permisos (nombre, descripcion, orden) "
            "VALUES (?, ?, ?)",
            (nombre, descripcion, orden),
        )
    for rol_nombre, permisos in PERMISOS_POR_DEFECTO.items():
        rol = cur.execute(
            "SELECT id FROM roles WHERE nombre=?", (rol_nombre,)
        ).fetchone()
        if rol is None:
            continue
        tiene_permisos = cur.execute(
            "SELECT COUNT(*) AS n FROM permisos_roles WHERE rol_id=?",
            (rol["id"],),
        ).fetchone()["n"] > 0
        if not tiene_permisos:
            for permiso in permisos:
                cur.execute(
                    "INSERT OR IGNORE INTO permisos_roles (rol_id, permiso) "
                    "VALUES (?, ?)",
                    (rol["id"], permiso),
                )

    # Causas de paro por defecto (misma politica que agregar_causa_paro:
    # si existe inactiva, se reactiva; si no, se inserta).
    for descripcion in CAUSAS_PARO_POR_DEFECTO:
        causa = cur.execute(
            "SELECT id, activo FROM causas_paro WHERE descripcion=?",
            (descripcion,),
        ).fetchone()
        if causa is not None:
            if not causa["activo"]:
                cur.execute(
                    "UPDATE causas_paro SET activo=1 WHERE id=?", (causa["id"],)
                )
        else:
            cur.execute(
                "INSERT INTO causas_paro (descripcion) VALUES (?)",
                (descripcion,),
            )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

def listar_roles(activas_solo=True):
    """Devuelve los roles (id, nombre[, activo])."""
    conn = obtener_conexion()
    if activas_solo:
        rows = conn.execute(
            "SELECT id, nombre FROM roles WHERE activo=1 ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, nombre, activo FROM roles ORDER BY id"
        ).fetchall()
    conn.close()
    return rows


def agregar_rol(nombre: str) -> bool:
    """Agrega un rol. Si existe pero esta desactivado, lo reactiva."""
    nombre = nombre.strip()
    if not nombre:
        return False
    conn = obtener_conexion()
    existe = conn.execute(
        "SELECT id, activo FROM roles WHERE nombre=?", (nombre,)
    ).fetchone()
    if existe:
        if not existe["activo"]:
            conn.execute("UPDATE roles SET activo=1 WHERE id=?", (existe["id"],))
            conn.commit()
        conn.close()
        return True
    conn.execute("INSERT INTO roles (nombre) VALUES (?)", (nombre,))
    conn.commit()
    conn.close()
    return True


def renombrar_rol(rol_id: int, nombre: str) -> bool:
    """Renombra un rol. Falla si el nuevo nombre ya existe o esta vacio."""
    nombre = nombre.strip()
    if not nombre:
        return False
    conn = obtener_conexion()
    duplicado = conn.execute(
        "SELECT id FROM roles WHERE nombre=? AND id<>?", (nombre, rol_id)
    ).fetchone()
    if duplicado:
        conn.close()
        return False
    conn.execute("UPDATE roles SET nombre=? WHERE id=?", (nombre, rol_id))
    conn.commit()
    conn.close()
    return True


def eliminar_rol(rol_id: int):
    """Soft-delete de un rol. Devuelve (ok, mensaje).

    Nunca desactiva al ULTIMO rol activo con `acceso_admin` (mismo guard
    que actualizar_permisos_rol): desde que los permisos respetan
    r.activo=1 (Diagnostico 7.2.3), desactivar ese rol dejaria a nadie con
    acceso a Administracion.
    """
    conn = obtener_conexion()
    try:
        tiene_admin = conn.execute(
            "SELECT 1 FROM roles r "
            "JOIN permisos_roles pr ON pr.rol_id=r.id "
            "WHERE pr.rol_id=? AND r.activo=1 AND pr.permiso=?",
            (rol_id, PERMISO_ACCESO_ADMIN),
        ).fetchone() is not None
        if tiene_admin:
            otros = conn.execute(
                "SELECT COUNT(*) AS n FROM permisos_roles pr "
                "JOIN roles r ON r.id=pr.rol_id "
                "WHERE r.activo=1 AND pr.permiso=? AND pr.rol_id<>?",
                (PERMISO_ACCESO_ADMIN, rol_id),
            ).fetchone()["n"]
            if otros == 0:
                conn.close()
                return False, (
                    "No se puede desactivar: es el ultimo rol activo con "
                    "acceso a Administracion."
                )
        conn.execute("UPDATE roles SET activo=0 WHERE id=?", (rol_id,))
        conn.commit()
        conn.close()
        return True, ""
    except Exception as e:
        return False, f"Error en base de datos: {str(e)}"


def rol_id_por_defecto() -> int | None:
    """Id del rol 'operador' si existe; si no, del primer rol activo."""
    conn = obtener_conexion()
    fila = conn.execute(
        "SELECT id FROM roles WHERE nombre='operador' AND activo=1"
    ).fetchone()
    if fila is None:
        fila = conn.execute(
            "SELECT id FROM roles WHERE activo=1 ORDER BY id LIMIT 1"
        ).fetchone()
    conn.close()
    return fila["id"] if fila else None


# ---------------------------------------------------------------------------
# Permisos por rol
# ---------------------------------------------------------------------------

def listar_permisos():
    """Catalogo de permisos (nombre, descripcion, orden)."""
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT nombre, descripcion, orden FROM permisos "
        "ORDER BY orden, nombre"
    ).fetchall()
    conn.close()
    return rows


def permisos_de_rol(rol_id: int):
    """Nombres de permisos asignados a un rol."""
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT permiso FROM permisos_roles WHERE rol_id=? ORDER BY permiso",
        (rol_id,),
    ).fetchall()
    conn.close()
    return [r["permiso"] for r in rows]


def rol_tiene_permiso_operador(operador_id: int, permiso: str) -> bool:
    """¿El operador (via su rol ACTIVO) tiene el permiso?

    El JOIN pasa por la tabla `roles` exigiendo r.activo=1: desactivar un
    rol debe REVOCAR sus permisos de inmediato para todos sus operadores
    (antes un rol desactivado retenia autorizar_paro/acceso_admin/etc.;
    ver Diagnostico 7.2.3). La autenticacion ya solo acepta operadores
    activos (listar_fmds activos_solo=True), asi que aqui basta el filtro
    de rol.
    """
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT 1 FROM operadores o "
        "JOIN roles r ON r.id=o.rol_id AND r.activo=1 "
        "JOIN permisos_roles pr ON pr.rol_id=r.id "
        "WHERE o.id=? AND pr.permiso=?",
        (operador_id, permiso),
    ).fetchone()
    conn.close()
    return row is not None


def roles_con_permiso(permiso: str):
    """Roles ACTIVOS que tienen el permiso (para mensajes al usuario)."""
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT r.nombre FROM roles r "
        "JOIN permisos_roles pr ON pr.rol_id=r.id "
        "WHERE r.activo=1 AND pr.permiso=? ORDER BY r.nombre",
        (permiso,),
    ).fetchall()
    conn.close()
    return [r["nombre"] for r in rows]


def actualizar_permisos_rol(rol_id: int, nombres_permisos):
    """Reemplaza los permisos de un rol. Devuelve (ok, mensaje).

    Nunca permite dejar a ningun rol activo con `acceso_admin`: si el rol
    seria el ultimo en conservarlo, se rechaza (evita quedarse fuera de
    Administracion).
    """
    nombres_permisos = [p for p in (nombres_permisos or []) if p]
    try:
        conn = obtener_conexion()
        if PERMISO_ACCESO_ADMIN not in nombres_permisos:
            otros = conn.execute(
                "SELECT COUNT(*) AS n FROM permisos_roles pr "
                "JOIN roles r ON r.id=pr.rol_id "
                "WHERE r.activo=1 AND pr.permiso=? AND pr.rol_id<>?",
                (PERMISO_ACCESO_ADMIN, rol_id),
            ).fetchone()["n"]
            if otros == 0:
                conn.close()
                return False, (
                    "Al menos un rol activo debe conservar el acceso a "
                    "Administracion."
                )
        validos = {
            r["nombre"]
            for r in conn.execute("SELECT nombre FROM permisos").fetchall()
        }
        nombres_permisos = [p for p in nombres_permisos if p in validos]
        conn.execute("DELETE FROM permisos_roles WHERE rol_id=?", (rol_id,))
        for permiso in nombres_permisos:
            conn.execute(
                "INSERT INTO permisos_roles (rol_id, permiso) VALUES (?, ?)",
                (rol_id, permiso),
            )
        conn.commit()
        conn.close()
        return True, ""
    except Exception as e:
        return False, f"Error en base de datos: {str(e)}"


# ---------------------------------------------------------------------------
# Operadores
# ---------------------------------------------------------------------------

def guardar_operador(nombre: str, huellas, rol_id: int | None = None):
    """Registra un operador activo con una o varias huellas.

    `huellas` acepta una plantilla (bytes) o una lista de plantillas. Devuelve
    (ok, mensaje|id).

    Si ya existe un operador con ese nombre pero inactivo (soft-delete), lo
    reactiva y agrega las huellas nuevas (conserva las existentes). Si existe
    activo, rechaza el duplicado.
    """
    nombre = (nombre or "").strip()
    if not nombre:
        return False, "El nombre no puede ir vacio."
    if isinstance(huellas, bytes):
        huellas = [huellas]
    huellas = [h for h in (huellas or []) if h]
    if not huellas:
        return False, "Se necesita al menos una huella para registrar."
    try:
        conn = obtener_conexion()
        if rol_id is None:
            rol_id = rol_id_por_defecto()
        existe = conn.execute(
            "SELECT id, activo FROM operadores WHERE nombre=?", (nombre,)
        ).fetchone()
        if existe:
            if existe["activo"]:
                conn.close()
                return False, f"Ya existe un operador activo con el nombre '{nombre}'."
            conn.execute(
                "UPDATE operadores SET activo=1, rol_id=?, fecha_registro=? "
                "WHERE id=?",
                (rol_id, ahora_local(), existe["id"]),
            )
            operador_id = existe["id"]
        else:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO operadores (nombre, fecha_registro, rol_id) "
                "VALUES (?, ?, ?)",
                (nombre, ahora_local(), rol_id),
            )
            operador_id = cur.lastrowid
        for h in huellas:
            conn.execute(
                "INSERT INTO huellas_operador (operador_id, huella_template, "
                "fecha_captura) VALUES (?, ?, ?)",
                (operador_id, h, ahora_local()),
            )
        conn.commit()
        conn.close()
        return True, operador_id
    except Exception as e:
        return False, f"Error en base de datos: {str(e)}"


def listar_fmds(activos_solo=True):
    """Devuelve una fila por huella: (operador_id, nombre, huella_template)."""
    conn = obtener_conexion()
    where = "WHERE o.activo=1" if activos_solo else ""
    rows = conn.execute(
        f"SELECT o.id, o.nombre, h.huella_template "
        "FROM huellas_operador h "
        "JOIN operadores o ON o.id=h.operador_id "
        f"{where} ORDER BY o.id, h.id"
    ).fetchall()
    conn.close()
    return rows


def agregar_huella(operador_id: int, huella_template: bytes) -> bool:
    """Registra una huella adicional para un operador."""
    if not huella_template:
        return False
    conn = obtener_conexion()
    conn.execute(
        "INSERT INTO huellas_operador (operador_id, huella_template, "
        "fecha_captura) VALUES (?, ?, ?)",
        (operador_id, huella_template, ahora_local()),
    )
    conn.commit()
    conn.close()
    return True


def listar_huellas_operador(operador_id: int, con_template: bool = False):
    """Huellas de un operador (id, fecha_captura[, huella_template]).

    Con `con_template=True` agrega la plantilla, util para detectar
    duplicados al comparar capturas nuevas.
    """
    conn = obtener_conexion()
    columnas = "id, fecha_captura" + (", huella_template" if con_template else "")
    rows = conn.execute(
        f"SELECT {columnas} FROM huellas_operador "
        "WHERE operador_id=? ORDER BY id",
        (operador_id,),
    ).fetchall()
    conn.close()
    return rows


def reemplazar_huella(huella_id: int, huella_template: bytes) -> bool:
    """Sustituye la plantilla de una huella existente (re-captura)."""
    if not huella_template:
        return False
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE huellas_operador SET huella_template=?, fecha_captura=? "
        "WHERE id=?",
        (huella_template, ahora_local(), huella_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def eliminar_huella(huella_id: int) -> bool:
    """Elimina definitivamente una huella (no es un catalogo: se borra)."""
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("DELETE FROM huellas_operador WHERE id=?", (huella_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def obtener_operador_temporal():
    """Devuelve (id, nombre) del operador temporal de desarrollo.

    Sin operadores reales registrados, el sistema deja entrar por si solo
    (modo desarrollo). Crea el operador la primera vez y lo reutiliza.
    """
    conn = obtener_conexion()
    fila = conn.execute(
        "SELECT id, nombre FROM operadores "
        "WHERE nombre=? AND activo=1 LIMIT 1",
        (OPERADOR_TEMPORAL_NOMBRE,),
    ).fetchone()
    if fila is None:
        admin = conn.execute(
            "SELECT id FROM roles WHERE nombre='admin' AND activo=1 LIMIT 1"
        ).fetchone()
        rol_id = admin["id"] if admin else rol_id_por_defecto()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO operadores (nombre, fecha_registro, rol_id) "
            "VALUES (?, ?, ?)",
            (OPERADOR_TEMPORAL_NOMBRE, ahora_local(), rol_id),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT id, nombre FROM operadores WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
    conn.close()
    return fila["id"], fila["nombre"]


def eliminar_operador(operador_id: int):
    """Soft-delete: marca activo=0."""
    conn = obtener_conexion()
    conn.execute("UPDATE operadores SET activo=0 WHERE id=?", (operador_id,))
    conn.commit()
    conn.close()


def listar_operadores_admin():
    """Todos los operadores (id, nombre, fecha_registro, activo, rol)."""
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT o.id, o.nombre, o.fecha_registro, o.activo, r.nombre AS rol "
        "FROM operadores o LEFT JOIN roles r ON r.id=o.rol_id "
        "ORDER BY o.id"
    ).fetchall()
    conn.close()
    return rows


def actualizar_rol_operador(operador_id: int, rol_id: int):
    """Asigna un rol a un operador."""
    conn = obtener_conexion()
    conn.execute("UPDATE operadores SET rol_id=? WHERE id=?", (rol_id, operador_id))
    conn.commit()
    conn.close()


def obtener_rol_operador(operador_id: int):
    """Nombre del rol de un operador (o None si no tiene rol asignado)."""
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT r.nombre FROM operadores o "
        "LEFT JOIN roles r ON r.id=o.rol_id WHERE o.id=?",
        (operador_id,),
    ).fetchone()
    conn.close()
    return row["nombre"] if row else None


# ---------------------------------------------------------------------------
# Causas de paro
# ---------------------------------------------------------------------------

def listar_causas_paro(activas_solo=True):
    """Devuelve lista de filas (id, descripcion[, activo])."""
    conn = obtener_conexion()
    if activas_solo:
        rows = conn.execute(
            "SELECT id, descripcion FROM causas_paro WHERE activo=1 ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, descripcion, activo FROM causas_paro ORDER BY id"
        ).fetchall()
    conn.close()
    return rows


def agregar_causa_paro(descripcion: str) -> bool:
    """Agrega una causa. Si ya existe (inactiva), solo la reactiva."""
    descripcion = descripcion.strip()
    if not descripcion:
        return False
    conn = obtener_conexion()
    existe = conn.execute(
        "SELECT id, activo FROM causas_paro WHERE descripcion=?", (descripcion,)
    ).fetchone()
    if existe:
        if not existe["activo"]:
            conn.execute(
                "UPDATE causas_paro SET activo=1 WHERE id=?", (existe["id"],)
            )
            conn.commit()
        conn.close()
        return True
    conn.execute(
        "INSERT INTO causas_paro (descripcion) VALUES (?)", (descripcion,)
    )
    conn.commit()
    conn.close()
    return True


def eliminar_causa_paro(causa_id: int):
    conn = obtener_conexion()
    conn.execute("UPDATE causas_paro SET activo=0 WHERE id=?", (causa_id,))
    conn.commit()
    conn.close()


def listar_causas_frecuentes(limite: int = 6):
    """Causas activas mas usadas (por numero de paros registrados)."""
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT c.id, c.descripcion, COUNT(p.id) AS usos "
        "FROM causas_paro c "
        "LEFT JOIN paros_produccion p ON p.causa_id=c.id "
        "WHERE c.activo=1 "
        "GROUP BY c.id "
        "ORDER BY usos DESC, c.descripcion "
        "LIMIT ?",
        (limite,),
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Sesiones de produccion
# ---------------------------------------------------------------------------

def abrir_sesion(operador_id: int) -> int:
    """Crea una sesion 'Activa' y devuelve su id."""
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sesiones_produccion (operador_id, fecha_inicio, estado) "
        "VALUES (?, ?, 'Activa')",
        (operador_id, ahora_local()),
    )
    conn.commit()
    nueva_id = cur.lastrowid
    conn.close()
    return nueva_id


def cerrar_sesion(sesion_id: int, total_cortes: int):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE sesiones_produccion SET estado='Finalizada', "
        "fecha_fin=?, total_cortes=? WHERE id=?",
        (ahora_local(), total_cortes, sesion_id),
    )
    conn.commit()
    conn.close()


def actualizar_cortes_sesion(sesion_id: int, total_cortes: int):
    """Guarda el total de cortes actual de una sesion (checkpoint periodico).

    Se llama en intervalos regulares para que, ante un corte de luz o un
    cierre abrupto, la sesion conserve el ultimo conteo en la base de datos.
    """
    conn = obtener_conexion()
    conn.execute(
        "UPDATE sesiones_produccion SET total_cortes=? WHERE id=?",
        (total_cortes, sesion_id),
    )
    conn.commit()
    conn.close()


def sesion_activa_actual():
    """Devuelve el id de la sesion Activa vigente o None."""
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT id FROM sesiones_produccion "
        "WHERE estado='Activa' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def obtener_sesion_interrumpida():
    """Sesion 'Activa' heredada de un cierre abrupto (recuperable) o None.

    El cierre normal siempre finaliza la sesion (estado != 'Activa'), asi que
    una sesion 'Activa' al arrancar significa que la app se cerro sin pasar
    por `cerrar_sesion`. Devuelve id, operador_id, nombre y el total de
    cortes del ultimo checkpoint para poder retomarla.
    """
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT s.id, s.operador_id, o.nombre, s.total_cortes "
        "FROM sesiones_produccion s "
        "JOIN operadores o ON o.id=s.operador_id "
        "WHERE s.estado='Activa' ORDER BY s.id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def obtener_operador_de_sesion(sesion_id: int) -> str:
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT o.nombre FROM sesiones_produccion s "
        "JOIN operadores o ON o.id=s.operador_id WHERE s.id=?",
        (sesion_id,),
    ).fetchone()
    conn.close()
    return row["nombre"] if row else "Desconocido"


# ---------------------------------------------------------------------------
# Trabajos (QR folio|num_part|cantidad_total)
# ---------------------------------------------------------------------------

ESTADO_ABIERTO = "Abierto"
ESTADO_CERRADO = "Cerrado"


def abrir_trabajo(folio: int, sesion_id: int, num_part: str,
                  cantidad_total: int):
    """Abre (o retoma) un trabajo identificado por su folio unico.

    Devuelve (ok, mensaje|fila):
        - Folio nuevo: se crea 'Abierto' con cantidad_cortada=0.
        - Folio 'Abierto': se RETOMA sin perder `cantidad_cortada`; se
          re-vincula a la sesion actual, refresca num_part/cantidad con lo
          escaneado y limpia `fecha_fin` (queda activo de nuevo).
        - Folio 'Cerrado': rechazado (ya alcanzo su cantidad_total).
    """
    try:
        folio = int(folio)
    except (TypeError, ValueError):
        return False, "El folio debe ser numerico."
    try:
        cantidad_total = int(cantidad_total)
    except (TypeError, ValueError):
        return False, "La cantidad total debe ser numerica."
    if cantidad_total <= 0:
        return False, "La cantidad total debe ser mayor que cero."
    num_part = (num_part or "").strip()
    if not num_part:
        return False, "El numero de parte no puede ir vacio."

    conn = obtener_conexion()
    existe = conn.execute(
        "SELECT folio, sesion_id, num_part, cantidad_total, cantidad_cortada, "
        "       fecha_inicio, estado FROM trabajos WHERE folio=?", (folio,)
    ).fetchone()
    if existe is not None and existe["estado"] == ESTADO_CERRADO:
        conn.close()
        return False, (
            f"El trabajo {folio} ya esta CERRADO "
            f"({existe['cantidad_cortada']}/{existe['cantidad_total']})."
        )
    if existe is not None:
        conn.execute(
            "UPDATE trabajos SET sesion_id=?, num_part=?, cantidad_total=?, "
            "fecha_fin=NULL WHERE folio=?",
            (sesion_id, num_part, cantidad_total, folio),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT * FROM trabajos WHERE folio=?", (folio,)
        ).fetchone()
        conn.close()
        return True, fila
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO trabajos (folio, sesion_id, num_part, cantidad_total) "
        "VALUES (?, ?, ?, ?)",
        (folio, sesion_id, num_part, cantidad_total),
    )
    conn.commit()
    fila = conn.execute(
        "SELECT * FROM trabajos WHERE folio=?", (folio,)
    ).fetchone()
    conn.close()
    return True, fila


def completar_trabajo(folio: int, cantidad_cortada: int):
    """Marca 'Cerrado' un trabajo al ALCANZAR su cantidad_total.

    Solo la meta alcanzada cierra un trabajo; guarda la cantidad REAL
    cortada aunque se haya pasado (p. ej. 202/200).
    """
    conn = obtener_conexion()
    conn.execute(
        "UPDATE trabajos SET estado=?, fecha_fin=?, cantidad_cortada=? "
        "WHERE folio=?",
        (ESTADO_CERRADO, ahora_local(), int(cantidad_cortada), int(folio)),
    )
    conn.commit()
    conn.close()


def pausar_trabajo(folio: int, cantidad_cortada: int):
    """Guarda el parcial de un trabajo SIN cerrarlo (queda 'Abierto').

    Se usa en el cierre anticipado (FINALIZAR TRABAJO) y al apagar/cerrar
    sesion con trabajo en curso: `fecha_fin` marca el momento del parcial y
    `cantidad_cortada` permite retomarlo despues re-escaneando el mismo
    folio (que lo reactiva) o via recuperacion tras apagon.
    """
    conn = obtener_conexion()
    conn.execute(
        "UPDATE trabajos SET fecha_fin=?, cantidad_cortada=? "
        "WHERE folio=? AND estado=?",
        (ahora_local(), int(cantidad_cortada), int(folio), ESTADO_ABIERTO),
    )
    conn.commit()
    conn.close()


def actualizar_cantidad_cortada(folio: int, cantidad_cortada: int):
    """Checkpoint periodico del conteo del trabajo (respaldo ante apagon)."""
    conn = obtener_conexion()
    conn.execute(
        "UPDATE trabajos SET cantidad_cortada=? WHERE folio=?",
        (int(cantidad_cortada), int(folio)),
    )
    conn.commit()
    conn.close()


def obtener_trabajo_abierto(sesion_id: int | None = None):
    """Trabajo 'Abierto' EN CURSO (sin fecha_fin) o None.

    `fecha_fin IS NULL` distingue un trabajo activo de uno con parcial
    guardado (pausado): los pausados NO se restauran ni se muestran como
    vigentes; se retoman solo re-escanendo su folio.
    """
    conn = obtener_conexion()
    if sesion_id is None:
        row = conn.execute(
            "SELECT * FROM trabajos WHERE estado=? AND fecha_fin IS NULL "
            "ORDER BY folio DESC LIMIT 1",
            (ESTADO_ABIERTO,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM trabajos WHERE estado=? AND fecha_fin IS NULL "
            "AND sesion_id=? ORDER BY folio DESC LIMIT 1",
            (ESTADO_ABIERTO, sesion_id),
        ).fetchone()
    conn.close()
    return row


def listar_trabajos_de_sesion(sesion_id: int):
    """Trabajos de una sesion para reportes (uno por fila, folio unico)."""
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT folio, num_part, cantidad_total, cantidad_cortada, "
        "       fecha_inicio, fecha_fin, estado "
        "FROM trabajos WHERE sesion_id=? ORDER BY fecha_inicio",
        (sesion_id,),
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Paros de produccion
# ---------------------------------------------------------------------------

def iniciar_paro(sesion_id: int) -> int:
    """Crea un paro 'en curso' (sin causa ni fin). Devuelve id."""
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO paros_produccion (sesion_id, inicio_paro) VALUES (?, ?)",
        (sesion_id, ahora_local()),
    )
    conn.commit()
    nuevo_id = cur.lastrowid
    conn.close()
    return nuevo_id


def finalizar_paro(paro_id: int, causa_id: int, operador_id: int):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE paros_produccion SET causa_id=?, fin_paro=?, "
        "autorizado_por_operador_id=? WHERE id=?",
        (causa_id, ahora_local(), operador_id, paro_id),
    )
    conn.commit()
    conn.close()


def paro_en_curso(sesion_id: int):
    """Paro sin fin de la sesion (None si no hay)."""
    conn = obtener_conexion()
    row = conn.execute(
        "SELECT id FROM paros_produccion WHERE sesion_id=? AND fin_paro IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (sesion_id,),
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def obtener_paros_de_sesion(sesion_id: int):
    """Paros de la sesion con causa y nombre del autorizador, para reportes."""
    conn = obtener_conexion()
    rows = conn.execute(
        "SELECT p.id, c.descripcion, p.inicio_paro, p.fin_paro, "
        "       a.nombre AS autorizador "
        "FROM paros_produccion p "
        "LEFT JOIN causas_paro c ON c.id=p.causa_id "
        "LEFT JOIN operadores a ON a.id=p.autorizado_por_operador_id "
        "WHERE p.sesion_id=? ORDER BY p.id",
        (sesion_id,),
    ).fetchall()
    conn.close()
    return rows


def listar_sesiones():
    """Todas las sesiones con nombre de operador y duracion en minutos."""
    conn = obtener_conexion()
    ahora = ahora_local()
    rows = conn.execute(
        "SELECT s.id, o.nombre, s.fecha_inicio, s.fecha_fin, s.total_cortes, "
        "       s.estado, "
        "       ROUND(COALESCE((julianday(s.fecha_fin)-julianday(s.fecha_inicio))*1440, "
        "                      (julianday(?)-julianday(s.fecha_inicio))*1440), 1) "
        "       AS minutos, "
        "       (SELECT COUNT(*) FROM paros_produccion p WHERE p.sesion_id=s.id) "
        "       AS num_paros "
        "FROM sesiones_produccion s "
        "JOIN operadores o ON o.id=s.operador_id "
        "ORDER BY s.id DESC",
        (ahora,),
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------

def resumen_dia(fecha: str):
    """Resumen (sesiones, cortes, paros) para una fecha 'YYYY-MM-DD'."""
    conn = obtener_conexion()
    filas = conn.execute(
        "SELECT s.id, o.nombre, s.fecha_inicio, s.fecha_fin, s.total_cortes, "
        "       COALESCE(SUM(CASE WHEN p.fin_paro IS NOT NULL "
        "            THEN (julianday(p.fin_paro)-julianday(p.inicio_paro))*1440 "
        "            ELSE 0 END),0) AS minutos_paro, "
        "       COUNT(p.id) AS num_paros "
        "FROM sesiones_produccion s "
        "JOIN operadores o ON o.id=s.operador_id "
        "LEFT JOIN paros_produccion p ON p.sesion_id=s.id "
        "WHERE date(s.fecha_inicio)=? "
        "GROUP BY s.id ORDER BY s.fecha_inicio",
        (fecha,),
    ).fetchall()
    conn.close()
    return filas


if __name__ == "__main__":
    init_db()
    print("Base de datos inicializada con esquema relacional.")