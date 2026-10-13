/* CANASAN — portada + ficha, métricas, resultados, predicción */
const $ = (s) => document.querySelector(s);
const viewEl = $("#view");
const PROYECTOS = ["CAPRI", "ESMERALDA", "MARBELLA", "POSITANO", "ROMA", "RUBI", "SANTORINI"];
const MESES = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"];
let rocChart = null;

const fmtS = (n) => "S/ " + Number(n || 0).toLocaleString("es-PE", { maximumFractionDigits: 0 });
const pct1 = (x) => (Number(x) * 100).toFixed(1) + "%";
const dec4 = (x) => Number(x).toFixed(4);
const n1 = (v) => String(v).replace(".", ",");
const tagC = (c) => `<span class="tag t-${String(c).toLowerCase()}">${c}</span>`;
const isDark = () => document.documentElement.classList.contains("dark");

function applyTheme(t) {
  document.documentElement.classList.toggle("dark", t === "dark");
  localStorage.setItem("canasan-theme", t);
  const b = $("#theme-btn");
  if (b) { b.textContent = t === "dark" ? "☀" : "◐"; b.title = t === "dark" ? "Modo claro" : "Modo oscuro"; }
}
applyTheme(localStorage.getItem("canasan-theme") || "light");

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let m = "Error " + r.status;
    try { m = (await r.json()).detail || m; } catch {}
    throw new Error(m);
  }
  return r.json();
}
function esc(s) { return String(s ?? "—").replace(/</g, "&lt;"); }

/* ============ PORTADA ============ */
async function renderPortada() {
  viewEl.innerHTML = `
    <div class="portada">
      <div class="portada-info">
        <p class="eyebrow">Inmobiliaria de Surquillo · 2021–2026</p>
        <h1>Analítica predictiva del cierre de ventas</h1>
        <p class="lead">Modelos de machine learning entrenados con las operaciones comerciales
        del área de ventas. La ficha de registro, las métricas, los resultados y el predictor
        de cierre se generan en vivo desde el dataset CANASAN.</p>
        <dl class="stat-row" id="p-stats">
          <div><dt>Cargando…</dt><dd>—</dd></div>
        </dl>
      </div>
      <div class="portada-actions">
        <a class="action a1" href="#ficha"><span class="num">01</span><span>Ficha de registro<span class="desc">Tablas TPV y TECV del informe</span></span></a>
        <a class="action a2" href="#metricas"><span class="num">02</span><span>Métricas<span class="desc">Comparación de modelos de ML</span></span></a>
        <a class="action a3" href="#resultados"><span class="num">03</span><span>Resultados<span class="desc">Indicadores y análisis predictivo</span></span></a>
        <a class="action a4" href="#prediccion"><span class="num">04</span><span>Predicción<span class="desc">Probabilidad de cierre de una operación</span></span></a>
      </div>
    </div>`;
  try {
    const [d, m] = await Promise.all([api("/api/dashboard"), api("/api/modelo")]);
    $("#p-stats").innerHTML = `
      <div><dt>Operaciones</dt><dd>${d.total_ops}</dd></div>
      <div><dt>TPV</dt><dd>${d.tpv_global} días</dd></div>
      <div><dt>TECV</dt><dd>${d.tecv_conservadora}%</dd></div>
      <div><dt>Mejor AUC</dt><dd>${dec4(m.tabla[0].AUC)}</dd></div>`;
  } catch (e) {
    $("#p-stats").innerHTML = `<div class="err">${e.message}</div>`;
  }
}

/* ============ 01 FICHA DE REGISTRO ============ */
async function renderFicha() {
  viewEl.innerHTML = `<p class="muted">Generando ficha…</p>`;
  const f = await api("/api/ficha");
  const c = f.cabecera, t1 = f.ficha_tpv, t2 = f.ficha_tecv;
  viewEl.innerHTML = `
    <div class="page-head">
      <div><h2>01 · Ficha de registro</h2>
        <p class="page-sub">Instrumento de recolección de datos del informe (Anexo 2), generado con los datos actuales.</p></div>
      <button class="btn btn-plain noprint" onclick="window.print()">Imprimir / PDF</button>
    </div>

    <div class="block">
      <h3>Ficha de registro N° 1 — TPV</h3>
      <div class="ficha-meta">
        <div><div class="k">Investigadores</div><div class="v">${c.investigador}</div></div>
        <div><div class="k">Tipo de registro</div><div class="v">${c.tipo_registro}</div></div>
        <div><div class="k">Fuente</div><div class="v">${c.fuente}</div></div>
        <div><div class="k">Indicador</div><div class="v">${t1.indicador}</div></div>
        <div><div class="k">Fecha de inicio</div><div class="v">${c.fecha_inicio}</div></div>
        <div><div class="k">Fecha fin</div><div class="v">${c.fecha_fin}</div></div>
        <div><div class="k">Variable</div><div class="v">Cierre de ventas</div></div>
        <div><div class="k">Dimensión</div><div class="v">${t1.dimension}</div></div>
        <div><div class="k">Medida</div><div class="v">${t1.medida}</div></div>
      </div>
      <div class="scroll">
        <table class="thesis">
          <thead><tr>
            <th>N°</th><th>Fecha Registro</th><th>Código</th><th>Fecha separación</th><th>Fecha cierre</th>
            <th>Proyecto - Dpto.</th><th>Valor registrado (días)</th><th>Valor promedio (días)</th>
          </tr></thead>
          <tbody>
            ${t1.filas.map((r) => `<tr>
              <td>${r.n}</td><td>${r.fecha_registro}</td><td>${r.codigo}</td>
              <td>${r.fecha_sep}</td><td>${r.fecha_cie}</td>
              <td><b>${esc(r.proy_dpto)}</b></td>
              <td>${r.dias}</td><td>${n1(r.prom)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>
      <p class="nota">Se muestran las primeras <b>20 filas</b> de ${t1.total_filas} operaciones cerradas. Valor promedio (días) = promedio acumulado hasta la operación n. Promedio general: <b>${n1(t1.promedio_general)} días</b>.</p>
    </div>

    <div class="block">
      <h3>Ficha de registro N° 2 — TECV</h3>
      <div class="ficha-meta">
        <div><div class="k">Investigadores</div><div class="v">${c.investigador}</div></div>
        <div><div class="k">Tipo de registro</div><div class="v">${c.tipo_registro}</div></div>
        <div><div class="k">Fuente</div><div class="v">${c.fuente}</div></div>
        <div><div class="k">Indicador</div><div class="v">${t2.indicador}</div></div>
        <div><div class="k">Fecha de inicio</div><div class="v">${c.fecha_inicio}</div></div>
        <div><div class="k">Fecha fin</div><div class="v">${c.fecha_fin}</div></div>
        <div><div class="k">Variable</div><div class="v">Cierre de ventas</div></div>
        <div><div class="k">Dimensión</div><div class="v">${t2.dimension}</div></div>
        <div><div class="k">Medida</div><div class="v">${t2.medida}</div></div>
      </div>
      <div class="scroll">
        <table class="thesis">
          <thead><tr>
            <th>N°</th><th>Fecha Registro</th><th>Código</th><th>Fecha evaluación</th>
            <th>Operaciones con ANTICIPO (acum.)</th><th>Operaciones cerradas (acum.)</th>
            <th>Valor registrado (%)</th><th>Valor promedio acumulado (%)</th>
          </tr></thead>
          <tbody>
            ${t2.filas.map((r) => `<tr>
              <td>${r.n}</td><td>${r.fecha_registro}</td><td>${r.codigo}</td>
              <td>${r.fecha_eval}</td>
              <td>${r.anticipo}</td><td>${r.cerradas}</td>
              <td>${n1(r.pct)}</td><td>${n1(r.prom)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>
      <p class="nota">Se muestran las primeras <b>20 filas</b> de ${t2.total_filas} evaluaciones trimestrales. Valor registrado (%) = operaciones cerradas acumuladas ÷ operaciones con ANTICIPO acumuladas × 100. El valor promedio acumulado es la media de los porcentajes trimestrales.</p>
    </div>`;
}

/* ============ 02 MÉTRICAS ============ */
async function renderMetricas() {
  viewEl.innerHTML = `<p class="muted">Cargando métricas…</p>`;
  const m = await api("/api/modelo");
  const h = m.holdout;
  const [[tn, fp], [fn, tp]] = h.matriz;
  const maxImp = Math.max(...m.importancias.map((f) => f.peso_pct));
  viewEl.innerHTML = `
    <div class="page-head">
      <div><h2>02 · Métricas</h2>
        <p class="page-sub">Validación cruzada estratificada de 5 pliegues sobre ${m.n_registros} operaciones con desenlace conocido (tasa de cierre ${m.tasa_cierre}%). Modelo activo: <b>${m.activo}</b>.</p></div>
    </div>

    <div class="block">
      <h3>Comparación de modelos</h3>
      <div class="scroll">
        <table class="data">
          <thead><tr><th>Modelo</th><th class="num">Accuracy</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">F1</th><th class="num">AUC</th></tr></thead>
          <tbody>
            ${m.tabla.map((r, i) => `<tr class="${i === 0 ? "best" : ""}">
              <td>${r.Modelo}${i === 0 ? "  ← seleccionado" : ""}</td>
              <td class="num mono">${dec4(r.Accuracy)}</td><td class="num mono">${dec4(r.Precision)}</td>
              <td class="num mono">${dec4(r.Recall)}</td><td class="num mono">${dec4(r.F1)}</td>
              <td class="num mono">${dec4(r.AUC)}</td></tr>`).join("")}
          </tbody>
        </table>
      </div>
      <p class="nota">Selección del modelo activo por mayor AUC. Umbrales de predicción: ALTA ≥ 70%, MEDIA 40–69%, BAJA &lt; 40%.</p>
    </div>

    <div class="grid2">
      <div class="block">
        <h3>Rendimiento en holdout (25%)</h3>
        <table class="data">
          <tbody>
            <tr><td>Accuracy</td><td class="num mono">${dec4(h.accuracy)}</td></tr>
            <tr><td>Precision</td><td class="num mono">${dec4(h.precision)}</td></tr>
            <tr><td>Recall</td><td class="num mono">${dec4(h.recall)}</td></tr>
            <tr><td>F1</td><td class="num mono">${dec4(h.f1)}</td></tr>
            <tr><td><b>AUC</b></td><td class="num mono"><b>${dec4(h.auc)}</b></td></tr>
          </tbody>
        </table>
        <h3 style="margin-top:22px">Matriz de confusión</h3>
        <table class="data" style="max-width:320px">
          <thead><tr><th></th><th class="ctr">Pred. cerrada</th><th class="ctr">Pred. anulada</th></tr></thead>
          <tbody>
            <tr><td><b>Real cerrada</b></td><td class="ctr mono">${tp}</td><td class="ctr mono">${fn}</td></tr>
            <tr><td><b>Real anulada</b></td><td class="ctr mono">${fp}</td><td class="ctr mono">${tn}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="block">
        <h3>Curva ROC (holdout)</h3>
        <canvas id="ch-roc" height="260"></canvas>
        <h3 style="margin-top:22px">Factores del modelo activo</h3>
        ${m.importancias.map((f) => `
          <div class="bar-row">
            <span>${f.factor.replace("PROY_", "Proy. ")}</span>
            <span class="bar-track"><span class="bar-fill" style="width:${(f.peso_pct / maxImp * 100).toFixed(1)}%"></span></span>
            <span class="bar-val mono">${f.peso_pct}%</span>
          </div>`).join("")}
      </div>
    </div>`;
  const roc = h.roc;
  if (rocChart) { rocChart.destroy(); rocChart = null; }
  const ctx = $("#ch-roc");
  if (ctx && window.Chart) {
    const dark = isDark();
    const gridC = dark ? "#1f2937" : "#f3f4f6";
    const txtC = dark ? "#94a3b8" : "#6b7280";
    const lineC = dark ? "#60a5fa" : "#1d4ed8";
    rocChart = new Chart(ctx, {
      type: "line",
      data: { datasets: [
        { label: `ROC (AUC ${dec4(h.auc)})`, data: roc.fpr.map((x, i) => ({ x, y: roc.tpr[i] })),
          borderColor: lineC, backgroundColor: dark ? "rgba(96,165,250,.08)" : "rgba(29,78,216,.06)", fill: true, pointRadius: 0, borderWidth: 2 },
        { label: "Azar", data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: dark ? "#374151" : "#d1d5db", borderDash: [5, 4], pointRadius: 0, borderWidth: 1 },
      ]},
      options: {
        scales: { x: { type: "linear", min: 0, max: 1, title: { display: true, text: "Tasa de falsos positivos", color: txtC }, grid: { color: gridC }, ticks: { color: txtC } },
                  y: { min: 0, max: 1, title: { display: true, text: "Tasa de verdaderos positivos", color: txtC }, grid: { color: gridC }, ticks: { color: txtC } } },
        plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 }, color: txtC } } },
      },
    });
  }
}

/* ============ 03 RESULTADOS ============ */
async function renderResultados() {
  viewEl.innerHTML = `<p class="muted">Cargando resultados…</p>`;
  const [d, a] = await Promise.all([api("/api/dashboard"), api("/api/analisis")]);
  const filaPipe = (r, riesgo = false) => `<tr>
    <td><b>${esc(r.proyecto)}</b></td><td class="ctr">${esc(r.dpto)}</td>
    <td>${esc(r.cliente)}</td>
    <td class="num mono">${fmtS(r.monto_total)}</td>
    <td class="num ctr mono">${r.n_pagos}</td>
    <td class="num mono" style="font-weight:700;color:${riesgo ? "var(--red)" : "var(--green)"}">${pct1(r.prob)}</td>
    <td class="ctr">${tagC(r.etiqueta)}</td></tr>`;
  viewEl.innerHTML = `
    <div class="page-head">
      <div><h2>03 · Resultados</h2>
        <p class="page-sub">Indicadores del proceso comercial y análisis predictivo del pipeline activo.</p></div>
    </div>

    <div class="kpi-strip">
      <div><div class="k">Cerradas</div><div class="v">${d.cerradas}</div></div>
      <div><div class="k">Anuladas</div><div class="v">${d.anuladas}</div></div>
      <div><div class="k">En proceso</div><div class="v">${d.en_proceso}</div></div>
      <div><div class="k">TECV conservadora</div><div class="v">${d.tecv_conservadora}%</div></div>
      <div><div class="k">TECV sobre resueltas</div><div class="v">${d.tecv_resueltas}%</div></div>
      <div><div class="k">TPV global</div><div class="v">${d.tpv_global} días</div></div>
      <div><div class="k">Prob. cierre promedio</div><div class="v">${d.prob_promedio != null ? pct1(d.prob_promedio) : "—"}</div></div>
      <div><div class="k">Ventas proyectadas</div><div class="v">${fmtS(d.ventas_proyectadas)}</div></div>
    </div>

    <div class="grid2">
      <div class="block">
        <h3>TECV por proyecto</h3>
        <table class="data">
          <thead><tr><th>Proyecto</th><th class="num">Cerradas</th><th class="num">Anuladas</th><th class="num">En proceso</th><th class="num">Separaciones</th><th class="num">TECV</th></tr></thead>
          <tbody>
            ${d.por_proyecto.map((p) => `<tr>
              <td><b>${p.proyecto}</b></td>
              <td class="num mono">${p.cerradas}</td><td class="num mono">${p.anuladas}</td>
              <td class="num mono">${p.en_proceso}</td><td class="num mono">${p.separaciones}</td>
              <td class="num mono"><b>${p.tecv}%</b></td></tr>`).join("")}
          </tbody>
        </table>
        <h3 style="margin-top:22px">TPV por proyecto (días)</h3>
        <table class="data">
          <thead><tr><th>Proyecto</th><th class="num">TPV</th><th class="num">n</th></tr></thead>
          <tbody>
            ${a.tpv_proyecto.map((r) => `<tr><td>${r.proyecto}</td><td class="num mono">${r.tpv_dias}</td><td class="num mono muted">${r.n}</td></tr>`).join("")}
          </tbody>
        </table>
      </div>
      <div>
        <div class="block">
          <h3>Pipeline — mayor probabilidad de cierre</h3>
          <div class="scroll">
            <table class="data">
              <thead><tr><th>Proy.</th><th class="ctr">Dpto</th><th>Cliente</th><th class="num">Monto</th><th class="ctr">Pagos</th><th class="num">Prob.</th><th class="ctr">Clase</th></tr></thead>
              <tbody>${a.top_pipeline.map((r) => filaPipe(r)).join("") || `<tr><td colspan="7" class="muted">Sin pipeline</td></tr>`}</tbody>
            </table>
          </div>
        </div>
        <div class="block">
          <h3>En riesgo — menor probabilidad de cierre</h3>
          <div class="scroll">
            <table class="data">
              <thead><tr><th>Proy.</th><th class="ctr">Dpto</th><th>Cliente</th><th class="num">Monto</th><th class="ctr">Pagos</th><th class="num">Prob.</th><th class="ctr">Clase</th></tr></thead>
              <tbody>${a.en_riesgo.map((r) => filaPipe(r, true)).join("") || `<tr><td colspan="7" class="muted">Sin casos</td></tr>`}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;
}

/* ============ 04 PREDICCIÓN ============ */
async function renderPrediccion() {
  const hoyMes = new Date().getMonth() + 1, hoyAnio = new Date().getFullYear();
  let anios = "";
  for (let a = hoyAnio + 1; a >= 2020; a--) anios += `<option value="${a}" ${a === hoyAnio ? "selected" : ""}>${a}</option>`;
  viewEl.innerHTML = `
    <div class="page-head">
      <div><h2>04 · Predicción</h2>
        <p class="page-sub">Probabilidad de cierre de una operación con el modelo activo.</p></div>
    </div>
    <div class="block">
      <form id="form-pred">
        <div class="form-grid">
          <div class="field"><label>Proyecto</label>
            <select id="p-proy">${PROYECTOS.map((p) => `<option ${p === "ROMA" ? "selected" : ""}>${p}</option>`).join("")}</select></div>
          <div class="field"><label>Monto total (S/)</label>
            <input id="p-monto" type="number" min="1" required value="250000"></div>
          <div class="field"><label>N° de pagos</label>
            <input id="p-pagos" type="number" min="1" max="120" required value="1"></div>
          <div class="field"><label>Mes de separación</label>
            <select id="p-mes">${MESES.map((m, i) => `<option value="${i + 1}" ${i + 1 === hoyMes ? "selected" : ""}>${m}</option>`).join("")}</select></div>
          <div class="field"><label>Año de separación</label>
            <select id="p-anio">${anios}</select></div>
        </div>
        <button class="btn" type="submit">Predecir</button>
      </form>
      <div class="pred-result" id="pred-out" hidden></div>
    </div>`;
  $("#form-pred").onsubmit = async (ev) => {
    ev.preventDefault();
    const out = $("#pred-out");
    out.hidden = false;
    out.innerHTML = `<p class="muted">Calculando…</p>`;
    try {
      const r = await api("/api/prediccion", { method: "POST", body: JSON.stringify({
        proyecto: $("#p-proy").value, monto_total: +$("#p-monto").value,
        n_pagos: +$("#p-pagos").value, mes_sep: +$("#p-mes").value, anio_sep: +$("#p-anio").value,
      })});
      const color = r.etiqueta === "ALTA" ? "var(--green)" : r.etiqueta === "MEDIA" ? "var(--amber)" : "var(--red)";
      out.innerHTML = `
        <div class="prob-label">Probabilidad de cierre · ${r.modelo}</div>
        <div class="prob-big mono" style="color:${color}">${pct1(r.probabilidad)}</div>
        <div style="margin-top:8px">${tagC(r.etiqueta)} <span class="muted">nivel de cierre</span></div>
        <p class="reco">${esc(r.recomendacion)}</p>
        <h3 style="margin-top:20px;font-size:13px;text-transform:uppercase;letter-spacing:.04em">Factores de la decisión</h3>
        <table class="data" style="max-width:560px;margin-top:8px">
          <thead><tr><th>Factor</th><th class="num">Impacto</th><th>Efecto</th></tr></thead>
          <tbody>
            ${r.contribuciones.map((c) => `<tr>
              <td>${esc(c.factor)}</td>
              <td class="num mono" style="color:${c.impacto >= 0 ? "var(--green)" : "var(--red)"}">${c.impacto >= 0 ? "+" : ""}${c.impacto.toFixed(3)}</td>
              <td class="muted">${c.efecto}</td></tr>`).join("")}
          </tbody>
        </table>`;
    } catch (e) {
      out.innerHTML = `<p class="err">${e.message}</p>`;
    }
  };
}

/* ============ router ============ */
const VIEWS = {
  portada: { render: renderPortada },
  ficha: { render: renderFicha },
  metricas: { render: renderMetricas },
  resultados: { render: renderResultados },
  prediccion: { render: renderPrediccion },
};
async function navigate() {
  const name = location.hash.replace("#", "") || "portada";
  const v = VIEWS[name] || VIEWS.portada;
  document.querySelectorAll(".topnav a").forEach((a) => a.classList.toggle("active", a.dataset.view === name));
  try { await v.render(); } catch (e) { viewEl.innerHTML = `<p class="err">${e.message}</p>`; }
  window.scrollTo(0, 0);
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("#theme-btn");
  if (!b) return;
  applyTheme(isDark() ? "light" : "dark");
  navigate();
});
window.addEventListener("hashchange", navigate);
window.addEventListener("DOMContentLoaded", navigate);
