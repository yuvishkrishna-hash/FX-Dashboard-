"use strict";

const DATA = JSON.parse(document.getElementById("payload").textContent);
const FX_READY = !!(DATA.pairs && DATA.pairs.length === 28 && DATA.ols && DATA.kalman && DATA.kalman.records && DATA.kalman.records.length === 378);
const PAIRS = FX_READY ? DATA.pairs : [];
const N = PAIRS.length;
const OLS = FX_READY ? DATA.ols : null;
const KAL = FX_READY ? DATA.kalman : null;
const SCREEN = FX_READY ? DATA.screen : null;
const SPUR = FX_READY ? new Set(OLS.spurious.map(function (p) { return p[0] + "," + p[1]; })) : new Set();
const REC = FX_READY ? new Map(KAL.records.map(function (r) { return [r.i + "," + r.j, r]; })) : new Map();
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
  const asof = document.getElementById("asof");
  if (asof) {
    asof.textContent = "Data as of " + prettyStamp(DATA.generatedAtSast) +
      " · window " + OLS.returnStart + " → " + OLS.returnEnd +
      " · " + DATA.source;
  }
  document.getElementById("foot").textContent =
    "Generated " + prettyStamp(DATA.generatedAtSast) +
    " · window " + OLS.returnStart + " → " + OLS.returnEnd +
    " · " + DATA.source +
    " · Africa/Johannesburg (SAST, UTC+2). Research only, not trading advice.";
  const stamp = parseSast(DATA.generatedAtSast);
  const staleDays = (SCREEN && SCREEN.rules && SCREEN.rules.staleDays) || 3;
  if (stamp && Date.now() - stamp.getTime() > staleDays * 86400000) {
    document.getElementById("stale").hidden = false;
  }
  const c = KAL.counts;
  document.getElementById("innov-hl").textContent = fmtDays(c.innovHlMedian);
  document.getElementById("level-hl").textContent = fmtDays(c.levelHlMedian);
  document.getElementById("innov-adf-n").textContent = String(c.innovAdf);
  document.getElementById("kal-sub").textContent =
    "Spread window " + KAL.windowStart + " → " + KAL.windowEnd +
    ". Hedge-ratio noise was estimated on " + KAL.estStart + " → " + KAL.estEnd + " and then frozen. Upper triangle only.";
}

function parseSast(s) {
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/);
  if (!m) return null;
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 2, +m[5]));
}

let returnHash = "#opportunities";

function canonicalRecord(i, j) {
  if (i === j) return null;
  if (i > j) { const swap = i; i = j; j = swap; }
  return REC.get(i + "," + j) || null;
}

function pairHash(r) { return "#pair=" + r.y + "_" + r.x; }

function findRecord(token) {
  const parts = String(token || "").split("_");
  if (parts.length !== 2) return null;
  const a = PAIRS.indexOf(parts[0]);
  const b = PAIRS.indexOf(parts[1]);
  if (a < 0 || b < 0) return null;
  return canonicalRecord(a, b);
}

function showPanels(which) {
  document.getElementById("panel-opp").hidden = which !== "opp";
  document.getElementById("panel-full").hidden = which !== "full";
  document.getElementById("panel-pair").hidden = which !== "pair";
  hideAssetRoot();
  setAssetNav("fx");
  restoreFxChrome();
  const more = document.getElementById("more-link");
  if (more) {
    more.hidden = which === "full";
    more.href = "#more";
  }
}

function selectSub(name) {
  const ols = name !== "kalman";
  document.getElementById("tab-ols").setAttribute("aria-selected", ols ? "true" : "false");
  document.getElementById("tab-kalman").setAttribute("aria-selected", ols ? "false" : "true");
  document.getElementById("panel-ols").hidden = !ols;
  document.getElementById("panel-kalman").hidden = ols;
}

function selectTab(name) {
  selectSub(name);
  showPanels("full");
  const hash = name === "kalman" ? "#full-kalman" : "#full-ols";
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

function route() {
  const hash = location.hash || "#opportunities";
  if (hash === "#commodities" || hash === "#commodities-more" || hash.indexOf("#c-pair=") === 0) {
    showAsset("commodities", hash);
    return;
  }
  if (hash === "#stocks" || hash === "#stocks-more" || hash.indexOf("#s-pair=") === 0) {
    showAsset("stocks", hash);
    return;
  }
  if (!FX_READY) {
    hideAssetRoot();
    setAssetNav("fx");
    document.getElementById("panel-opp").hidden = true;
    document.getElementById("panel-full").hidden = true;
    document.getElementById("panel-pair").hidden = true;
    const more = document.getElementById("more-link");
    if (more) more.hidden = true;
    const err = document.getElementById("fx-error");
    err.hidden = false;
    err.textContent = DATA.fxError || "FX data is not in this snapshot.";
    return;
  }
  if (hash.indexOf("#pair=") === 0) {
    const rec = findRecord(decodeURIComponent(hash.slice(6)));
    if (!rec) {
      history.replaceState(null, "", "#opportunities");
      showPanels("opp");
      return;
    }
    showPanels("pair");
    renderPair(rec);
    window.scrollTo(0, 0);
    return;
  }
  if (hash === "#kalman" || hash === "#full-kalman") {
    selectSub("kalman");
    showPanels("full");
    return;
  }
  if (hash === "#ols" || hash === "#full-ols" || hash === "#full" || hash === "#more") {
    selectSub("ols");
    showPanels("full");
    return;
  }
  showPanels("opp");
}

function openPair(i, j) {
  const rec = canonicalRecord(i, j);
  if (!rec) return;
  if (location.hash.indexOf("#pair=") !== 0) returnHash = location.hash || "#opportunities";
  location.hash = pairHash(rec);
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
    openPair(i, j);
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
  if (opt.band) {
    opt.band.upper.forEach(function (v) { if (finite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    opt.band.lower.forEach(function (v) { if (finite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
  }
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
    const axis = opt.dates || (KAL && KAL.windowDates) || [];
    label.textContent = axis[i] ? shortDate(axis[i]) : "";
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
  if (opt.band) {
    let area = "";
    let started = false;
    opt.band.upper.forEach(function (v, i) {
      if (!finite(v) || !finite(opt.band.lower[i])) { started = false; return; }
      area += (started ? "L" : "M") + xOf(i).toFixed(1) + "," + yOf(v).toFixed(1);
      started = true;
    });
    for (let i = opt.band.lower.length - 1; i >= 0; i--) {
      const v = opt.band.lower[i];
      if (!finite(v) || !finite(opt.band.upper[i])) continue;
      area += "L" + xOf(i).toFixed(1) + "," + yOf(v).toFixed(1);
    }
    if (area) {
      svg.append(svgEl("path", { d: area + "Z", fill: "rgba(224,177,94,0.16)", stroke: "none" }));
    }
  }
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

function dirText(row) {
  const name = row.direction === "rich" ? "Spread rich" : row.direction === "cheap" ? "Spread cheap" : "Flat";
  return fmt(row.z, 3) + " · " + name;
}

function rollText(row) {
  if (row.rollPass) return "Yes";
  const bits = [];
  if (!row.rollStat) bits.push("not stationary");
  if (!finite(row.rollZNow) || Math.abs(row.rollZNow) < 2) bits.push("|z| " + fmt(row.rollZNow, 3));
  return "No · " + (bits.join(", ") || "no");
}

function renderScreenTable(table, rows) {
  table.replaceChildren();
  if (!rows.length) return;
  const heads = ["Pair", "Kalman z", "Half-life", "Beta", "Rolling agrees"];
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  heads.forEach(function (name, idx) {
    const th = document.createElement("th");
    if (idx === 0 || idx === 4) th.className = "left";
    th.textContent = name;
    hr.append(th);
  });
  thead.append(hr);
  const tb = document.createElement("tbody");
  rows.forEach(function (row) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", function () { openPair(row.i, row.j); });
    const pair = document.createElement("td");
    pair.className = "left pair";
    pair.textContent = row.y + " / " + row.x;
    tr.append(pair);
    function cell(text, left) {
      const td = document.createElement("td");
      if (left) td.className = "left";
      td.textContent = text;
      return td;
    }
    tr.append(cell(fmt(row.z, 3), false));
    tr.append(cell(finite(row.hl) ? fmt(row.hl, 3) : "—", false));
    tr.append(cell(fmt(row.betaNow, 4), false));
    tr.append(cell(row.rollingAgrees ? "Yes" : "No", true));
    tb.append(tr);
  });
  table.append(thead, tb);
}

function renderConcentration() {
  const box = document.getElementById("concentration");
  box.replaceChildren();
  if (!SCREEN.nOpportunities) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "No opportunities on this snapshot, so there is no shared-currency concentration to report.";
    box.append(note);
    return;
  }
  const shared = (SCREEN.currencies || []).filter(function (item) { return item.count >= 2; });
  if (!shared.length) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "No currency appears in more than one opportunity.";
    box.append(note);
    return;
  }
  const conc = document.createElement("div");
  conc.className = "conc";
  shared.forEach(function (item) {
    const el = document.createElement("div");
    el.className = "warn";
    el.textContent = item.currency + " appears in " + item.count + " of " + item.n;
    conc.append(el);
  });
  const groups = document.createElement("div");
  groups.className = "groups";
  shared.forEach(function (item) {
    const line = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = item.currency;
    line.append(name, document.createTextNode(" · " + item.pairs.join(", ")));
    groups.append(line);
  });
  box.append(conc, groups);
}

function renderScreen() {
  const opps = SCREEN.opportunities || [];
  const watch = SCREEN.watchlist || [];
  document.getElementById("opp-title").textContent = "Opportunities · " + opps.length;
  document.getElementById("watch-title").textContent = "Watchlist · " + watch.length;
  document.getElementById("opp-empty").hidden = opps.length > 0;
  document.getElementById("watch-empty").hidden = watch.length > 0;
  renderScreenTable(document.getElementById("table-opp"), opps);
  renderScreenTable(document.getElementById("table-watch"), watch);
  renderConcentration();
}

function zBands() {
  return [
    { value: 2, color: "#e08a8a", label: "+2" },
    { value: 1, color: "#8d735c", label: "+1" },
    { value: -1, color: "#8d735c", label: "−1" },
    { value: -2, color: "#e08a8a", label: "−2" },
    { value: 0, color: "#66758a", dash: "2 3", label: "" }
  ];
}

function renderPair(r) {
  document.getElementById("pair-title").textContent = r.y + " / " + r.x;
  document.getElementById("pair-orient").textContent =
    "Kalman spread z-score. Lines at 0 and ±2. Research only, not trading advice.";
  drawChart(document.getElementById("chart-pair-z"), r.zSeries, {
    color: "#8eb7ff",
    refs: [
      { value: 2, color: "#e08a8a", label: "+2" },
      { value: -2, color: "#e08a8a", label: "−2" },
      { value: 0, color: "#66758a", dash: "2 3", label: "0" }
    ]
  });
}

function bind() {
  const back = document.getElementById("pair-back");
  if (back) {
    back.addEventListener("click", function (event) {
      event.preventDefault();
      location.hash = returnHash && returnHash.indexOf("#pair=") !== 0 ? returnHash : "#opportunities";
    });
  }
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
  document.getElementById("asset-sector").addEventListener("change", function (event) {
    assetSector = event.target.value || "All";
    renderAssetAll(assetBlock(assetKey));
  });
  document.getElementById("asset-filter").addEventListener("input", function () {
    renderAssetAll(assetBlock(assetKey));
  });
  window.addEventListener("hashchange", route);
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

let fxChrome = null;
let assetKey = "commodities";
let assetSort = { key: "absz", dir: -1 };
let assetSector = "All";
let assetHomeKey = "";

function hideAssetRoot() {
  const root = document.getElementById("asset-root");
  if (root) root.hidden = true;
}

function setAssetNav(key) {
  ["fx", "commodities", "stocks"].forEach(function (name) {
    const el = document.getElementById("nav-" + name);
    if (!el) return;
    if (name === key) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
}

function staleLimit() {
  return (SCREEN && SCREEN.rules && SCREEN.rules.staleDays) || 3;
}

function applyStale(stamp) {
  const stale = document.getElementById("stale");
  if (!stale) return;
  const parsed = stamp ? parseSast(stamp) : null;
  stale.hidden = !(parsed && Date.now() - parsed.getTime() > staleLimit() * 86400000);
}

function snapshotFxChrome() {
  fxChrome = {
    eyebrow: document.querySelector(".eyebrow").textContent,
    h1: document.querySelector("h1").textContent,
    title: document.title,
    asof: document.getElementById("asof").textContent,
    foot: document.getElementById("foot").textContent
  };
}

function restoreFxChrome() {
  if (!fxChrome) return;
  document.querySelector(".eyebrow").textContent = fxChrome.eyebrow;
  document.querySelector("h1").textContent = fxChrome.h1;
  document.title = fxChrome.title;
  document.getElementById("asof").textContent = fxChrome.asof;
  document.getElementById("foot").textContent = fxChrome.foot;
  applyStale(DATA.generatedAtSast);
}

function assetBlock(key) {
  const block = DATA[key];
  if (!block) {
    return {
      error: "This snapshot has no " + key + " data.",
      pairs: [],
      dropped: [],
      dateSets: [],
      warnings: []
    };
  }
  return block;
}

function assetHome(key) {
  return key === "stocks" ? "#stocks" : "#commodities";
}

function assetLines(row) {
  if (assetKey === "commodities") return [row.yName + " / " + row.xName, row.y + " / " + row.x];
  return [row.y + " / " + row.x, (row.yName || "") + " / " + (row.xName || "")];
}

function hideFxPanels() {
  document.getElementById("panel-opp").hidden = true;
  document.getElementById("panel-full").hidden = true;
  document.getElementById("panel-pair").hidden = true;
}

function byAbsZ(rows) {
  return rows.slice().sort(function (a, b) {
    const av = finite(a.z) ? Math.abs(a.z) : -1;
    const bv = finite(b.z) ? Math.abs(b.z) : -1;
    return bv - av;
  });
}

function pairCell(row) {
  const td = document.createElement("td");
  td.className = "left pair";
  const lines = assetLines(row);
  const main = document.createElement("span");
  main.textContent = lines[0];
  td.append(main);
  if (lines[1]) {
    const sub = document.createElement("span");
    sub.className = "subname";
    sub.textContent = lines[1];
    td.append(sub);
  }
  return td;
}

function textCell(text, left) {
  const td = document.createElement("td");
  if (left) td.className = "left";
  td.textContent = text;
  return td;
}

function renderAssetScreenTable(table, rows) {
  table.replaceChildren();
  if (!rows.length) return;
  const heads = ["Pair", "Kalman z", "Half-life", "Beta", "Rolling agrees"];
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  heads.forEach(function (name, idx) {
    const th = document.createElement("th");
    if (idx === 0 || idx === 4) th.className = "left";
    th.textContent = name;
    hr.append(th);
  });
  thead.append(hr);
  const tb = document.createElement("tbody");
  rows.forEach(function (row) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", function () { openAssetPair(row); });
    tr.append(pairCell(row));
    tr.append(textCell(fmt(row.z, 3), false));
    tr.append(textCell(finite(row.hl) ? fmt(row.hl, 3) : "—", false));
    tr.append(textCell(fmt(row.betaNow, 4), false));
    tr.append(textCell(row.rollingAgrees ? "Yes" : "No", true));
    tb.append(tr);
  });
  table.append(thead, tb);
}

function assetRank(row, key) {
  if (key === "pair") return (assetKey === "commodities" ? (row.yName || "") + (row.xName || "") : row.y + row.x).toLowerCase();
  if (key === "name") return ((row.yName || "") + " " + (row.xName || "")).toLowerCase();
  if (key === "absz") return finite(row.z) ? Math.abs(row.z) : null;
  if (key === "status") return row.status === "opportunity" ? 3 : row.status === "watchlist" ? 2 : 1;
  if (key === "agrees") return row.rollingAgrees ? 1 : 0;
  if (key === "why") return row.why || "";
  if (key === "sector") return row.sector || "";
  const value = row[key];
  return finite(value) ? value : null;
}

function sortAssetRows(rows) {
  const key = assetSort.key;
  const dir = assetSort.dir;
  return rows.slice().sort(function (a, b) {
    const av = assetRank(a, key);
    const bv = assetRank(b, key);
    const aMiss = av === null || av === "";
    const bMiss = bv === null || bv === "";
    if (aMiss && bMiss) return 0;
    if (aMiss) return 1;
    if (bMiss) return -1;
    if (av < bv) return -dir;
    if (av > bv) return dir;
    return 0;
  });
}

function defaultAssetDir(key) {
  if (key === "pair" || key === "name" || key === "sector" || key === "why") return 1;
  return -1;
}

function sortHeader(label, key, left) {
  const th = document.createElement("th");
  if (left) th.className = "left";
  const btn = document.createElement("button");
  btn.type = "button";
  const mark = assetSort.key === key ? (assetSort.dir < 0 ? " ↓" : " ↑") : "";
  btn.textContent = label + mark;
  btn.addEventListener("click", function () {
    if (assetSort.key === key) assetSort.dir = -assetSort.dir;
    else assetSort = { key: key, dir: defaultAssetDir(key) };
    renderAssetAll(assetBlock(assetKey));
  });
  th.append(btn);
  return th;
}

function statusText(row) {
  if (row.status === "opportunity") return "Opportunity";
  if (row.status === "watchlist") return "Watchlist";
  return "Fails";
}

function renderAssetAll(block) {
  const table = document.getElementById("table-asset-all");
  const rows = block.pairs || [];
  document.getElementById("asset-all-title").textContent = "All tested pairs · " + rows.length;
  const warn = (block.warnings || []).join(" ");
  document.getElementById("asset-all-sub").textContent =
    "Every pair that was tested, including the ones that fail a gate." + (warn ? " " + warn : "");
  const q = document.getElementById("asset-filter").value.trim().toLowerCase();
  const filtered = rows.filter(function (row) {
    if (assetKey === "stocks" && assetSector !== "All" && row.sector !== assetSector) return false;
    if (!q) return true;
    const blob = [row.y, row.x, row.yName, row.xName, row.sector, row.why, row.status].join(" ").toLowerCase();
    return blob.indexOf(q) !== -1;
  });
  document.getElementById("asset-all-empty").hidden = filtered.length > 0;
  table.replaceChildren();
  if (!filtered.length) return;
  const stocks = assetKey === "stocks";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.append(sortHeader("Pair", "pair", true));
  if (stocks) {
    hr.append(sortHeader("Sector", "sector", true));
    hr.append(sortHeader("Corr", "corr", false));
  }
  hr.append(sortHeader("Status", "status", true));
  hr.append(sortHeader("Kalman z", "absz", false));
  hr.append(sortHeader("Half-life", "hl", false));
  hr.append(sortHeader("ADF", "adf", false));
  hr.append(sortHeader("KPSS", "kpss", false));
  hr.append(sortHeader("Beta", "betaNow", false));
  hr.append(sortHeader("Rolling z", "rollZNow", false));
  hr.append(sortHeader("Rolling agrees", "agrees", true));
  hr.append(sortHeader("Why", "why", true));
  thead.append(hr);
  const tb = document.createElement("tbody");
  sortAssetRows(filtered).forEach(function (row) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", function () { openAssetPair(row); });
    tr.append(pairCell(row));
    if (stocks) {
      tr.append(textCell(row.sector || "—", true));
      tr.append(textCell(fmt(row.corr, 3), false));
    }
    tr.append(textCell(statusText(row), true));
    tr.append(textCell(fmt(row.z, 3), false));
    tr.append(textCell(finite(row.hl) ? fmt(row.hl, 3) : "—", false));
    tr.append(textCell(fmtP(row.adf), false));
    tr.append(textCell(fmtP(row.kpss), false));
    tr.append(textCell(fmt(row.betaNow, 4), false));
    tr.append(textCell(fmt(row.rollZNow, 3), false));
    tr.append(textCell(row.rollingAgrees ? "Yes" : "No", true));
    const why = document.createElement("td");
    why.className = "left wrap";
    why.textContent = row.why || "—";
    tr.append(why);
    tb.append(tr);
  });
  table.append(thead, tb);
}

function fillAssetSectors(block) {
  const field = document.getElementById("asset-sector-field");
  const select = document.getElementById("asset-sector");
  const stocks = assetKey === "stocks";
  field.hidden = !stocks;
  if (!stocks) return;
  const previous = assetSector;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "All";
  all.textContent = "All sectors";
  select.append(all);
  const seen = {};
  (block.sectors || []).forEach(function (item) {
    if (!item.sector || seen[item.sector]) return;
    seen[item.sector] = true;
    const opt = document.createElement("option");
    opt.value = item.sector;
    opt.textContent = item.sector + " (" + item.tested + ")";
    select.append(opt);
  });
  (block.pairs || []).forEach(function (row) {
    if (!row.sector || seen[row.sector]) return;
    seen[row.sector] = true;
    const opt = document.createElement("option");
    opt.value = row.sector;
    opt.textContent = row.sector;
    select.append(opt);
  });
  const keep = previous && seen[previous];
  assetSector = keep ? previous : "All";
  select.value = assetSector;
}

function renderDropped(block) {
  const card = document.getElementById("asset-dropped-card");
  const dropped = block.dropped || [];
  card.hidden = dropped.length === 0;
  document.getElementById("asset-dropped-title").textContent = "Dropped tickers · " + dropped.length;
  const table = document.getElementById("table-asset-dropped");
  table.replaceChildren();
  if (!dropped.length) return;
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  ["Ticker", "Company", "Sector", "Reason"].forEach(function (name) {
    const th = document.createElement("th");
    th.className = "left";
    th.textContent = name;
    hr.append(th);
  });
  thead.append(hr);
  const tb = document.createElement("tbody");
  dropped.forEach(function (row) {
    const tr = document.createElement("tr");
    tr.append(textCell(row.ticker, true));
    tr.append(textCell(row.name, true));
    tr.append(textCell(row.sector, true));
    const why = document.createElement("td");
    why.className = "left wrap";
    why.textContent = row.reason || "";
    tr.append(why);
    tb.append(tr);
  });
  table.append(thead, tb);
}

function renderAssetHome(block) {
  if (assetHomeKey !== assetKey) {
    assetSort = { key: "absz", dir: -1 };
    assetSector = "All";
    document.getElementById("asset-filter").value = "";
    assetHomeKey = assetKey;
  }
  fillAssetSectors(block);
  const opps = byAbsZ((block.pairs || []).filter(function (row) { return row.status === "opportunity"; }));
  const watch = byAbsZ((block.pairs || []).filter(function (row) { return row.status === "watchlist"; }));
  document.getElementById("asset-opp-title").textContent = "Opportunities · " + opps.length;
  document.getElementById("asset-watch-title").textContent = "Watchlist · " + watch.length;
  document.getElementById("asset-opp-empty").hidden = opps.length > 0;
  document.getElementById("asset-watch-empty").hidden = watch.length > 0;
  renderAssetScreenTable(document.getElementById("table-asset-opp"), opps);
  renderAssetScreenTable(document.getElementById("table-asset-watch"), watch);
  renderAssetAll(block);
  renderDropped(block);
}

function openAssetPair(row) {
  location.hash = (assetKey === "stocks" ? "#s-pair=" : "#c-pair=") + encodeURIComponent(row.id);
}

function renderAssetPair(block, hash) {
  const rowId = decodeURIComponent(hash.slice("#c-pair=".length));
  let row = null;
  (block.pairs || []).forEach(function (item) { if (item.id === rowId) row = item; });
  if (!row) {
    const home = assetHome(assetKey);
    history.replaceState(null, "", home);
    showAsset(assetKey, home);
    return;
  }
  const lines = assetLines(row);
  document.getElementById("asset-pair-title").textContent = lines[0];
  document.getElementById("asset-pair-orient").textContent =
    (lines[1] ? lines[1] + ". " : "") + "Kalman spread z-score. Lines at 0 and ±2. Research only, not trading advice.";
  const dates = (block.dateSets || [])[row.dateSet] || [];
  drawChart(document.getElementById("chart-asset-z"), row.zSeries || [], {
    color: "#8eb7ff",
    dates: dates,
    refs: [
      { value: 2, color: "#e08a8a", label: "+2" },
      { value: -2, color: "#e08a8a", label: "−2" },
      { value: 0, color: "#66758a", dash: "2 3", label: "0" }
    ]
  });
}

function addParagraph(parent, text) {
  if (!text) return;
  const p = document.createElement("p");
  p.textContent = text;
  parent.append(p);
}

function renderAssetMore(block) {
  const body = document.getElementById("asset-howto");
  body.replaceChildren();
  addParagraph(body, "An opportunity passes every filter on the Kalman tradeable spread: ADF p < 0.05, KPSS not rejected (p > 0.05), half-life from 3 to 30 trading days, and a current |z| of at least 2. Rolling agrees means the 120-day rolling OLS z has the same sign as the Kalman z and |rolling z| is at least 1.5.");
  addParagraph(body, "Each pair is lined up on its own common trading days. Non-positive prices are dropped, and today's incomplete daily bar is dropped. Closes are natural logs. The Kalman variances are estimated on the first 500 of the last 750 common sessions and then frozen. The tested spread is the cumulative sum of the daily change in ln Y minus the predicted hedge ratio times the daily change in ln X, over the final 250 sessions. The z-score uses that 250-day mean and sample standard deviation.");
  addParagraph(body, "The rolling OLS z is fit on the 120 closes before the last one and applied to that last close. It is the log-price residual divided by the residual standard deviation of that fit. Rolling agrees when this z has the same sign as the Kalman z and its absolute value is at least 1.5.");
  addParagraph(body, block.lead);
  addParagraph(body, block.multipleTesting);
  addParagraph(body, block.universeNote);
  if (block.catalog && block.catalog.length) {
    addParagraph(body, block.catalog.map(function (row) {
      return row.yName + "/" + row.xName + " (" + row.y + "/" + row.x + ")";
    }).join("; ") + ".");
  }
  if (block.sectors && block.sectors.length) {
    addParagraph(body, "Pairs tested by sector: " + block.sectors.map(function (item) {
      return item.sector + " " + item.tested;
    }).join(", ") + ".");
  }
  (block.warnings || []).forEach(function (note) { addParagraph(body, note); });
}

function applyAssetChrome(key, block) {
  const copy = key === "stocks"
    ? { eyebrow: "Equities · research", h1: "S&P 500 pairs", title: "S&P 500 research dashboard" }
    : { eyebrow: "Commodities · research", h1: "Commodity pairs", title: "Commodity research dashboard" };
  document.querySelector(".eyebrow").textContent = copy.eyebrow;
  document.querySelector("h1").textContent = copy.h1;
  document.title = copy.title;
  const stamp = block.generatedAtSast || DATA.generatedAtSast;
  let asof = "Data as of " + (stamp ? prettyStamp(stamp) : "—");
  if (block.priceStart && block.priceEnd) asof += " · window " + block.priceStart + " → " + block.priceEnd;
  if (block.source) asof += " · " + block.source;
  document.getElementById("asof").textContent = asof;
  document.getElementById("foot").textContent =
    "Generated " + (stamp ? prettyStamp(stamp) : "—") +
    " · " + (block.nTested || 0) + " pairs" +
    (block.source ? " · " + block.source : "") +
    " · Africa/Johannesburg (SAST, UTC+2). Research only, not trading advice.";
  applyStale(stamp);
}

function showAsset(key, hash) {
  assetKey = key;
  const block = assetBlock(key);
  hideFxPanels();
  document.getElementById("asset-root").hidden = false;
  setAssetNav(key);
  applyAssetChrome(key, block);
  const failed = !!block.error;
  const err = document.getElementById("asset-error");
  err.hidden = !failed;
  err.textContent = failed ? block.error : "";
  const lead = document.getElementById("asset-lead");
  lead.hidden = failed || !block.lead;
  lead.textContent = block.lead || "";
  const testing = document.getElementById("asset-testing");
  const showNote = !failed && !!block.multipleTesting;
  testing.hidden = !showNote;
  testing.textContent = showNote ? block.multipleTesting : "";
  let view = "home";
  if (!failed && (hash.indexOf("#c-pair=") === 0 || hash.indexOf("#s-pair=") === 0)) view = "pair";
  if (!failed && (hash === "#commodities-more" || hash === "#stocks-more")) view = "more";
  document.getElementById("panel-asset").hidden = view !== "home" || failed;
  document.getElementById("panel-asset-pair").hidden = view !== "pair";
  document.getElementById("panel-asset-more").hidden = view !== "more";
  const more = document.getElementById("more-link");
  if (more) {
    more.href = key === "stocks" ? "#stocks-more" : "#commodities-more";
    more.hidden = view === "more" || failed;
  }
  const home = assetHome(key);
  document.getElementById("asset-back").setAttribute("href", home);
  document.getElementById("asset-more-back").setAttribute("href", home);
  if (failed) return;
  if (view === "home") renderAssetHome(block);
  if (view === "pair") renderAssetPair(block, hash);
  if (view === "more") renderAssetMore(block);
  window.scrollTo(0, 0);
}

function init() {
  if (DATA.fxError) {
    const err = document.getElementById("fx-error");
    err.hidden = false;
    err.textContent = DATA.fxError;
  }
  if (!FX_READY) {
    document.getElementById("asof").textContent = DATA.fxError ? "Data as of —" : document.getElementById("asof").textContent;
    bind();
    route();
    return;
  }
  if (N !== 28 || KAL.records.length !== 378) {
    throw new Error("Dashboard payload is not the 28-pair universe.");
  }
  fillMeta();
  snapshotFxChrome();
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
  renderScreen();
  bind();
  route();
}

init();
