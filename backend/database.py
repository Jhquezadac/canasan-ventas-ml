"""SQLite: operaciones, predicciones, modelos, dataset_log."""
from __future__ import annotations

import sqlite3
from datetime import datetime, date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "storage" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto TEXT NOT NULL,
    dpto TEXT,
    cliente TEXT NOT NULL,
    fecha_separacion TEXT NOT NULL,
    fecha_cierre TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('CERRADA','ANULADA','EN_PROCESO')),
    monto_total REAL NOT NULL,
    n_pagos INTEGER NOT NULL DEFAULT 1,
    dias_venta REAL,
    fuente TEXT NOT NULL DEFAULT 'dataset',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ops_estado ON operaciones(estado);
CREATE INDEX IF NOT EXISTS idx_ops_proy ON operaciones(proyecto);

CREATE TABLE IF NOT EXISTS predicciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto TEXT NOT NULL,
    monto_total REAL NOT NULL,
    n_pagos INTEGER NOT NULL,
    mes_sep INTEGER NOT NULL,
    anio_sep INTEGER NOT NULL,
    probabilidad REAL NOT NULL,
    prediccion TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS modelos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    accuracy REAL, precision REAL, recall REAL, f1 REAL, auc REAL,
    es_activo INTEGER NOT NULL DEFAULT 0,
    n_registros INTEGER,
    trained_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dataset_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo TEXT NOT NULL,
    filas INTEGER,
    operaciones INTEGER,
    mensaje TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def _d(v) -> str | None:
    if v is None:
        return None
    try:
        if not isinstance(v, (list, tuple)) and pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def bulk_insert_operaciones(ops: pd.DataFrame, fuente: str = "dataset") -> int:
    rows = []
    for _, r in ops.iterrows():
        dias = r.get("DIAS_VENTA")
        if dias is None or (isinstance(dias, float) and pd.isna(dias)):
            dias = None
        rows.append((
            r["PROYECTO"], _d(r.get("DPTO")), r["CLIENTE"],
            _d(r["FECHA_SEPARACION"]), _d(r.get("FECHA_CIERRE")),
            r["ESTADO"], float(r["MONTO_TOTAL"]), int(r["N_PAGOS"]),
            dias, fuente,
        ))
    with connect() as conn:
        conn.executemany(
            """INSERT INTO operaciones (proyecto, dpto, cliente, fecha_separacion,
               fecha_cierre, estado, monto_total, n_pagos, dias_venta, fuente)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(rows)


def delete_dataset_operaciones() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM operaciones WHERE fuente='dataset'")


def fetch_operaciones(estado: str | None = None, order: str = "id") -> pd.DataFrame:
    """order='id' conserva el orden del dataset (reproducibilidad del CV del notebook)."""
    q = "SELECT * FROM operaciones"
    params: tuple = ()
    if estado and estado != "TODAS":
        q += " WHERE estado = ?"
        params = (estado,)
    q += " ORDER BY id" if order == "id" else " ORDER BY fecha_separacion DESC"
    with connect() as conn:
        df = pd.read_sql_query(q, conn, params=params)
    df = df.rename(columns={
        "proyecto": "PROYECTO", "dpto": "DPTO", "cliente": "CLIENTE",
        "fecha_separacion": "FECHA_SEPARACION", "fecha_cierre": "FECHA_CIERRE",
        "estado": "ESTADO", "monto_total": "MONTO_TOTAL", "n_pagos": "N_PAGOS",
        "dias_venta": "DIAS_VENTA", "fuente": "FUENTE", "created_at": "CREATED_AT",
    })
    for c in ("FECHA_SEPARACION", "FECHA_CIERRE"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def insert_prediccion(proyecto, monto, pagos, mes, anio, prob, etiqueta) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO predicciones (proyecto, monto_total, n_pagos, mes_sep, anio_sep, probabilidad, prediccion) VALUES (?,?,?,?,?,?,?)",
            (proyecto, float(monto), int(pagos), int(mes), int(anio), float(prob), etiqueta),
        )
        return int(cur.lastrowid)


def fetch_predicciones(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM predicciones ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_modelo_result(nombre, metrics, activo, n_registros) -> None:
    with connect() as conn:
        if activo:
            conn.execute("UPDATE modelos SET es_activo=0")
        conn.execute(
            "INSERT INTO modelos (nombre, accuracy, precision, recall, f1, auc, es_activo, n_registros) VALUES (?,?,?,?,?,?,?,?)",
            (nombre, metrics["Accuracy"], metrics["Precision"], metrics["Recall"],
             metrics["F1"], metrics["AUC"], 1 if activo else 0, n_registros),
        )


def activo_modelo() -> dict | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM modelos WHERE es_activo=1 ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None


def log_dataset(archivo, filas, operaciones, mensaje) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO dataset_log (archivo, filas, operaciones, mensaje) VALUES (?,?,?,?)",
            (archivo, filas, operaciones, mensaje),
        )


def insert_operacion_manual(proyecto, dpto, cliente, monto, pagos, mes, anio) -> int:
    fecha = f"{int(anio):04d}-{int(mes):02d}-01"
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO operaciones (proyecto, dpto, cliente, fecha_separacion,
               estado, monto_total, n_pagos, fuente) VALUES (?,?,?,?,'EN_PROCESO',?,?,'usuario')""",
            (proyecto.upper().strip(), (dpto or "").upper().strip() or None,
             cliente.upper().strip(), fecha, float(monto), int(pagos)),
        )
        return int(cur.lastrowid)


def delete_operacion(op_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM operaciones WHERE id=? AND fuente='usuario'", (op_id,))
        return cur.rowcount > 0
