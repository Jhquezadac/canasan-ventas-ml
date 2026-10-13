"""Pipeline replicada 1:1 del notebook de Kaggle (ventas-2020.ipynb)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    cols = []
    for i, c in enumerate(df.columns):
        if c is None or str(c).strip() == "" or str(c).startswith("Unnamed"):
            cols.append(f"COL_{i}")
        else:
            cols.append(
                str(c).strip().upper()
                .replace(" ", "_").replace(".", "")
                .replace("Á", "A").replace("É", "E")
                .replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
            )
    df = df.copy()
    df.columns = cols
    return df.rename(columns={
        "FECHA_DE_DOC": "FECHA",
        "CLIENTE_(APELLIDOS_Y_NOMBRES)": "CLIENTE",
        "NO_DPTO": "DPTO",
        "DOC_IDENT": "DNI",
    })


def leer_ventas(path: str | Path) -> pd.DataFrame:
    wb = load_workbook(path, data_only=True)
    ws = wb["VENTAS"]
    data = list(ws.values)
    df = pd.DataFrame(data[1:], columns=data[0])
    return normalizar_columnas(df)


def preparar_ventas(df: pd.DataFrame) -> pd.DataFrame:
    n_brutas = len(df)
    df = df.copy()

    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce", dayfirst=True)
    n_sin_fecha = int(df["FECHA"].isna().sum())
    df = df.dropna(subset=["FECHA"])

    df["MONTO"] = pd.to_numeric(df["TOTAL_S/"], errors="coerce")

    for c in ["CLIENTE", "PROYECTO", "SITUACION"]:
        if c in df.columns:
            df[c] = (
                df[c].astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip().str.upper()
            )

    df["PROYECTO"] = df["PROYECTO"].str.replace(r"^\d+\.\s*", "", regex=True).str.strip()
    df["DPTO"] = df["DPTO"].replace({"-": None, "": None})

    stats = {
        "filas_brutas": n_brutas,
        "filas_validas": len(df),
        "filas_sin_fecha": n_sin_fecha,
        "situaciones": df["SITUACION"].value_counts().to_dict(),
        "proyectos": df["PROYECTO"].value_counts().to_dict(),
        "n_montos_nulos": int(df["MONTO"].isna().sum()),
    }
    return df, stats


def construir_operaciones(ventas: pd.DataFrame) -> pd.DataFrame:
    df = ventas[ventas["SITUACION"].isin(["ANTICIPO", "CANCELACION", "ANULACION"])].copy()
    key = ["PROYECTO", "DPTO", "CLIENTE"]
    df = df.dropna(subset=key)

    ops = []
    for k, g in df.groupby(key):
        ant = g[g["SITUACION"] == "ANTICIPO"]["FECHA"]
        can = g[g["SITUACION"] == "CANCELACION"]["FECHA"]
        anu = g[g["SITUACION"] == "ANULACION"]["FECHA"]

        f_sep = ant.min() if not ant.empty else pd.NaT
        f_cie = can.max() if not can.empty else pd.NaT

        if not can.empty:
            estado = "CERRADA"
        elif not anu.empty:
            estado = "ANULADA"
        elif not ant.empty:
            estado = "EN_PROCESO"
        else:
            estado = "OTRO"

        row = dict(zip(key, k))
        row.update({
            "FECHA_SEPARACION": f_sep,
            "FECHA_CIERRE": f_cie,
            "ESTADO": estado,
            "MONTO_TOTAL": g["MONTO"].sum(),
            "N_PAGOS": len(g),
        })
        ops.append(row)

    ops = pd.DataFrame(ops)
    ops["DIAS_VENTA"] = (ops["FECHA_CIERRE"] - ops["FECHA_SEPARACION"]).dt.days
    return ops.dropna(subset=["FECHA_SEPARACION"]).reset_index(drop=True)


def tpv(ops: pd.DataFrame) -> float:
    c = ops[ops["ESTADO"] == "CERRADA"].dropna(subset=["DIAS_VENTA"])
    c = c[c["DIAS_VENTA"] >= 0]
    return float(c["DIAS_VENTA"].mean()) if not c.empty else float("nan")


def cargar_dataset(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    ventas, stats = preparar_ventas(leer_ventas(path))
    operaciones = construir_operaciones(ventas)
    return ventas, operaciones, stats
