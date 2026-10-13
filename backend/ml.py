"""Modelos ML: replicación del notebook + XGBoost, entrenamiento, predicción."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score,
                             roc_curve, make_scorer)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "storage" / "models"
BEST_PATH = MODELS_DIR / "best_model.joblib"
META_PATH = MODELS_DIR / "meta.json"

FEATURE_COLS = [
    "MONTO_TOTAL", "N_PAGOS", "MES_SEP", "ANIO_SEP",
    "PROY_ESMERALDA", "PROY_MARBELLA", "PROY_POSITANO",
    "PROY_ROMA", "PROY_RUBI", "PROY_SANTORINI",
]
PROYECTOS = ["CAPRI", "ESMERALDA", "MARBELLA", "POSITANO", "ROMA", "RUBI", "SANTORINI"]

UMBRAL_ALTA = 0.70
UMBRAL_MEDIA = 0.40


def construir_modelos() -> dict:
    return {
        "LogisticRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]),
        "DecisionTree": DecisionTreeClassifier(max_depth=5, random_state=42, class_weight="balanced"),
        "RandomForest": RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42, class_weight="balanced"),
        "GradientBoosting": GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42),
        "KNN": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", KNeighborsClassifier(n_neighbors=5)),
        ]),
        "XGBoost": XGBClassifier(
            n_estimators=150, max_depth=4, learning_rate=0.1,
            subsample=0.9, colsample_bytree=0.9, random_state=42,
            eval_metric="logloss", scale_pos_weight=0.25,
        ),
    }


def featurize(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["MONTO_TOTAL"] = pd.to_numeric(df["MONTO_TOTAL"], errors="coerce").astype(float)
    out["N_PAGOS"] = pd.to_numeric(df["N_PAGOS"], errors="coerce").astype(float)
    out["MES_SEP"] = pd.to_numeric(df["MES_SEP"], errors="coerce").astype(float)
    out["ANIO_SEP"] = pd.to_numeric(df["ANIO_SEP"], errors="coerce").astype(float)
    proj = df["PROYECTO"].astype(str).str.upper().str.strip()
    for col in FEATURE_COLS[4:]:
        out[col] = (proj == col.replace("PROY_", "")).astype(float)
    return out[FEATURE_COLS].fillna(0)


def dataset_modelo(operaciones: pd.DataFrame) -> pd.DataFrame:
    ops = operaciones[operaciones["ESTADO"].isin(["CERRADA", "ANULADA"])].copy()
    ops["TARGET"] = (ops["ESTADO"] == "CERRADA").astype(int)
    ops["MES_SEP"] = ops["FECHA_SEPARACION"].dt.month
    ops["ANIO_SEP"] = ops["FECHA_SEPARACION"].dt.year
    return ops


def entrenar(operaciones: pd.DataFrame) -> dict:
    """CV estratificado 5-fold (igual al notebook) + holdout del mejor."""
    ops = dataset_modelo(operaciones)
    X = featurize(ops)
    y = ops["TARGET"].values

    modelos = construir_modelos()
    scoring = {
        "accuracy": make_scorer(accuracy_score),
        "precision": make_scorer(precision_score, zero_division=0),
        "recall": make_scorer(recall_score, zero_division=0),
        "f1": make_scorer(f1_score, zero_division=0),
        "auc": make_scorer(roc_auc_score, response_method="predict_proba"),
    }
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    filas = []
    ajustados = {}
    for nombre, modelo in modelos.items():
        s = cross_validate(modelo, X, y, cv=cv, scoring=scoring, n_jobs=-1)
        filas.append({
            "Modelo": nombre,
            "Accuracy": round(float(np.nanmean(s["test_accuracy"])), 4),
            "Precision": round(float(np.nanmean(s["test_precision"])), 4),
            "Recall": round(float(np.nanmean(s["test_recall"])), 4),
            "F1": round(float(np.nanmean(s["test_f1"])), 4),
            "AUC": round(float(np.nanmean(s["test_auc"])), 4),
        })
        modelo.fit(X, y)
        ajustados[nombre] = modelo

    tabla = pd.DataFrame(filas).sort_values("AUC", ascending=False).reset_index(drop=True)
    mejor = tabla.iloc[0]["Modelo"]

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
    m = construir_modelos()[mejor]
    m.fit(Xtr, ytr)
    proba = m.predict_proba(Xte)[:, 1]
    pred = (proba >= 0.5).astype(int)
    fpr, tpr, _ = roc_curve(yte, proba)

    importancias = _importancias(ajustados[mejor], X, y, mejor)

    meta = {
        "mejor": mejor,
        "tabla": tabla.to_dict(orient="records"),
        "n_registros": int(len(ops)),
        "tasa_cierre": round(float(y.mean()) * 100, 2),
        "feat_mean": [round(float(v), 4) for v in X.mean().tolist()],
        "feat_std": [round(float(v) if v else 1.0, 4) for v in X.std().tolist()],
        "holdout": {
            "accuracy": round(float(accuracy_score(yte, pred)), 4),
            "precision": round(float(precision_score(yte, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(yte, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(yte, pred, zero_division=0)), 4),
            "auc": round(float(roc_auc_score(yte, proba)), 4),
            "matriz": confusion_matrix(yte, pred).tolist(),
            "roc": {"fpr": [round(float(v), 4) for v in fpr],
                    "tpr": [round(float(v), 4) for v in tpr]},
        },
        "importancias": importancias,
        "umbral_alta": UMBRAL_ALTA,
        "umbral_media": UMBRAL_MEDIA,
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(ajustados[mejor], BEST_PATH)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _importancias(modelo, X, y, nombre: str) -> list[dict]:
    if nombre == "LogisticRegression":
        clf = modelo.named_steps["clf"]
        vals = np.abs(clf.coef_[0])
    elif nombre == "KNN":
        from sklearn.inspection import permutation_importance
        r = permutation_importance(modelo, X, y, n_repeats=10, random_state=42)
        vals = r.importances_mean
    else:
        vals = getattr(modelo, "feature_importances_", np.zeros(len(FEATURE_COLS)))
    serie = pd.Series(np.asarray(vals, dtype=float), index=FEATURE_COLS).sort_values(ascending=False)
    total = float(serie.sum()) or 1.0
    return [
        {"factor": k, "peso": round(float(v), 4), "peso_pct": round(float(v) / total * 100, 1)}
        for k, v in serie.items()
    ]


def cargar_mejor():
    if not BEST_PATH.exists() or not META_PATH.exists():
        return None, None
    return joblib.load(BEST_PATH), json.loads(META_PATH.read_text(encoding="utf-8"))


def clasificar(prob: float) -> str:
    if prob >= UMBRAL_ALTA:
        return "ALTA"
    if prob >= UMBRAL_MEDIA:
        return "MEDIA"
    return "BAJA"


def recomendar(etiqueta: str, prob: float, proyecto: str) -> str:
    if etiqueta == "ALTA":
        return (f"Alta probabilidad de cierre ({prob:.0%}). Priorice el envío de la carta de "
                f"compromiso y cierre de financiamiento en {proyecto}.")
    if etiqueta == "MEDIA":
        return (f"Probabilidad media ({prob:.0%}). Programe una reunión de seguimiento, "
                f"ofrezca opciones de financiamiento y refuerce la propuesta de valor.")
    return (f"Baja probabilidad de cierre ({prob:.0%}). Active un plan de rescate: "
            f"contacto en 48h, descuento o cambio de unidad alternativa.")


def predecir(modelo, proyecto: str, monto: float, pagos: int, mes: int, anio: int) -> dict:
    row = pd.DataFrame([{
        "PROYECTO": proyecto.upper().strip(),
        "MONTO_TOTAL": monto, "N_PAGOS": pagos,
        "MES_SEP": mes, "ANIO_SEP": anio,
    }])
    X = featurize(row)
    prob = float(modelo.predict_proba(X)[0, 1])
    etiqueta = clasificar(prob)
    feat_mean = feat_std = None
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            feat_mean, feat_std = meta.get("feat_mean"), meta.get("feat_std")
        except Exception:
            pass
    contrib = _contribuciones(modelo, X.iloc[0], feat_mean, feat_std)
    return {
        "proyecto": proyecto.upper().strip(),
        "monto_total": float(monto),
        "n_pagos": int(pagos),
        "mes_sep": int(mes),
        "anio_sep": int(anio),
        "probabilidad": round(prob, 4),
        "etiqueta": etiqueta,
        "recomendacion": recomendar(etiqueta, prob, proyecto.upper().strip()),
        "contribuciones": contrib,
    }


def _contribuciones(modelo, x_row: pd.Series, feat_mean=None, feat_std=None) -> list[dict]:
    """Contribución orientativa por feature (coef×x estandarizado en LR; importancia×z en el resto)."""
    if hasattr(modelo, "named_steps") and "clf" in getattr(modelo, "named_steps", {}):
        clf = modelo.named_steps["clf"]
        scaler = modelo.named_steps["scaler"]
        xs = scaler.transform(pd.DataFrame([x_row.values], columns=FEATURE_COLS))[0]
        vals = clf.coef_[0] * xs
    elif hasattr(modelo, "feature_importances_"):
        mean = np.array(feat_mean) if feat_mean else np.zeros(len(FEATURE_COLS))
        std = np.array(feat_std) if feat_std else np.ones(len(FEATURE_COLS))
        std = np.where(std == 0, 1.0, std)
        z = (x_row.values.astype(float) - mean) / std
        vals = np.asarray(modelo.feature_importances_, dtype=float) * z
    else:
        vals = np.zeros(len(FEATURE_COLS))
    s = pd.Series(np.asarray(vals, dtype=float), index=FEATURE_COLS)
    s = s.reindex(FEATURE_COLS).fillna(0.0)
    top = s.reindex(s.abs().sort_values(ascending=False).index).head(4)
    out = []
    for k, v in top.items():
        efecto = "favorece cierre" if v > 0 else "reduce cierre"
        etiqueta = k.replace("PROY_", "Proy. ")
        if k == "MONTO_TOTAL":
            etiqueta = "Monto total"
        elif k == "N_PAGOS":
            etiqueta = "N° de pagos"
        elif k == "MES_SEP":
            etiqueta = "Mes de separación"
        elif k == "ANIO_SEP":
            etiqueta = "Año de separación"
        out.append({"factor": etiqueta, "impacto": round(float(v), 4), "efecto": efecto})
    return out


def score_operaciones(modelo, operaciones: pd.DataFrame) -> pd.DataFrame:
    """Agrega probabilidad de cierre a las operaciones EN_PROCESO."""
    enp = operaciones[operaciones["ESTADO"] == "EN_PROCESO"].copy()
    if enp.empty:
        return enp
    enp["MES_SEP"] = enp["FECHA_SEPARACION"].dt.month
    enp["ANIO_SEP"] = enp["FECHA_SEPARACION"].dt.year
    X = featurize(enp)
    enp["PROB"] = modelo.predict_proba(X)[:, 1]
    enp["ETIQUETA"] = enp["PROB"].map(clasificar)
    return enp
