"use strict";

const DATA = JSON.parse(document.getElementById("payload").textContent);
const PAIRS = DATA.pairs;
const N = PAIRS.length;
const OLS = DATA.ols;
const KAL = DATA.kalman;
const SPUR = new Set(OLS.spurious.map(function (p) { return p[0] + "," + p[1]; }));
const REC = new Map(KAL.records.map(function (r) { return [r.i + "," + r.j, r]; }));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const NS = "http://www.w3.org/2000/svg";

const OLS_METRICS = {
  beta: { label: "Beta", scale: "div", ret: "beta", px: "priceBeta" },
  r2: { label: "R²", scale: "unit", ret: "r2", px: "priceR2" },
  corr: { label: "Correlation", scale: "corr", ret: "corr", px: "priceCorr" },
  p: { label: "Slope p", scale: "p", ret: "pvalue", px: "pricePvalue" },
  adf: { label: "ADF p", scale: "p", ret: null, px: "priceAdf", lock: "r2" },
  dw: { label: "Durbin–Watson", scale: "dw", ret: null, px: "priceDw", lock: "r2" }
};

const KAL_METRICS = {
  adf: { label: "ADF p", scale: "p", field: "adf", note: "Low p rejects a unit root in the tradeable spread. The screen uses 0.05." },
  kpss: { label: "KPSS p", scale: "kpss", field: "kpss", note: "High p fails to reject stationarity. Statsmodels caps the printed p at 0.01 and 0.10." },
  hl: { label: "Half-life", scale: "hl", field: "hl", note: "AR(1) half-life in days. Blank cells have no mean-reverting slope." },
  beta: { label: "Current beta", scale: "div", field: "betaNow", note: "Filtered log hedge ratio on the last day of the window, β at t given t." },
  z: { label: "Current z", scale: "div", field: "z", note: "Latest tradeable spread, in units of its own 250-day standard deviation. Not a trade signal." },
  stab: { label: "Beta stability", scale: "stab", field: "betaStdRel", note: "Standard deviation of filtered beta divided by |mean beta|. The static-beta flag trips below 0.5%." },
  status: { label: "Kalman vs OLS", scale: "status", field: "status", note: "Kalman stationary means ADF p < 0.05 and KPSS p > 0.05. OLS stationary means the static log-spread ADF p < 0.05." }
};

let olsMetric = "r2";
let kalMetric = "adf";
let kalRule = "both";
let kalSort = { key: "adf", dir: 1 };
let selOls = null;
let selKal = null;
const tip = document.getElementById("tip");

function finite(v) { return typeof v === "number" && Number.isFinite(v); }
function fmt(v, sig) {
  if (!finite(v)) return "—";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e-4 && a < 1e5) return String(Number(v.toPrecision(sig || 4)));
  return v.toExponential(2);
}
function fmtP(v) {
  if (!finite(v)) return "—";
  if (v === 0) return "0";
  if (v < 1e-4) return v.toExponential(2);
  return String(Number(v.toPrecision(3)));
}
function fmtDays(v) {
  if (!finite(v)) return "n/a";
  return Number(v.toPrecision(3)) + " days";
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function hex(h) {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function mix(a, b, t) {
  const pa = hex(a);
  const pb = hex(b);
  t = Math.max(0, Math.min(1, t));
  const c = pa.map(function (v, i) { return Math.round(v + (pb[i] - v) * t); });
  return "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
}
function ramp(t, stops) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const span = stops[i][0] - stops[i - 1][0] || 1;
      return mix(stops[i - 1][1], stops[i][1], (t - stops[i - 1][0]) / span);
    }
  }
  return stops[stops.length - 1][1];
}
function prettyStamp(s) {
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/);
  if (!m) return s;
  return Number(m[3]) + " " + MONTHS[Number(m[2]) - 1] + " " + m[1] + ", " + m[4] + ":" + m[5] + " SAST";
}
function shortDate(iso) {
  const p = iso.split("-");
  return MONTHS[Number(p[1]) - 1] + " " + p[0].slice(2);
}

function chip(k, v, accent) {
  const el = document.createElement("div");
  el.className = "chip" + (accent ? " accent" : "");
  const a = document.createElement("span");
  a.className = "k";
  a.textContent = k;
  const b = document.createElement("span");
  b.className = "v";
  b.textContent = v;
  el.append(a, b);
  return el;
}

function fillMeta() {
  const meta = document.getElementById("meta");
  meta.append(
    chip("Last updated", prettyStamp(DATA.generatedAtSast), true),
    chip("Return and spread window", OLS.returnStart + " → " + OLS.returnEnd),
    chip("Sessions", OLS.nReturns + " weekdays"),
    chip("Closes behind the returns", OLS.closeStart + " → " + OLS.closeEnd + " · " + OLS.nCloses),
    chip("Kalman estimation sample", KAL.estStart + " → " + KAL.estEnd + " · " + KAL.estN + ", then frozen"),
    chip("Source", DATA.source),
    chip("Universe", PAIRS.length + " / 28 pairs")
  );
  document.getElementById("foot").textContent =
    "Generated " + prettyStamp(DATA.generatedAtSast) +
    " · window " + OLS.returnStart + " → " + OLS.returnEnd +
    " · " + DATA.source +
    " · Africa/Johannesburg (SAST, UTC+2). Research only.";
  const c = KAL.counts;
  document.getElementById("innov-hl").textContent = fmtDays(c.innovHlMedian);
  document.getElementById("level-hl").textContent = fmtDays(c.levelHlMedian);
  document.getElementById("innov-adf-n").textContent = String(c.innovAdf);
  document.getElementById("kal-sub").textContent =
    "Spread window " + KAL.windowStart + " → " + KAL.windowEnd +
    ". Hedge-ratio noise was estimated on " + KAL.estStart + " → " + KAL.estEnd + " and then frozen. Upper triangle only.";
}

function selectTab(name) {
  const ols = name !== "kalman";
  document.getElementById("tab-ols").setAttribute("aria-selected", ols ? "true" : "false");
  document.getElementById("tab-kalman").setAttribute("aria-selected", ols ? "false" : "true");
  document.getElementById("panel-ols").hidden = !ols;
  document.getElementById("panel-kalman").hidden = ols;
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
}

function valuesOf(matrix, skipDiag) {
  const out = [];
  for (let i = 0; i < N; i++) {
    for (let j = 0; j < N; j++) {
      if (skipDiag && i === j) continue;
      const v = matrix[i][j];
      if (finite(v)) out.push(v);
    }
  }
  return out;
}
function absCap(vals) {
  const xs = vals.map(Math.abs).filter(finite).sort(function (a, b) { return a - b; });
  if (!xs.length) return 1;
  const q = xs[Math.min(xs.length - 1, Math.round((xs.length - 1) * 0.98))];
  return Math.max(q, 1e-6);
}
function colorFor(scale, v, cap) {
  if (!finite(v)) return "#1a2030";
  if (scale === "unit") return ramp(Math.max(0, Math.min(1, v)), [[0, "#1a2230"], [0.5, "#1d4e6a"], [1, "#e0b15e"]]);
  if (scale === "div") {
    const t = (Math.max(-cap, Math.min(cap, v)) / cap + 1) / 2;
    return ramp(t, [[0, "#d16b76"], [0.5, "#1a2230"], [1, "#3dbe9a"]]);
  }
  if (scale === "corr") {
    const t = (Math.max(-1, Math.min(1, v)) + 1) / 2;
    return ramp(t, [[0, "#d16b76"], [0.5, "#1a2230"], [1, "#8eb7ff"]]);
  }
  if (scale === "p") {
    if (v < 0.05) return mix("#1d4a3c", "#8ef0c8", 1 - Math.min(1, v / 0.05));
    return mix("#4a3f38", "#2a2428", Math.min(1, (v - 0.05) / 0.95));
  }
  if (scale === "kpss") {
    if (v > 0.05) return mix("#1d4a3c", "#8ef0c8", Math.min(1, (v - 0.05) / 0.05));
    return mix("#e08a8a", "#3a2a30", Math.min(1, v / 0.05));
  }
  if (scale === "dw") return ramp(Math.min(Math.abs(v - 2) / 2, 1), [[0, "#3dbe9a"], [1, "#d16b76"]]);
  if (scale === "hl") return ramp(Math.min(v, 40) / 40, [[0, "#e0b15e"], [1, "#243044"]]);
  if (scale === "stab") return ramp(Math.min(Math.abs(v) / 0.05, 1), [[0, "#243044"], [1, "#e0a15a"]]);
  return "#1a2230";
}
const STATUS_COLOR = { both: "#3dbe9a", kalman: "#8eb7ff", ols: "#e0b15e", neither: "#2a3344" };
function statusOf(r) {
  if (r.kStat && r.oStat) return "both";
  if (r.kStat) return "kalman";
  if (r.oStat) return "ols";
  return "neither";
}
const STATUS_LABEL = {
  both: "Both stationary",
  kalman: "Kalman only",
  ols: "OLS only",
  neither: "Neither"
};

function legend(el, scale, cap) {
  el.replaceChildren();
  if (scale === "status") {
    const wrap = document.createElement("div");
    wrap.className = "swatches";
    Object.keys(STATUS_LABEL).forEach(function (key) {
      const s = document.createElement("span");
      s.className = "swatch";
      const i = document.createElement("i");
      i.style.background = STATUS_COLOR[key];
      s.append(i, document.createTextNode(STATUS_LABEL[key]));
      wrap.append(s);
    });
    el.append(wrap);
    return;
  }
  const bar = document.createElement("div");
  bar.className = "bar";
  const left = document.createElement("span");
  const right = document.createElement("span");
  left.style.color = "#93a0b4";
  right.style.color = "#93a0b4";
  left.style.fontSize = "12px";
  right.style.fontSize = "12px";
  if (scale === "unit") {
    bar.style.background = "linear-gradient(90deg,#1a2230,#1d4e6a,#e0b15e)";
    left.textContent = "0";
    right.textContent = "1";
  } else if (scale === "div" || scale === "corr") {
    bar.style.background = "linear-gradient(90deg,#d16b76,#1a2230,#" + (scale === "corr" ? "8eb7ff" : "3dbe9a") + ")";
    left.textContent = scale === "corr" ? "−1" : "−" + fmt(cap, 3);
    right.textContent = scale === "corr" ? "+1" : "+" + fmt(cap, 3);
  } else if (scale === "p") {
    bar.style.background = "linear-gradient(90deg,#8ef0c8,#1d4a3c 18%,#4a3f38 22%,#2a2428)";
    left.textContent = "p < 0.05";
    right.textContent = "p near 1";
  } else if (scale === "kpss") {
    bar.style.background = "linear-gradient(90deg,#e08a8a,#3a2a30 40%,#1d4a3c 55%,#8ef0c8)";
    left.textContent = "rejects level-stationarity";
    right.textContent = "p > 0.05";
  } else if (scale === "dw") {
    bar.style.background = "linear-gradient(90deg,#3dbe9a,#d16b76)";
    left.textContent = "DW = 2";
    right.textContent = "DW near 0 or 4";
  } else if (scale === "hl") {
    bar.style.background = "linear-gradient(90deg,#e0b15e,#243044)";
    left.textContent = "short";
    right.textContent = "40d and longer";
  } else if (scale === "stab") {
    bar.style.background = "linear-gradient(90deg,#243044,#e0a15a)";
    left.textContent = "stable";
    right.textContent = "5% of |mean β|";
  }
  el.append(left, bar, right);
}

function buildHeat(table, mode) {
  const head = document.createElement("thead");
  const hr = document.createElement("tr");
  const corner = document.createElement("th");
  corner.className = "row";
  hr.append(corner);
  PAIRS.forEach(function (name) {
    const th = document.createElement("th");
    th.className = "col";
    th.textContent = name;
    hr.append(th);
  });
  head.append(hr);
  const body = document.createElement("tbody");
  for (let i = 0; i < N; i++) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.className = "row";
    th.textContent = PAIRS[i];
    tr.append(th);
    for (let j = 0; j < N; j++) {
      const td = document.createElement("td");
      td.dataset.i = String(i);
      td.dataset.j = String(j);
      if (i === j) td.classList.add("diag");
      else if (mode === "kalman" && i > j) td.classList.add("na");
      else td.classList.add("live");
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(head, body);
  table.addEventListener("mousemove", function (event) {
    const td = event.target.closest("td");
    if (!td || !table.contains(td)) return;
    showTip(event, mode, Number(td.dataset.i), Number(td.dataset.j));
  });
  table.addEventListener("mouseleave", function () { tip.hidden = true; });
  table.addEventListener("click", function (event) {
    const td = event.target.closest("td.live");
    if (!td) return;
    const i = Number(td.dataset.i);
    const j = Number(td.dataset.j);
    if (mode === "ols") selectOls(i, j);
    else selectKal(i, j, true);
  });
}

function showTip(event, mode, i, j) {
  if (i === j) {
    tip.innerHTML = "<div class='pair'>" + esc(PAIRS[i]) + "</div><div>Same pair. The diagonal is not a relationship.</div>";
  } else if (mode === "kalman" && i > j) {
    tip.innerHTML = "<div>Lower triangle is not estimated. See " + esc(PAIRS[j]) + " on " + esc(PAIRS[i]) + " above the diagonal.</div>";
  } else if (mode === "ols") {
    const spec = OLS_METRICS[olsMetric];
    const key = spec.ret || OLS_METRICS[spec.lock].ret;
    const rv = OLS[key][i][j];
    const pv = OLS[spec.px][i][j];
    const spur = SPUR.has(i + "," + j) ? " · likely spurious" : "";
    tip.innerHTML = "<div class='pair'>" + esc(PAIRS[i]) + " on " + esc(PAIRS[j]) + "</div>" +
      "<div>Returns " + esc(OLS_METRICS[spec.ret ? olsMetric : spec.lock].label) + " " + esc(fmt(rv, 4)) + "</div>" +
      "<div>Log price " + esc(spec.label) + " " + esc(fmt(pv, 4)) + esc(spur) + "</div>";
  } else {
    const r = REC.get(i + "," + j);
    const spec = KAL_METRICS[kalMetric];
    const shown = spec.scale === "status" ? STATUS_LABEL[statusOf(r)] : fmt(r[spec.field], 4);
    tip.innerHTML = "<div class='pair'>" + esc(r.y) + " on " + esc(r.x) + "</div><div>" + esc(spec.label) + " " + esc(shown) + "</div>";
  }
  tip.hidden = false;
  const rect = tip.getBoundingClientRect();
  let x = event.clientX + 14;
  let y = event.clientY + 14;
  if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - 14;
  if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - 14;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}

function paintOls() {
  const spec = OLS_METRICS[olsMetric];
  const retKey = spec.ret || OLS_METRICS[spec.lock].ret;
  const retScale = spec.ret ? spec.scale : OLS_METRICS[spec.lock].scale;
  const retCap = absCap(valuesOf(OLS[retKey], true));
  const pxCap = absCap(valuesOf(OLS[spec.px], true));
  paintMatrix(document.getElementById("heat-ret"), function (i, j) {
    if (i === j) return { bg: "", cls: "" };
    return { bg: colorFor(retScale, OLS[retKey][i][j], retCap), cls: "" };
  }, selOls);
  paintMatrix(document.getElementById("heat-px"), function (i, j) {
    if (i === j) return { bg: "", cls: "" };
    return {
      bg: colorFor(spec.scale, OLS[spec.px][i][j], pxCap),
      cls: SPUR.has(i + "," + j) ? "spurious" : ""
    };
  }, selOls);
  legend(document.getElementById("leg-ret"), retScale, retCap);
  legend(document.getElementById("leg-px"), spec.scale, pxCap);
  const note = document.getElementById("ols-metric-note");
  if (spec.lock) {
    note.textContent = spec.label + " is computed on the log-spread residual only. The returns heatmap stays on R². Gold outlines mark likely spurious log-price fits (R² ≥ 0.5 and ADF p ≥ 0.05): " + SPUR.size + " directed cells.";
  } else {
    note.textContent = "Gold outlines on the log-price map mark likely spurious fits (R² ≥ 0.5 and residual ADF p ≥ 0.05): " + SPUR.size + " directed cells. Hover a cell for the value. Click to pin it.";
  }
}

function paintKal() {
  const spec = KAL_METRICS[kalMetric];
  let cap = 1;
  if (spec.scale === "div" || spec.scale === "stab") {
    const vals = KAL.records.map(function (r) { return r[spec.field]; }).filter(finite);
    cap = absCap(vals);
  }
  paintMatrix(document.getElementById("heat-kal"), function (i, j) {
    if (i === j || i > j) return { bg: "", cls: "" };
    const r = REC.get(i + "," + j);
    if (spec.scale === "status") return { bg: STATUS_COLOR[statusOf(r)], cls: "" };
    return { bg: colorFor(spec.scale, r[spec.field], cap), cls: "" };
  }, selKal);
  legend(document.getElementById("leg-kal"), spec.scale, cap);
  document.getElementById("kal-metric-note").textContent = spec.note;
}

function paintMatrix(table, styleOf, selected) {
  const cells = table.querySelectorAll("tbody td");
  cells.forEach(function (td) {
    const i = Number(td.dataset.i);
    const j = Number(td.dataset.j);
    const styled = styleOf(i, j);
    if (styled.bg) td.style.background = styled.bg;
    td.classList.toggle("spurious", styled.cls === "spurious");
    const on = selected && selected.i === i && selected.j === j;
    td.classList.toggle("selected", on);
  });
}

function selectOls(i, j) {
  selOls = { i: i, j: j };
  paintOls();
  const box = document.getElementById("ols-readout");
  const y = PAIRS[i];
  const x = PAIRS[j];
  const spur = SPUR.has(i + "," + j);
  const adf = OLS.priceAdf[i][j];
  let flag = "";
  if (spur) flag = "<span class='flag bad'>Likely spurious</span>";
  else if (finite(adf) && adf < 0.05) flag = "<span class='flag ok'>Residual ADF p &lt; 0.05</span>";
  box.innerHTML =
    "<strong>" + esc(y) + " on " + esc(x) + "</strong>" + flag +
    "<div>Returns · β " + esc(fmt(OLS.beta[i][j], 4)) +
    " · R² " + esc(fmt(OLS.r2[i][j], 4)) +
    " · corr " + esc(fmt(OLS.corr[i][j], 4)) +
    " · slope p " + esc(fmtP(OLS.pvalue[i][j])) + "</div>" +
    "<div>Log price · β " + esc(fmt(OLS.priceBeta[i][j], 4)) +
    " · R² " + esc(fmt(OLS.priceR2[i][j], 4)) +
    " · corr " + esc(fmt(OLS.priceCorr[i][j], 4)) +
    " · slope p " + esc(fmtP(OLS.pricePvalue[i][j])) +
    " · ADF p " + esc(fmtP(adf)) +
    " · DW " + esc(fmt(OLS.priceDw[i][j], 4)) + "</div>" +
    "<div class='dim'>The other direction, " + esc(x) + " on " + esc(y) +
    ", has return β " + esc(fmt(OLS.beta[j][i], 4)) +
    " and log-price β " + esc(fmt(OLS.priceBeta[j][i], 4)) + ".</div>";
  markRows();
}

function ownText(idx) {
  const p = KAL.ownAdf[idx];
  const pass = finite(p) && p < 0.05;
  return PAIRS[idx] + " own-price ADF p " + fmtP(p) + (pass ? " (passes ADF on its own)" : " (not stationary on its own)");
}

function selectKal(i, j, fromClick) {
  const r = REC.get(i + "," + j);
  if (!r) return;
  selKal = { i: i, j: j };
  paintKal();
  const box = document.getElementById("kal-readout");
  const flags = [];
  if (r.degenerate) flags.push("<span class='flag static'>Static beta</span>");
  if (r.weakHedge) flags.push("<span class='flag weak'>Weak hedge</span>");
  if (r.kStat) flags.push("<span class='flag ok'>ADF and KPSS</span>");
  else if (r.kAdf) flags.push("<span class='flag ok'>ADF only</span>");
  let extra = "";
  if (r.weakHedge && finite(KAL.ownAdf[i]) && KAL.ownAdf[i] < 0.05) {
    extra = "<div class='dim'>The hedge stays near zero and " + esc(r.y) + "’s own log price passes ADF, so this stationarity is mostly " + esc(r.y) + " alone.</div>";
  }
  box.innerHTML =
    "<strong>" + esc(r.y) + " on " + esc(r.x) + "</strong> " +
    "<span class='dim'>" + esc(STATUS_LABEL[statusOf(r)]) + "</span>" + flags.join(" ") +
    "<div>Spread · ADF p " + esc(fmtP(r.adf)) +
    " · KPSS p " + esc(fmtP(r.kpss)) +
    " · half-life " + esc(finite(r.hl) ? fmt(r.hl, 3) + " d" : "no mean reversion") +
    " · Hurst " + esc(fmt(r.hurst, 3)) +
    " · z " + esc(fmt(r.z, 3)) + "</div>" +
    "<div>Beta · now " + esc(fmt(r.betaNow, 4)) +
    " · min " + esc(fmt(r.betaMin, 4)) +
    " · max " + esc(fmt(r.betaMax, 4)) +
    " · std " + esc(fmt(r.betaStd, 3)) +
    " · std/|mean| " + esc(fmt(r.betaStdRel, 3)) +
    " · qβ/Ve " + esc(fmt(r.deltaB, 3)) +
    " · EM iterations " + esc(String(r.emIters)) + "</div>" +
    "<div>Static OLS on the same window · β " + esc(fmt(r.olsBeta, 4)) +
    " · R² " + esc(fmt(r.olsR2, 4)) +
    " · residual ADF p " + esc(fmtP(r.olsAdf)) + "</div>" +
    "<div class='dim'>" + esc(ownText(i)) + ". " + esc(ownText(j)) + ".</div>" +
    extra;
  syncSelect(r);
  drawCharts(r);
  markRows();
  if (fromClick) {
    const row = document.querySelector("#table-kal tr[data-key='" + i + "," + j + "']");
    if (row) row.scrollIntoView({ block: "nearest" });
  }
}

function passes(r) { return kalRule === "both" ? r.kStat : r.kAdf; }

function syncSelect(r) {
  const sel = document.getElementById("pair-select");
  const key = r.i + "," + r.j;
  let found = false;
  for (let i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value === key) { sel.selectedIndex = i; found = true; break; }
  }
  if (!found) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = r.y + " / " + r.x + " (outside the current filter)";
    sel.insertBefore(opt, sel.firstChild);
    sel.selectedIndex = 0;
  }
}

function renderKalTable() {
  const q = document.getElementById("pair-filter").value.trim().toUpperCase();
  let rows = KAL.records.filter(passes);
  if (q) {
    rows = rows.filter(function (r) { return (r.y + r.x).toUpperCase().indexOf(q) !== -1 || (r.y + " " + r.x).toUpperCase().indexOf(q) !== -1; });
  }
  const key = kalSort.key;
  const dir = kalSort.dir;
  function flagScore(r) { return (r.degenerate ? 2 : 0) + (r.weakHedge ? 1 : 0); }
  rows.sort(function (a, b) {
    if (key === "flags") return (flagScore(a) - flagScore(b)) * dir || (a.adf - b.adf);
    const av = key === "y" ? a.y + a.x : a[key];
    const bv = key === "y" ? b.y + b.x : b[key];
    const af = finite(av);
    const bf = finite(bv);
    if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir;
    if (af !== bf) return af ? -1 : 1;
    if (av === bv) return a.adf - b.adf;
    return (av < bv ? -1 : 1) * dir;
  });
  const title = document.getElementById("kal-table-title");
  title.textContent = (kalRule === "both" ? "ADF and KPSS" : "ADF only") + " · " + rows.length + " pairs";
  const table = document.getElementById("table-kal");
  table.replaceChildren();
  const cols = [
    ["y", "Pair", true],
    ["adf", "ADF p", false],
    ["kpss", "KPSS p", false],
    ["hl", "Half-life", false],
    ["hurst", "Hurst", false],
    ["betaNow", "Beta", false],
    ["betaStdRel", "β stability", false],
    ["z", "z", false],
    ["olsR2", "OLS R²", false],
    ["olsAdf", "OLS ADF", false],
    ["flags", "Flags", true]
  ];
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  cols.forEach(function (col) {
    const th = document.createElement("th");
    if (col[2]) th.className = "left";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = col[1] + (kalSort.key === col[0] ? (kalSort.dir > 0 ? " ↑" : " ↓") : "");
    btn.addEventListener("click", function () {
      if (kalSort.key === col[0]) kalSort.dir *= -1;
      else kalSort = { key: col[0], dir: col[0] === "y" ? 1 : 1 };
      renderKalTable();
    });
    th.append(btn);
    hr.append(th);
  });
  thead.append(hr);
  const tb = document.createElement("tbody");
  rows.forEach(function (r) {
    const tr = document.createElement("tr");
    tr.dataset.key = r.i + "," + r.j;
    if (selKal && selKal.i === r.i && selKal.j === r.j) tr.className = "on";
    tr.addEventListener("click", function () { selectKal(r.i, r.j, false); });
    function td(text, left, extreme) {
      const cell = document.createElement("td");
      if (left) cell.className = "left";
      if (extreme) cell.classList.add("extreme");
      cell.textContent = text;
      return cell;
    }
    const pair = document.createElement("td");
    pair.className = "left pair";
    pair.textContent = r.y + " / " + r.x;
    tr.append(pair);
    tr.append(td(fmtP(r.adf), false, false));
    tr.append(td(fmtP(r.kpss), false, false));
    tr.append(td(finite(r.hl) ? fmt(r.hl, 3) + " d" : "—", false, false));
    tr.append(td(fmt(r.hurst, 3), false, false));
    tr.append(td(fmt(r.betaNow, 4), false, false));
    tr.append(td(fmt(r.betaStdRel, 3), false, false));
    tr.append(td(fmt(r.z, 3), false, finite(r.z) && Math.abs(r.z) >= 2));
    tr.append(td(fmt(r.olsR2, 3), false, false));
    tr.append(td(fmtP(r.olsAdf), false, false));
    const flags = document.createElement("td");
    flags.className = "left";
    if (r.degenerate) {
      const s = document.createElement("span");
      s.className = "flag static";
      s.textContent = "Static β";
      flags.append(s);
    }
    if (r.weakHedge) {
      const s = document.createElement("span");
      s.className = "flag weak";
      s.textContent = "Weak hedge";
      flags.append(s);
    }
    if (!r.degenerate && !r.weakHedge) flags.textContent = "—";
    tr.append(flags);
    tb.append(tr);
  });
  table.append(thead, tb);
  fillPairSelect();
}

function fillPairSelect() {
  const sel = document.getElementById("pair-select");
  const current = selKal ? selKal.i + "," + selKal.j : "";
  const rows = KAL.records.filter(passes).slice().sort(function (a, b) { return a.adf - b.adf; });
  sel.replaceChildren();
  rows.forEach(function (r) {
    const opt = document.createElement("option");
    opt.value = r.i + "," + r.j;
    opt.textContent = r.y + " / " + r.x + " · ADF " + fmtP(r.adf);
    sel.append(opt);
  });
  if (current && REC.has(current)) {
    let found = false;
    for (let i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === current) { sel.selectedIndex = i; found = true; break; }
    }
    if (!found) {
      const r = REC.get(current);
      const opt = document.createElement("option");
      opt.value = current;
      opt.textContent = r.y + " / " + r.x + " (outside the current filter)";
      sel.insertBefore(opt, sel.firstChild);
      sel.selectedIndex = 0;
    }
  }
}

function markRows() {
  document.querySelectorAll("#table-ret tbody tr, #table-px tbody tr, #table-kal tbody tr").forEach(function (tr) {
    const key = tr.dataset.key;
    const onOls = selOls && key === selOls.i + "," + selOls.j;
    const onKal = selKal && key === selKal.i + "," + selKal.j;
    tr.classList.toggle("on", onOls || onKal);
  });
}

function renderRank(table, rows, price) {
  table.replaceChildren();
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  const heads = price
    ? ["Pair", "R²", "Corr", "β Y←X", "β X←Y", "ADF p", "DW", "Flag"]
    : ["Pair", "R²", "Corr", "β Y←X", "β X←Y"];
  heads.forEach(function (name, idx) {
    const th = document.createElement("th");
    if (idx === 0 || (price && idx === heads.length - 1)) th.className = "left";
    th.textContent = name;
    hr.append(th);
  });
  thead.append(hr);
  const tb = document.createElement("tbody");
  rows.forEach(function (r) {
    const tr = document.createElement("tr");
    tr.dataset.key = r.i + "," + r.j;
    tr.addEventListener("click", function () { selectOls(r.i, r.j); });
    function cell(text, left) {
      const td = document.createElement("td");
      if (left) td.className = "left";
      td.textContent = text;
      return td;
    }
    const pair = document.createElement("td");
    pair.className = "left pair";
    pair.textContent = r.y + " / " + r.x;
    tr.append(pair);
    tr.append(cell(fmt(r.r2, 4), false));
    tr.append(cell(fmt(r.corr, 4), false));
    tr.append(cell(fmt(r.betaYX, 4), false));
    tr.append(cell(fmt(r.betaXY, 4), false));
    if (price) {
      tr.append(cell(fmtP(r.adfP), false));
      tr.append(cell(fmt(r.dw, 4), false));
      const flag = document.createElement("td");
      flag.className = "left";
      if (r.spurious) {
        const s = document.createElement("span");
        s.className = "flag bad";
        s.textContent = "Spurious";
        flag.append(s);
      } else if (r.cointegrated) {
        const s = document.createElement("span");
        s.className = "flag ok";
        s.textContent = "ADF < 0.05";
        flag.append(s);
      } else flag.textContent = "—";
      tr.append(flag);
    }
    tb.append(tr);
  });
  table.append(thead, tb);
}

function statCard(k, v, s) {
  const el = document.createElement("div");
  el.className = "stat";
  const a = document.createElement("div");
  a.className = "k";
  a.textContent = k;
  const b = document.createElement("div");
  b.className = "v";
  b.textContent = v;
  const c = document.createElement("div");
  c.className = "s";
  c.textContent = s;
  el.append(a, b, c);
  return el;
}

function fillCards() {
  const c = KAL.counts;
  const main = document.getElementById("cards-main");
  const cmp = document.getElementById("cards-cmp");
  const flag = document.getElementById("cards-flag");
  main.append(
    statCard("Pairs tested", String(c.nPairs), "Upper triangle, one orientation each"),
    statCard("Kalman stationary", String(c.kalmanStationary), "ADF p < 0.05 and KPSS p > 0.05"),
    statCard("Kalman ADF only", String(c.kalmanAdfOnly), "ADF p < 0.05, KPSS not required"),
    statCard("Median half-life", finite(c.stationaryHlMedian) ? fmt(c.stationaryHlMedian, 3) + " d" : "—", "Among ADF-and-KPSS pairs that mean-revert")
  );
  cmp.append(
    statCard("Both", String(c.bothStat), "Kalman stationary and OLS ADF"),
    statCard("Kalman only", String(c.kalmanOnlyStat), "Moving hedge, OLS residual does not pass"),
    statCard("OLS only", String(c.olsOnlyStat), "Static log spread passes, Kalman spread does not"),
    statCard("OLS ADF and R² ≥ 0.5", String(c.olsAdfR2), "OLS residual ADF p < 0.05 with a high R²")
  );
  flag.append(
    statCard("Static beta", String(c.degenerate), "Hedge barely moved over the window"),
    statCard("Static and stationary", String(c.degenerateStationary), "Stationary with an almost fixed beta"),
    statCard("Weak hedge and stationary", String(c.weakHedgeStationary), "|β| < 0.1 for the whole window"),
    statCard("OLS residual ADF", String(c.olsAdf), "Static log spread, ADF p < 0.05")
  );
}

function svgEl(name, attrs) {
  const node = document.createElementNS(NS, name);
  Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
  return node;
}

function drawChart(svg, values, opt) {
  const W = 720;
  const H = 280;
  const pad = { l: 54, r: 16, t: 16, b: 32 };
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.replaceChildren();
  const finiteIdx = [];
  values.forEach(function (v, i) { if (finite(v)) finiteIdx.push([i, v]); });
  if (finiteIdx.length < 2) {
    svg.append(svgEl("text", { x: "24", y: "40", fill: "#93a0b4", "font-size": "14" }));
    svg.lastChild.textContent = "No series for this pair.";
    return;
  }
  let lo = Math.min.apply(null, finiteIdx.map(function (d) { return d[1]; }));
  let hi = Math.max.apply(null, finiteIdx.map(function (d) { return d[1]; }));
  (opt.refs || []).forEach(function (ref) {
    if (finite(ref.value)) { lo = Math.min(lo, ref.value); hi = Math.max(hi, ref.value); }
  });
  if (!(hi > lo)) { lo -= 1; hi += 1; }
  const padY = (hi - lo) * 0.08;
  lo -= padY;
  hi += padY;
  const innerW = W - pad.l - pad.r;
  const innerH = H - pad.t - pad.b;
  const xOf = function (i) { return pad.l + (i / (values.length - 1)) * innerW; };
  const yOf = function (v) { return pad.t + (hi - v) / (hi - lo) * innerH; };
  for (let t = 0; t <= 4; t++) {
    const v = lo + (hi - lo) * (1 - t / 4);
    const y = yOf(v);
    svg.append(svgEl("line", { x1: pad.l, x2: W - pad.r, y1: y, y2: y, stroke: "#243044", "stroke-width": "1" }));
    const label = svgEl("text", { x: "6", y: y + 4, fill: "#7e8ba0", "font-size": "11", "font-family": "ui-monospace, monospace" });
    label.textContent = fmt(v, 3);
    svg.append(label);
  }
  const tickN = 4;
  for (let t = 0; t <= tickN; t++) {
    const i = Math.round((values.length - 1) * t / tickN);
    const label = svgEl("text", {
      x: xOf(i),
      y: H - 10,
      fill: "#7e8ba0",
      "font-size": "11",
      "text-anchor": t === 0 ? "start" : t === tickN ? "end" : "middle",
      "font-family": "ui-monospace, monospace"
    });
    label.textContent = shortDate(KAL.windowDates[i]);
    svg.append(label);
  }
  (opt.refs || []).forEach(function (ref) {
    if (!finite(ref.value)) return;
    const y = yOf(ref.value);
    svg.append(svgEl("line", {
      x1: pad.l, x2: W - pad.r, y1: y, y2: y,
      stroke: ref.color, "stroke-width": "1", "stroke-dasharray": ref.dash || "4 4"
    }));
    if (ref.label) {
      const label = svgEl("text", { x: W - pad.r - 4, y: y - 4, fill: ref.color, "font-size": "11", "text-anchor": "end" });
      label.textContent = ref.label;
      svg.append(label);
    }
  });
  let d = "";
  let pen = false;
  values.forEach(function (v, i) {
    if (!finite(v)) { pen = false; return; }
    d += (pen ? "L" : "M") + xOf(i).toFixed(1) + "," + yOf(v).toFixed(1);
    pen = true;
  });
  svg.append(svgEl("path", { d: d, fill: "none", stroke: opt.color, "stroke-width": "1.7", "stroke-linejoin": "round", "stroke-linecap": "round" }));
}

function drawCharts(r) {
  drawChart(document.getElementById("chart-beta"), r.betaSeries, {
    color: "#e0b15e",
    refs: [{ value: r.olsBeta, color: "#9aa6b8", label: "OLS " + fmt(r.olsBeta, 3) }]
  });
  drawChart(document.getElementById("chart-z"), r.zSeries, {
    color: "#8eb7ff",
    refs: [
      { value: 2, color: "#e08a8a", label: "+2" },
      { value: -2, color: "#e08a8a", label: "−2" },
      { value: 0, color: "#66758a", dash: "2 3", label: "" }
    ]
  });
}

function bind() {
  document.getElementById("tab-ols").addEventListener("click", function () { selectTab("ols"); });
  document.getElementById("tab-kalman").addEventListener("click", function () { selectTab("kalman"); });
  document.getElementById("ols-metrics").addEventListener("click", function (event) {
    const btn = event.target.closest("button[data-metric]");
    if (!btn) return;
    olsMetric = btn.dataset.metric;
    document.querySelectorAll("#ols-metrics button").forEach(function (b) {
      b.setAttribute("aria-checked", b === btn ? "true" : "false");
    });
    paintOls();
  });
  document.getElementById("kal-metrics").addEventListener("click", function (event) {
    const btn = event.target.closest("button[data-metric]");
    if (!btn) return;
    kalMetric = btn.dataset.metric;
    document.querySelectorAll("#kal-metrics button").forEach(function (b) {
      b.setAttribute("aria-checked", b === btn ? "true" : "false");
    });
    paintKal();
  });
  document.getElementById("rule-both").addEventListener("click", function () { setRule("both"); });
  document.getElementById("rule-adf").addEventListener("click", function () { setRule("adf"); });
  document.getElementById("pair-filter").addEventListener("input", renderKalTable);
  document.getElementById("pair-select").addEventListener("change", function (event) {
    const parts = event.target.value.split(",");
    selectKal(Number(parts[0]), Number(parts[1]), false);
  });
  window.addEventListener("hashchange", function () {
    selectTab(location.hash === "#kalman" ? "kalman" : "ols");
  });
}

function setRule(rule) {
  kalRule = rule;
  document.getElementById("rule-both").setAttribute("aria-pressed", rule === "both" ? "true" : "false");
  document.getElementById("rule-adf").setAttribute("aria-pressed", rule === "adf" ? "true" : "false");
  if (selKal) {
    const r = REC.get(selKal.i + "," + selKal.j);
    if (r && !passes(r)) {
      const next = KAL.records.filter(passes).slice().sort(function (a, b) { return a.adf - b.adf; })[0];
      if (next) selKal = { i: next.i, j: next.j };
    }
  }
  renderKalTable();
  if (selKal) selectKal(selKal.i, selKal.j, false);
}

function init() {
  if (N !== 28 || KAL.records.length !== 378) {
    throw new Error("Dashboard payload is not the 28-pair universe.");
  }
  fillMeta();
  fillCards();
  buildHeat(document.getElementById("heat-ret"), "ols");
  buildHeat(document.getElementById("heat-px"), "ols");
  buildHeat(document.getElementById("heat-kal"), "kalman");
  renderRank(document.getElementById("table-ret"), OLS.topReturns, false);
  renderRank(document.getElementById("table-px"), OLS.topPrices, true);
  const top = OLS.topReturns[0];
  selectOls(top.i, top.j);
  const first = KAL.records.filter(function (r) { return r.kStat; }).slice().sort(function (a, b) { return a.adf - b.adf; })[0]
    || KAL.records.slice().sort(function (a, b) { return a.adf - b.adf; })[0];
  renderKalTable();
  selectKal(first.i, first.j, false);
  bind();
  if (location.hash === "#kalman") selectTab("kalman");
}

init();
