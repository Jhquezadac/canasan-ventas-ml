"""API del aplicativo de predicción de cierre de ventas — CANASAN."""
from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database as db
from . import ml, pipeline, reports

ROOT = Path(__file__).resolve().parent.parent
DATA_XLSX = ROOT / "data" / "CANASAN_2026_SIN_COLORES.xlsx"
FRONTEND = ROOT / "frontend"

_estado_stats: dict = {}
_modelo_cache: dict | None = None  # {"modelo": fitted, "meta": dict}


def _entrenar_y_activar(operaciones: pd.DataFrame, archivo: str) -> dict:
    global _modelo_cache
    meta = ml.entrenar(operaciones)
    db.save_modelo_result(meta["mejor"], meta["tabla"][0], True, meta["n_registros"])
    modelo, _ = ml.cargar_mejor()
    _modelo_cache = {"modelo": modelo, "meta": meta}
    return meta


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    global _estado_stats, _modelo_cache
    ops = db.fetch_operaciones()
    if ops.empty and DATA_XLSX.exists():
        ventas, operaciones, stats = pipeline.cargar_dataset(DATA_XLSX)
        db.bulk_insert_operaciones(operaciones, fuente="dataset")
        _estado_stats = stats
        db.log_dataset(DATA_XLSX.name, stats["filas_validas"], len(operaciones), "Carga inicial")
        ops = db.fetch_operaciones()
    else:
        try:
            if DATA_XLSX.exists():
                _, _, stats = pipeline.cargar_dataset(DATA_XLSX)
                _estado_stats = stats
            else:
                _estado_stats = {}
        except Exception:
            _estado_stats = {}
    cargado = False
    if db.activo_modelo() is not None and ml.BEST_PATH.exists():
        try:
            modelo, meta = ml.cargar_mejor()
            if modelo is not None and meta:
                _modelo_cache = {"modelo": modelo, "meta": meta}
                cargado = True
        except Exception:
            cargado = False
    if not cargado and not ops.empty:
        _entrenar_y_activar(ops, "inicial")
    yield


app = FastAPI(title="CANASAN — Predicción de cierre de ventas", version="1.0.0", lifespan=lifespan)


# ---------- esquemas ----------
class OperacionIn(BaseModel):
    proyecto: str
    dpto: str = ""
    cliente: str
    monto_total: float = Field(gt=0)
    n_pagos: int = Field(default=1, ge=1, le=120)
    mes_sep: int = Field(ge=1, le=12)
    anio_sep: int = Field(ge=2020, le=2035)


class PrediccionIn(BaseModel):
    proyecto: str
    monto_total: float = Field(gt=0)
    n_pagos: int = Field(ge=1, le=120)
    mes_sep: int = Field(ge=1, le=12)
    anio_sep: int = Field(ge=2020, le=2035)


# ---------- helpers ----------
def _kpis_y_series(ops: pd.DataFrame, modelo) -> dict:
    if ops.empty:
        return {
            "total_ops": 0, "cerradas": 0, "anuladas": 0, "en_proceso": 0,
            "tecv_conservadora": 0, "tecv_resueltas": 0, "tpv_global": 0,
            "prob_promedio": None, "valor_pipeline": 0, "ventas_proyectadas": 0,
            "serie_mensual": [], "por_proyecto": [],
            "embudo": {"separaciones": 0, "en_proceso": 0, "cerradas": 0, "anuladas": 0},
        }
    cerradas = int((ops["ESTADO"] == "CERRADA").sum())
    anuladas = int((ops["ESTADO"] == "ANULADA").sum())
    en_proceso = int((ops["ESTADO"] == "EN_PROCESO").sum())
    total = cerradas + anuladas + en_proceso

    enp = ml.score_operaciones(modelo, ops) if modelo is not None and en_proceso else pd.DataFrame()
    prob_prom = float(enp["PROB"].mean()) if not enp.empty else None
    valor_pipeline = float(ops.loc[ops["ESTADO"] == "EN_PROCESO", "MONTO_TOTAL"].sum())
    ventas_proyectadas = float((enp["MONTO_TOTAL"] * enp["PROB"]).sum()) if not enp.empty else 0.0

    c = ops[ops["ESTADO"] == "CERRADA"]
    serie = []
    meses = sorted(set(c["FECHA_CIERRE"].dropna().dt.to_period("M").astype(str))
                   | set(ops["FECHA_SEPARACION"].dropna().dt.to_period("M").astype(str)))
    for m in meses[-18:]:
        p = pd.Period(m)
        serie.append({
            "mes": m,
            "cerradas": int((c["FECHA_CIERRE"].dt.to_period("M").astype(str) == m).sum()),
            "separaciones": int((ops["FECHA_SEPARACION"].dt.to_period("M").astype(str) == m).sum()),
        })

    detalle = (ops.groupby("PROYECTO")["ESTADO"].value_counts().unstack(fill_value=0)
               .reindex(columns=["CERRADA", "ANULADA", "EN_PROCESO"], fill_value=0))
    detalle["SEPARACIONES"] = detalle.sum(axis=1)
    detalle["TECV"] = (detalle["CERRADA"] / detalle["SEPARACIONES"] * 100).round(1)
    por_proyecto = [
        {"proyecto": p, "cerradas": int(r["CERRADA"]), "anuladas": int(r["ANULADA"]),
         "en_proceso": int(r["EN_PROCESO"]), "separaciones": int(r["SEPARACIONES"]),
         "tecv": float(r["TECV"])}
        for p, r in detalle.sort_values("TECV", ascending=False).iterrows()
    ]

    tpv_df = pipeline.tpv(ops)
    cerradas_pct = cerradas / total * 100 if total else 0
    resueltas = cerradas + anuladas

    return {
        "total_ops": total,
        "cerradas": cerradas,
        "anuladas": anuladas,
        "en_proceso": en_proceso,
        "tecv_conservadora": round(cerradas_pct, 2),
        "tecv_resueltas": round(cerradas / resueltas * 100, 2) if resueltas else 0,
        "tpv_global": round(tpv_df, 1),
        "prob_promedio": round(prob_prom, 4) if prob_prom is not None else None,
        "valor_pipeline": valor_pipeline,
        "ventas_proyectadas": ventas_proyectadas,
        "serie_mensual": serie,
        "por_proyecto": por_proyecto,
        "embudo": {"separaciones": total, "en_proceso": en_proceso,
                   "cerradas": cerradas, "anuladas": anuladas},
    }


def _modelo_o_500() -> dict:
    if not _modelo_cache or _modelo_cache.get("modelo") is None:
        raise HTTPException(500, "Modelo no disponible; reintente el entrenamiento.")
    return _modelo_cache


# ---------- rutas base ----------
@app.get("/api/health")
def health():
    return {"ok": True, "hora": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/proyectos")
def proyectos():
    return {"proyectos": ml.PROYECTOS}


# ---------- Ficha de registro (instrumento de la tesis, Anexo 2) ----------
@app.get("/api/ficha")
def ficha():
    from datetime import date as _date
    ops = db.fetch_operaciones()
    if ops.empty:
        raise HTTPException(400, "No hay operaciones.")
    hoy = datetime.now().strftime("%d/%m/%Y")
    f_ini = ops["FECHA_SEPARACION"].min()
    f_fin = ops["FECHA_SEPARACION"].max()
    cab = {
        "investigador": "Quezada Carbajal, Jhoseph",
        "tipo_registro": "Histórico (2021–2026)",
        "fuente": "Base de datos comercial CANASAN (hoja VENTAS); excluye cocheras y depósitos vendidos de forma independiente",
        "fecha_inicio": f_ini.strftime("%d/%m/%Y"),
        "fecha_fin": f_fin.strftime("%d/%m/%Y"),
        "fecha_registro": hoy,
        "total_ops": int(len(ops)),
    }

    # Ficha N° 1 — TPV: operaciones cerradas, días y promedio acumulado
    c = ops[(ops["ESTADO"] == "CERRADA")].dropna(subset=["DIAS_VENTA"]).copy()
    c = c[c["DIAS_VENTA"] >= 0].sort_values(["FECHA_SEPARACION", "id"])
    acum, filas_tpv = [], []
    for i, (_, r) in enumerate(c.iterrows(), 1):
        dias = float(r["DIAS_VENTA"])
        acum.append(dias)
        filas_tpv.append({
            "n": i, "codigo": i,
            "fecha_registro": hoy,
            "fecha_sep": r["FECHA_SEPARACION"].strftime("%Y%m%d"),
            "fecha_cie": r["FECHA_CIERRE"].strftime("%Y%m%d") if pd.notna(r["FECHA_CIERRE"]) else "",
            "proy_dpto": f"{r['PROYECTO']} - {r['DPTO']}",
            "dias": int(dias),
            "prom": round(sum(acum) / len(acum), 1),
        })

    # Ficha N° 2 — TECV: evaluación trimestral acumulada
    ops_s = ops.dropna(subset=["FECHA_SEPARACION"]).sort_values("FECHA_SEPARACION")
    q = ops_s["FECHA_SEPARACION"].min().to_period("Q")
    q_fin = ops_s["FECHA_SEPARACION"].max().to_period("Q")
    pcts, filas_tecv, n = [], [], 0
    while q <= q_fin:
        limite = q.to_timestamp("Q")
        sub = ops_s[ops_s["FECHA_SEPARACION"] <= limite]
        antic = int(len(sub))
        cerr = int((sub["ESTADO"] == "CERRADA").sum())
        pct = round(cerr / antic * 100, 1) if antic else 0.0
        pcts.append(pct)
        n += 1
        filas_tecv.append({
            "n": n, "codigo": n,
            "fecha_registro": hoy,
            "fecha_eval": limite.strftime("%Y%m%d"),
            "anticipo": antic,
            "cerradas": cerr,
            "pct": pct,
            "prom": round(sum(pcts) / len(pcts), 1),
        })
        q += 1

    tpv_prom = round(float(c["DIAS_VENTA"].mean()), 1) if not c.empty else None
    total_tpv, total_tecv = len(filas_tpv), len(filas_tecv)
    return {
        "cabecera": cab,
        "ficha_tpv": {"indicador": "Tiempo promedio de venta (TPV)",
                      "dimension": "Celeridad del proceso comercial",
                      "medida": "Días",
                      "promedio_general": tpv_prom,
                      "total_filas": total_tpv,
                      "filas": filas_tpv[:20]},
        "ficha_tecv": {"indicador": "Tasa de éxito en cierre de ventas (TECV)",
                       "dimension": "Efectividad de la gestión comercial",
                       "medida": "%",
                       "total_filas": total_tecv,
                       "filas": filas_tecv[:20]},
    }


# ---------- Dashboard ----------
@app.get("/api/dashboard")
def dashboard():
    ops = db.fetch_operaciones()
    modelo = _modelo_cache["modelo"] if _modelo_cache else None
    return _kpis_y_series(ops, modelo)


# ---------- Oportunidades ----------
@app.get("/api/operaciones")
def listar_operaciones(
    estado: str = Query("TODAS"), proyecto: str = Query(""),
    q: str = Query(""), page: int = Query(1, ge=1), size: int = Query(15, ge=1, le=100),
):
    ops = db.fetch_operaciones()
    if estado and estado != "TODAS":
        ops = ops[ops["ESTADO"] == estado]
    if proyecto:
        ops = ops[ops["PROYECTO"] == proyecto.upper().strip()]
    if q:
        qq = q.upper().strip()
        ops = ops[ops["PROYECTO"].str.contains(qq, na=False)
                  | ops["CLIENTE"].astype(str).str.upper().str.contains(qq, na=False)
                  | ops["DPTO"].astype(str).str.upper().str.contains(qq, na=False)]
    ops = ops.sort_values("FECHA_SEPARACION", ascending=False, na_position="last")
    total_f = len(ops)
    pages = max(1, (total_f + size - 1) // size)
    page = min(page, pages)
    slice_ = ops.iloc[(page - 1) * size: page * size]
    registros = []
    for _, r in slice_.iterrows():
        registros.append({
            "id": int(r["id"]), "proyecto": r["PROYECTO"], "dpto": r.get("DPTO"),
            "cliente": r["CLIENTE"],
            "fecha_separacion": r["FECHA_SEPARACION"].strftime("%Y-%m-%d") if pd.notna(r["FECHA_SEPARACION"]) else None,
            "fecha_cierre": r["FECHA_CIERRE"].strftime("%Y-%m-%d") if pd.notna(r.get("FECHA_CIERRE")) else None,
            "estado": r["ESTADO"], "monto_total": float(r["MONTO_TOTAL"]),
            "n_pagos": int(r["N_PAGOS"]),
            "dias_venta": float(r["DIAS_VENTA"]) if pd.notna(r.get("DIAS_VENTA")) else None,
            "fuente": r.get("FUENTE", "dataset"),
        })
    return {"total": total_f, "page": page, "pages": pages, "items": registros}


@app.post("/api/operaciones", status_code=201)
def crear_operacion(op: OperacionIn):
    if op.proyecto.upper().strip() not in ml.PROYECTOS:
        raise HTTPException(400, f"Proyecto inválido; use uno de: {', '.join(ml.PROYECTOS)}")
    oid = db.insert_operacion_manual(op.proyecto, op.dpto, op.cliente, op.monto_total,
                                     op.n_pagos, op.mes_sep, op.anio_sep)
    return {"id": oid, "mensaje": "Oportunidad registrada como EN_PROCESO."}


@app.delete("/api/operaciones/{op_id}")
def borrar_operacion(op_id: int):
    if not db.delete_operacion(op_id):
        raise HTTPException(404, "Operación no encontrada o es del dataset original.")
    return {"ok": True}


# ---------- Predicción ----------
@app.post("/api/prediccion")
def predecir(p: PrediccionIn):
    if p.proyecto.upper().strip() not in ml.PROYECTOS:
        raise HTTPException(400, f"Proyecto inválido; use uno de: {', '.join(ml.PROYECTOS)}")
    m = _modelo_o_500()
    res = ml.predecir(m["modelo"], p.proyecto, p.monto_total, p.n_pagos, p.mes_sep, p.anio_sep)
    res["modelo"] = m["meta"]["mejor"]
    db.insert_prediccion(res["proyecto"], res["monto_total"], res["n_pagos"],
                         res["mes_sep"], res["anio_sep"], res["probabilidad"], res["etiqueta"])
    return res


@app.get("/api/predicciones")
def historial(limit: int = Query(20, ge=1, le=100)):
    return {"items": db.fetch_predicciones(limit)}


# ---------- Modelo ----------
@app.get("/api/modelo")
def info_modelo():
    m = _modelo_o_500()
    activo = db.activo_modelo() or {}
    return {
        "activo": activo.get("nombre", m["meta"]["mejor"]),
        "tabla": m["meta"]["tabla"],
        "holdout": m["meta"]["holdout"],
        "importancias": m["meta"]["importancias"],
        "n_registros": m["meta"]["n_registros"],
        "tasa_cierre": m["meta"]["tasa_cierre"],
        "umbral_alta": m["meta"]["umbral_alta"],
        "umbral_media": m["meta"]["umbral_media"],
        "features": ml.FEATURE_COLS,
        "entrenado": activo.get("trained_at"),
    }


@app.post("/api/modelo/reentrenar")
def reentrenar():
    ops = db.fetch_operaciones()
    if ops.empty:
        raise HTTPException(400, "No hay operaciones para entrenar.")
    meta = _entrenar_y_activar(ops, "manual")
    return {"ok": True, "mejor": meta["mejor"], "tabla": meta["tabla"]}


# ---------- Datos ----------
@app.get("/api/datos/info")
def datos_info():
    ops = db.fetch_operaciones()
    por_estado = ops["ESTADO"].value_counts().to_dict()
    return {
        "archivo": DATA_XLSX.name,
        "stats": _estado_stats,
        "operaciones": len(ops),
        "por_estado": por_estado,
        "manuales": int((ops["FUENTE"] == "usuario").sum()) if "FUENTE" in ops.columns else 0,
        "ultima_carga": None,
    }


@app.post("/api/datos/subir")
async def subir_archivo(file: UploadFile = File(...)):
    nombre = (file.filename or "").lower()
    contenido = await file.read()
    try:
        if nombre.endswith((".xlsx", ".xls")):
            try:
                raw = pd.read_excel(io.BytesIO(contenido), sheet_name="VENTAS", header=0)
            except ValueError:
                raw = pd.read_excel(io.BytesIO(contenido), header=0)
        elif nombre.endswith(".csv"):
            raw = pd.read_csv(io.BytesIO(contenido))
        else:
            raise HTTPException(400, "Formato no soportado; use .xlsx o .csv.")
        ventas, stats = pipeline.preparar_ventas(pipeline.normalizar_columnas(raw))
        operaciones = pipeline.construir_operaciones(ventas)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"No se pudo procesar el archivo: {e}")

    if len(operaciones) < 20:
        raise HTTPException(400, f"Muy pocas operaciones derivadas ({len(operaciones)}); verifique el formato.")

    db.delete_dataset_operaciones()
    db.bulk_insert_operaciones(operaciones, fuente="dataset")
    global _estado_stats
    _estado_stats = stats
    db.log_dataset(file.filename, stats["filas_validas"], len(operaciones), "Carga por usuario")
    meta = _entrenar_y_activar(db.fetch_operaciones(), file.filename)
    return {
        "ok": True, "filas_validas": stats["filas_validas"],
        "operaciones": len(operaciones),
        "por_estado": operaciones["ESTADO"].value_counts().to_dict(),
        "mejor_modelo": meta["mejor"],
        "mensaje": f"Dataset reemplazado ({len(operaciones)} operaciones) y modelos reentrenados.",
    }


# ---------- Análisis predictivo ----------
@app.get("/api/analisis")
def analisis():
    ops = db.fetch_operaciones()
    m = _modelo_o_500()
    kpis = _kpis_y_series(ops, m["modelo"])
    enp = ml.score_operaciones(m["modelo"], ops)
    if enp.empty:
        return {"top_pipeline": [], "en_riesgo": [], "rendimiento": kpis["por_proyecto"],
                "factores": m["meta"]["importancias"], "tpv_proyecto": []}
    enp_sorted = enp.sort_values("PROB", ascending=False)
    cols = ["PROYECTO", "DPTO", "CLIENTE", "MONTO_TOTAL", "N_PAGOS", "PROB", "ETIQUETA"]

    def _fila(r):
        return {
            "proyecto": r["PROYECTO"], "dpto": r.get("DPTO"), "cliente": r["CLIENTE"],
            "monto_total": float(r["MONTO_TOTAL"]), "n_pagos": int(r["N_PAGOS"]),
            "prob": round(float(r["PROB"]), 4), "etiqueta": r["ETIQUETA"],
        }

    c = ops[ops["ESTADO"] == "CERRADA"].dropna(subset=["DIAS_VENTA"])
    c = c[c["DIAS_VENTA"] >= 0]
    tpv_p = [{"proyecto": p, "tpv_dias": round(float(g["DIAS_VENTA"].mean()), 1),
              "n": int(len(g))}
             for p, g in c.groupby("PROYECTO")]
    tpv_p.sort(key=lambda x: -x["tpv_dias"])

    return {
        "top_pipeline": [_fila(r) for _, r in enp_sorted.head(10).iterrows()],
        "en_riesgo": [_fila(r) for _, r in enp_sorted.tail(10).iloc[::-1].iterrows()],
        "rendimiento": kpis["por_proyecto"],
        "factores": m["meta"]["importancias"],
        "tpv_proyecto": tpv_p,
        "ventas_futuras": kpis["ventas_proyectadas"],
        "prob_promedio": kpis["prob_promedio"],
    }


# ---------- Reportes ----------
@app.get("/api/reportes/pdf")
def reporte_pdf():
    ops_db = db.fetch_operaciones()
    m = _modelo_o_500()
    kpis = _kpis_y_series(ops_db, m["modelo"])
    enp = ml.score_operaciones(m["modelo"], ops_db).sort_values("PROB", ascending=False)
    contenido = reports.build_pdf(kpis, m["meta"], enp, m["meta"]["importancias"])
    fecha = datetime.now().strftime("%Y%m%d")
    return Response(
        content=contenido, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="reporte_canasan_{fecha}.pdf"'},
    )


@app.get("/api/reportes/excel")
def reporte_excel():
    ops_db = db.fetch_operaciones().rename(columns=str.lower)
    m = _modelo_o_500()
    kpis = _kpis_y_series(db.fetch_operaciones(), m["modelo"])
    contenido = reports.build_excel(kpis, ops_db, m["meta"], db.fetch_predicciones(100))
    fecha = datetime.now().strftime("%Y%m%d")
    return Response(
        content=contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="reporte_canasan_{fecha}.xlsx"'},
    )


# ---------- Frontend ----------
@app.middleware("http")
async def sin_cache_frontend(request, call_next):
    resp = await call_next(request)
    if request.url.path in ("/", "/app.js", "/index.html"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND)), name="frontend")
