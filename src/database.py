import sqlite3

from src.config import DB_PATH


def init_db():
    """Inicializa la base de datos con la tabla de operadores."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode=WAL;")

    cols = [r[1] for r in cursor.execute("PRAGMA table_info(operadores)").fetchall()]
    if cols and "numero_empleado" in cols:
        cursor.execute("DROP TABLE operadores")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            huella_template BLOB NOT NULL,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def guardar_operador(nombre: str, huella_template: bytes):
    """Guarda un nuevo operador en SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO operadores (nombre, huella_template)
            VALUES (?, ?)
        ''', (nombre, huella_template))
        conn.commit()
        conn.close()
        return True, "Operador registrado correctamente."
    except Exception as e:
        return False, f"Error en base de datos: {str(e)}"


def listar_fmds():
    """Devuelve lista de (id, nombre, huella_template) de todos los operadores."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, nombre, huella_template FROM operadores ORDER BY id"
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    init_db()
    print("✅ Base de datos inicializada correctamente.")
