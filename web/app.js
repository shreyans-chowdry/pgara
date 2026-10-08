/* PGARA Compiler Studio front end (dependency-free). */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const SVGNS = "http://www.w3.org/2000/svg";

const state = {
  examples: [],
  allocatorNames: {},
  report: null,
  tab: "tokens",
  fn: null,
  allocator: "pgara",
  rendered: {},
  steps: {},
  compileTimer: null,
  requestId: 0,
  astCollapsed: new Set(),
};

const KEYWORDS = new Set(["int", "void", "if", "else", "while", "for", "return", "break", "continue", "print", "input"]);
const LINE_H = 20;

/* ------------------------------------------------------------------ utils */
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function el(tag, attrs = {}, html) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  if (html !== undefined) node.innerHTML = html;
  return node;
}
function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
function fmt(n, digits = 0) {
  if (n === null || n === undefined) return "–";
  if (typeof n !== "number") return String(n);
  return n.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
function pct(x) { return (x * 100).toFixed(1) + "%"; }

const tooltip = $("#tooltip");
function showTip(evt, text) {
  tooltip.textContent = text;
  tooltip.style.display = "block";
  const x = Math.min(evt.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8);
  const y = Math.min(evt.clientY + 14, window.innerHeight - tooltip.offsetHeight - 8);
  tooltip.style.left = x + "px";
  tooltip.style.top = y + "px";
}
function hideTip() { tooltip.style.display = "none"; }

/* ------------------------------------------------------------------ editor */
const src = $("#source");
const hl = $("#highlight");
const gutter = $("#gutter");
const lineMark = $("#line-mark");

function highlightSource(text) {
  const re = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|([A-Za-z_][A-Za-z0-9_]*)(\s*\()?|(\d+)|(<=|>=|==|!=|&&|\|\||\+=|-=|\*=|\+\+|--|[+\-*/%<>!=])|([^A-Za-z0-9_\/]+|\/)/g;
  let out = "";
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m[1]) out += `<span class="tk-com">${esc(m[1])}</span>`;
    else if (m[2]) {
      const word = m[2];
      if (KEYWORDS.has(word)) out += `<span class="tk-kw">${esc(word)}</span>`;
      else if (m[3]) out += `<span class="tk-fn">${esc(word)}</span>`;
      else out += esc(word);
      if (m[3]) out += esc(m[3]);
    } else if (m[4]) out += `<span class="tk-num">${esc(m[4])}</span>`;
    else if (m[5]) out += `<span class="tk-op">${esc(m[5])}</span>`;
    else out += esc(m[0]);
  }
  return out + "\n";
}

function errorLines() {
  const lines = new Set();
  if (state.report) for (const d of state.report.diagnostics || []) if (d.severity === "error") lines.add(d.line);
  return lines;
}

function refreshEditor() {
  const text = src.value;
  hl.innerHTML = highlightSource(text);
  const n = text.split("\n").length;
  const errs = errorLines();
  let g = "";
  for (let i = 1; i <= n; i++) g += `<div class="${errs.has(i) ? "err" : ""}">${i}</div>`;
  gutter.innerHTML = g;
  syncScroll();
}
function syncScroll() {
  hl.scrollTop = src.scrollTop;
  hl.scrollLeft = src.scrollLeft;
  gutter.scrollTop = src.scrollTop;
  positionLineMark();
}
let markedLine = 0;
function markLine(line, reveal = false) {
  markedLine = line || 0;
  if (reveal && markedLine) {
    const top = (markedLine - 1) * LINE_H;
    if (top < src.scrollTop || top > src.scrollTop + src.clientHeight - 3 * LINE_H) {
      src.scrollTop = Math.max(0, top - src.clientHeight / 2);
      syncScroll();
    }
  }
  positionLineMark();
}
function positionLineMark() {
  if (!markedLine) { lineMark.style.display = "none"; return; }
  lineMark.style.display = "block";
  lineMark.style.top = (12 + (markedLine - 1) * LINE_H - src.scrollTop) + "px";
}
function gotoLine(line, col = 1) {
  const lines = src.value.split("\n");
  let pos = 0;
  for (let i = 0; i < Math.min(line - 1, lines.length); i++) pos += lines[i].length + 1;
  pos += Math.max(0, col - 1);
  src.focus();
  src.setSelectionRange(pos, pos);
  markLine(line, true);
  updateCursor();
}
function updateCursor() {
  const before = src.value.slice(0, src.selectionStart).split("\n");
  $("#cursor-pos").textContent = `Ln ${before.length}, Col ${before[before.length - 1].length + 1}`;
}

src.addEventListener("input", () => {
  markLine(0);
  refreshEditor();
  if ($("#live").checked) scheduleCompile();
});
src.addEventListener("scroll", syncScroll);
src.addEventListener("keyup", updateCursor);
src.addEventListener("click", () => { updateCursor(); markLine(0); });
src.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    const s = src.selectionStart;
    src.setRangeText("    ", s, src.selectionEnd, "end");
    refreshEditor();
  } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    compileNow();
  }
});

/* ------------------------------------------------------------------ compile */
function parseInputs(text) {
  return text.split(/[\s,]+/).filter(Boolean).map(Number).filter((x) => Number.isFinite(x)).map((x) => Math.trunc(x));
}
function setStatus(kind, text) {
  const s = $("#status");
  s.className = "status " + kind;
  s.textContent = text;
}
function scheduleCompile() {
  clearTimeout(state.compileTimer);
  state.compileTimer = setTimeout(compileNow, 450);
}
async function compileNow() {
  clearTimeout(state.compileTimer);
  const id = ++state.requestId;
  setStatus("busy", "Compiling…");
  const body = {
    source: src.value,
    k: parseInt($("#k").value, 10) || 4,
    opt_level: parseInt($("#opt").value, 10),
    train_inputs: parseInputs($("#train").value),
    test_inputs: parseInputs($("#test").value),
  };
  const t0 = performance.now();
  try {
    const res = await fetch("/api/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const report = await res.json();
    if (id !== state.requestId) return;
    const ms = Math.round(performance.now() - t0);
    if (report.fatal) {
      setStatus("err", report.fatal);
      return;
    }
    state.report = report;
    state.rendered = {};
    const fns = report.functions ? Object.keys(report.functions) : [];
    if (!fns.includes(state.fn)) state.fn = fns.includes("main") ? "main" : fns[0] || null;
    const errors = (report.diagnostics || []).filter((d) => d.severity === "error").length;
    if (!report.ok) setStatus("err", `${errors} error${errors === 1 ? "" : "s"}`);
    else {
      const run = report.targets[state.allocator] ? report.targets[state.allocator].stats : null;
      const verdict = run && !run.matches_reference ? " · output mismatch" : "";
      setStatus("ok", `Compiled in ${ms} ms${verdict}`);
    }
    renderDiagnostics();
    refreshEditor();
    renderActive();
  } catch (err) {
    if (id === state.requestId) setStatus("err", "Server unreachable");
  }
}
$("#compile").addEventListener("click", compileNow);
for (const id of ["#k", "#opt", "#train", "#test"]) $(id).addEventListener("change", compileNow);

function renderDiagnostics() {
  const box = $("#diagnostics");
  box.innerHTML = "";
  const diags = (state.report && state.report.diagnostics) || [];
  if (!diags.length) {
    box.appendChild(el("div", { class: "diag-ok" }, "No lexical, syntax or semantic diagnostics."));
    return;
  }
  for (const d of diags) {
    const row = el("div", { class: `diag ${d.severity}` },
      `<span class="sev">${esc(d.severity)}</span><span class="where">${esc(d.phase)} ${d.line}:${d.col}</span><span>${esc(d.message)}</span>`);
    row.addEventListener("click", () => gotoLine(d.line, d.col));
    box.appendChild(row);
  }
}

/* ------------------------------------------------------------------ tabs */
$$("#tabs button").forEach((b) => b.addEventListener("click", () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  state.tab = b.dataset.tab;
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + state.tab));
  renderActive();
}));

const RENDERERS = {
  tokens: renderTokens, ast: renderAST, symbols: renderSymbols, tac: renderTAC, ssa: renderSSA,
  cfg: renderCFG, alloc: renderAlloc, asm: renderAsm, run: renderRun, grammar: renderGrammar,
};
function renderActive() {
  if (!state.report) return;
  if (state.rendered[state.tab]) return;
  const view = $("#view-" + state.tab);
  view.innerHTML = "";
  RENDERERS[state.tab](view);
  state.rendered[state.tab] = true;
}
function needsBackEnd(view) {
  if (state.report && state.report.ok) return false;
  view.appendChild(el("div", { class: "empty" }, "Fix the errors listed under the editor to see this stage."));
  return true;
}
function functionSelect(onChange) {
  const sel = el("select", { class: "select" });
  for (const name of Object.keys(state.report.functions || {})) {
    const o = el("option", { value: name }, esc(name));
    if (name === state.fn) o.selected = true;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => { state.fn = sel.value; state.rendered = {}; onChange(); });
  const label = el("label", {}, "Function");
  label.appendChild(sel);
  return label;
}
function allocatorSelect(onChange) {
  const sel = el("select", { class: "select" });
  for (const [key, name] of Object.entries(state.allocatorNames)) {
    const o = el("option", { value: key }, esc(name));
    if (key === state.allocator) o.selected = true;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => { state.allocator = sel.value; state.rendered = {}; onChange(); });
  const label = el("label", {}, "Allocator");
  label.appendChild(sel);
  return label;
}
function rerender() { state.rendered[state.tab] = false; renderActive(); }

/* ------------------------------------------------------------------ tokens */
function renderTokens(view) {
  const toks = state.report.tokens.filter((t) => t.kind !== "EOF");
  const counts = {};
  for (const t of toks) counts[t.kind] = (counts[t.kind] || 0) + 1;
  const stats = el("div", { class: "stats" });
  stats.innerHTML = `<div class="stat"><div class="v">${toks.length}</div><div class="l">tokens</div></div>` +
    ["KW", "ID", "NUM", "OP", "PUNCT"].map((k) => `<div class="stat tone-${k}"><div class="v">${counts[k] || 0}</div><div class="l">${{ KW: "keywords", ID: "identifiers", NUM: "literals", OP: "operators", PUNCT: "punctuation" }[k]}</div></div>`).join("");
  view.appendChild(stats);
  const bar = el("div", { class: "toolbar" });
  const filter = el("input", { class: "select", placeholder: "Filter lexeme or kind", style: "width:220px" });
  bar.appendChild(filter);
  bar.appendChild(el("span", { class: "caption", style: "margin:0" }, "Maximal-munch DFA scan. Hover a token to locate it in the source."));
  view.appendChild(bar);
  const list = el("div");
  view.appendChild(list);
  function draw() {
    const q = filter.value.trim().toLowerCase();
    list.innerHTML = "";
    const byLine = new Map();
    for (const t of toks) {
      if (q && !t.lexeme.toLowerCase().includes(q) && !t.kind.toLowerCase().includes(q)) continue;
      if (!byLine.has(t.line)) byLine.set(t.line, []);
      byLine.get(t.line).push(t);
    }
    for (const [line, ts] of byLine) {
      const row = el("div", { class: "token-line" });
      row.appendChild(el("div", { class: "ln" }, String(line)));
      const chips = el("div", { class: "chips" });
      for (const t of ts) {
        const c = el("span", { class: "chip " + t.kind }, `<span class="lx">${esc(t.lexeme)}</span><span class="kd">${esc(t.kind)}</span>`);
        c.addEventListener("mouseenter", (e) => { markLine(t.line, true); showTip(e, `${t.kind}  "${t.lexeme}"  at ${t.line}:${t.col}`); });
        c.addEventListener("mouseleave", hideTip);
        c.addEventListener("click", () => gotoLine(t.line, t.col));
        chips.appendChild(c);
      }
      row.appendChild(chips);
      list.appendChild(row);
    }
    if (!byLine.size) list.appendChild(el("div", { class: "empty" }, "No tokens match."));
  }
  filter.addEventListener("input", draw);
  draw();
}

/* ------------------------------------------------------------------ pan / zoom canvas */
function makeCanvas(view, hint) {
  const box = el("div", { class: "canvas" });
  const s = svg("svg");
  const g = svg("g");
  s.appendChild(g);
  box.appendChild(s);
  box.appendChild(el("div", { class: "hint" }, hint || "Drag to pan · scroll to zoom"));
  view.appendChild(box);
  const t = { x: 20, y: 20, k: 1 };
  const apply = () => g.setAttribute("transform", `translate(${t.x},${t.y}) scale(${t.k})`);
  let drag = null;
  box.addEventListener("mousedown", (e) => { drag = { x: e.clientX - t.x, y: e.clientY - t.y }; box.classList.add("dragging"); });
  window.addEventListener("mousemove", (e) => { if (drag) { t.x = e.clientX - drag.x; t.y = e.clientY - drag.y; apply(); } });
  window.addEventListener("mouseup", () => { drag = null; box.classList.remove("dragging"); });
  box.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = box.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const f = Math.exp(-e.deltaY * 0.0015);
    const nk = Math.min(3, Math.max(0.15, t.k * f));
    t.x = mx - (mx - t.x) * (nk / t.k);
    t.y = my - (my - t.y) * (nk / t.k);
    t.k = nk;
    apply();
  }, { passive: false });
  function fit(w, h, focusX, minK = 0.15) {
    const r = box.getBoundingClientRect();
    const k = Math.min(1.15, Math.max(minK, Math.min((r.width - 40) / Math.max(w, 1), (r.height - 40) / Math.max(h, 1))));
    t.k = k;
    t.x = focusX === undefined || w * k <= r.width - 40 ? (r.width - w * k) / 2 : r.width / 2 - focusX * k;
    t.y = 20;
    apply();
  }
  apply();
  return { svg: s, g, fit, box };
}

/* ------------------------------------------------------------------ AST */
function renderAST(view) {
  const bar = el("div", { class: "toolbar" });
  const expand = el("button", { class: "btn small" }, "Expand all");
  const collapse = el("button", { class: "btn small" }, "Collapse expressions");
  const fitBtn = el("button", { class: "btn small" }, "Fit");
  bar.append(expand, collapse, fitBtn, el("span", { class: "caption", style: "margin:0" }, "Click a node to fold it. Types are the synthesized attribute from semantic analysis."));
  view.appendChild(bar);
  const canvas = makeCanvas(view);
  const root = state.report.ast;
  const NODE_H = 38, V_GAP = 34, H_GAP = 14;

  function width(n) { return Math.max(56, Math.max(n.label.length, (n.kind || "").length * 0.85) * 7.4 + 22); }
  function layout(n, depth) {
    const collapsed = state.astCollapsed.has(n.id);
    const kids = collapsed ? [] : n.children;
    n._w = width(n);
    n._depth = depth;
    if (!kids.length) { n._span = n._w; return; }
    let total = 0;
    for (const c of kids) { layout(c, depth + 1); total += c._span; }
    total += H_GAP * (kids.length - 1);
    n._span = Math.max(n._w, total);
  }
  function place(n, left) {
    const collapsed = state.astCollapsed.has(n.id);
    const kids = collapsed ? [] : n.children;
    n._x = left + n._span / 2;
    n._y = n._depth * (NODE_H + V_GAP);
    if (!kids.length) return;
    let total = kids.reduce((a, c) => a + c._span, 0) + H_GAP * (kids.length - 1);
    let x = left + (n._span - total) / 2;
    for (const c of kids) { place(c, x); x += c._span + H_GAP; }
  }
  function draw(fitAfter) {
    canvas.g.innerHTML = "";
    layout(root, 0);
    place(root, 0);
    let maxY = 0;
    const edges = svg("g"), nodes = svg("g");
    canvas.g.append(edges, nodes);
    (function walk(n) {
      maxY = Math.max(maxY, n._y);
      const collapsed = state.astCollapsed.has(n.id);
      const kids = collapsed ? [] : n.children;
      for (const c of kids) {
        const y1 = n._y + NODE_H, y2 = c._y, my = (y1 + y2) / 2;
        edges.appendChild(svg("path", { class: "edge", d: `M${n._x},${y1} C${n._x},${my} ${c._x},${my} ${c._x},${y2}` }));
        if (c.edge && n.children.length > 1 && !["decls", "stmts", "args", "params"].includes(c.edge)) {
          edges.appendChild(svg("text", { class: "edge-label", x: (n._x + c._x) / 2 + 4, y: my - 2 }, c.edge));
        }
        walk(c);
      }
      const gnode = svg("g", { class: "node cat-" + astCategory(n.kind) + (n.children.length ? "" : " leaf") + (collapsed ? " collapsed" : ""), transform: `translate(${n._x - n._w / 2},${n._y})` });
      gnode.appendChild(svg("rect", { width: n._w, height: NODE_H, rx: 8 }));
      gnode.appendChild(svg("text", { class: "kind", x: n._w / 2, y: 13, "text-anchor": "middle" }, n.kind + (collapsed ? ` +${countNodes(n) - 1}` : "")));
      gnode.appendChild(svg("text", { x: n._w / 2, y: 29, "text-anchor": "middle" }, n.label));
      gnode.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!n.children.length) return;
        if (state.astCollapsed.has(n.id)) state.astCollapsed.delete(n.id); else state.astCollapsed.add(n.id);
        draw(false);
      });
      gnode.addEventListener("mousedown", (e) => e.stopPropagation());
      gnode.addEventListener("mouseenter", (e) => { markLine(n.line, true); showTip(e, `${n.kind} · line ${n.line}:${n.col}${n.type ? " · type " + n.type : ""}`); });
      gnode.addEventListener("mouseleave", hideTip);
      nodes.appendChild(gnode);
    })(root);
    if (fitAfter) canvas.fit(root._span, maxY + NODE_H, root._x, 0.55);
  }
  function countNodes(n) { return 1 + n.children.reduce((a, c) => a + countNodes(c), 0); }
  expand.addEventListener("click", () => { state.astCollapsed.clear(); draw(true); });
  collapse.addEventListener("click", () => {
    (function walk(n) {
      if (["Binary", "Unary", "Call", "Index"].includes(n.kind) && n.children.length) state.astCollapsed.add(n.id);
      n.children.forEach(walk);
    })(root);
    draw(true);
  });
  fitBtn.addEventListener("click", () => draw(true));
  if (!state.astCollapsed.size && countNodes(root) > 120) {
    (function walk(n) {
      if (["Binary", "Unary", "Call", "Index"].includes(n.kind) && n.children.length) state.astCollapsed.add(n.id);
      n.children.forEach(walk);
    })(root);
  }
  draw(true);
}

/* ------------------------------------------------------------------ symbols */
function renderSymbols(view) {
  const scopes = state.report.symbols || [];
  if (!scopes.length) { view.appendChild(el("div", { class: "empty" }, "The symbol table is built once the program parses.")); return; }
  const total = scopes.reduce((a, s) => a + s.symbols.length, 0);
  const stats = el("div", { class: "stats" });
  stats.innerHTML = `<div class="stat"><div class="v">${scopes.length}</div><div class="l">scopes</div></div>
    <div class="stat"><div class="v">${total}</div><div class="l">symbols</div></div>
    <div class="stat"><div class="v">${Math.max(...scopes.map((s) => s.level))}</div><div class="l">max nesting</div></div>`;
  view.appendChild(stats);
  view.appendChild(el("div", { class: "caption" }, "Stack of hash maps, one per scope; lookups walk outward. Unique names (x#1) disambiguate shadowed declarations in the IR."));
  for (const sc of scopes) {
    const card = el("div", { class: "card scope", style: `margin-left:${sc.level * 22}px` });
    card.appendChild(el("div", { class: "card-head" },
      `<span class="title">${esc(sc.name)} <span class="pill">scope ${sc.id}</span><span class="pill">level ${sc.level}</span></span><span class="muted mono">line ${sc.line}${sc.parent !== null ? " · parent " + sc.parent : ""}</span>`));
    if (!sc.symbols.length) {
      card.appendChild(el("div", { class: "card-body muted" }, "No declarations."));
    } else {
      const rows = sc.symbols.map((s) => `<tr data-line="${s.line}"><td class="mono"><b>${esc(s.name)}</b></td><td class="mono">${esc(s.uname)}</td><td>${esc(s.kind)}</td><td class="mono">${esc(s.type)}</td><td class="num">${s.size ?? "–"}</td><td class="num">${s.line}</td><td class="num">${s.uses}</td></tr>`).join("");
      const t = el("table", { class: "grid" }, `<thead><tr><th>Name</th><th>IR name</th><th>Kind</th><th>Type</th><th class="num">Size</th><th class="num">Line</th><th class="num">Refs</th></tr></thead><tbody>${rows}</tbody>`);
      $$("tr[data-line]", t).forEach((tr) => {
        tr.addEventListener("mouseenter", () => markLine(+tr.dataset.line, true));
        tr.addEventListener("click", () => gotoLine(+tr.dataset.line));
      });
      card.appendChild(t);
    }
    view.appendChild(card);
  }
}

/* ------------------------------------------------------------------ listings with stepper */
function listingView(view, key, rows, opts = {}) {
  const st = state.steps[key] || (state.steps[key] = { pos: rows.length, timer: null });
  if (st.pos > rows.length) st.pos = rows.length;
  const bar = el("div", { class: "toolbar" });
  (opts.leading || []).forEach((n) => bar.appendChild(n));
  bar.appendChild(el("span", { class: "spacer" }));
  const stepper = el("div", { class: "stepper" });
  const first = el("button", { class: "btn small", title: "Start" }, "⏮");
  const prev = el("button", { class: "btn small", title: "Previous instruction" }, "◀");
  const play = el("button", { class: "btn small", title: "Play emission" }, "▶ Play");
  const next = el("button", { class: "btn small", title: "Next instruction" }, "▶");
  const last = el("button", { class: "btn small", title: "Show all" }, "⏭");
  const pos = el("span", { class: "pos" });
  stepper.append(first, prev, pos, next, last, play);
  bar.appendChild(stepper);
  view.appendChild(bar);
  if (opts.caption) view.appendChild(el("div", { class: "caption" }, opts.caption));
  const box = el("div", { class: "listing" });
  const rowEls = rows.map((r, i) => {
    const row = el("div", { class: "row" + (r.kind === "label" ? " label" : "") });
    row.innerHTML = `<span class="n">${i + 1}</span><span class="src">${r.line ? "L" + r.line : ""}</span><span class="txt">${esc(r.text)}</span>` + (r.tag ? `<span class="tag ${esc(r.tag)}">${esc(r.tag.replace("_", " "))}</span>` : "");
    row.addEventListener("mouseenter", (e) => { if (r.line) markLine(r.line, true); if (r.ir) showTip(e, "from IR: " + r.ir); });
    row.addEventListener("mouseleave", hideTip);
    row.addEventListener("click", () => { st.pos = i + 1; update(); });
    box.appendChild(row);
    return row;
  });
  view.appendChild(box);
  function update() {
    rowEls.forEach((row, i) => {
      row.classList.toggle("hidden", i >= st.pos);
      row.classList.toggle("cur", i === st.pos - 1 && st.pos < rows.length);
    });
    pos.textContent = `${st.pos} / ${rows.length}`;
    const cur = rows[st.pos - 1];
    if (cur && cur.line && st.pos < rows.length) {
      markLine(cur.line, true);
      const rowEl = rowEls[st.pos - 1];
      const v = view.getBoundingClientRect(), r = rowEl.getBoundingClientRect();
      if (r.bottom > v.bottom - 10 || r.top < v.top + 60) view.scrollTop += r.top - v.top - v.height / 2;
    }
  }
  function stop() { clearInterval(st.timer); st.timer = null; play.textContent = "▶ Play"; }
  first.addEventListener("click", () => { stop(); st.pos = 1; update(); });
  prev.addEventListener("click", () => { stop(); st.pos = Math.max(1, st.pos - 1); update(); });
  next.addEventListener("click", () => { stop(); st.pos = Math.min(rows.length, st.pos + 1); update(); });
  last.addEventListener("click", () => { stop(); st.pos = rows.length; update(); markLine(0); });
  play.addEventListener("click", () => {
    if (st.timer) { stop(); return; }
    if (st.pos >= rows.length) st.pos = 0;
    play.textContent = "❚❚ Pause";
    st.timer = setInterval(() => {
      if (!document.body.contains(box)) { stop(); return; }
      st.pos += 1;
      if (st.pos >= rows.length) { st.pos = rows.length; stop(); }
      update();
    }, 260);
  });
  update();
}

function renderTAC(view) {
  if (needsBackEnd(view)) return;
  const rows = state.report.tac[state.fn] || [];
  listingView(view, "tac:" + state.fn, rows, {
    leading: [functionSelect(rerender)],
    caption: "Linear three-address code from syntax-directed translation. Conditions use jumping code with inherited true/false labels (short-circuit && and ||).",
  });
}

function renderSSA(view) {
  if (needsBackEnd(view)) return;
  const fn = state.fn;
  const ssaRows = state.report.ssa[fn].listing;
  const optRows = state.report.optimized[fn].listing;
  const log = state.report.opt_log[fn];
  const which = state.steps["ssa-mode"] || "opt";
  const mode = el("select", { class: "select" }, `<option value="ssa">SSA form (before optimisation)</option><option value="opt">Optimised SSA</option>`);
  mode.value = which;
  mode.addEventListener("change", () => { state.steps["ssa-mode"] = mode.value; rerender(); });
  const modeLabel = el("label", {}, "Stage");
  modeLabel.appendChild(mode);
  const stats = el("div", { class: "stats" });
  const removed = log.instrs_before - log.instrs_after;
  stats.innerHTML = `<div class="stat"><div class="v">${state.report.ssa[fn].phis}</div><div class="l">φ-functions placed</div></div>
    <div class="stat"><div class="v">${log.instrs_before}</div><div class="l">instrs before</div></div>
    <div class="stat"><div class="v">${log.instrs_after}</div><div class="l">instrs after</div></div>
    <div class="stat"><div class="v">${log.instrs_before ? pct(removed / log.instrs_before) : "0%"}</div><div class="l">removed</div></div>`;
  view.appendChild(stats);
  if (log.passes.length) {
    const t = el("table", { class: "grid", style: "margin-bottom:14px" },
      `<thead><tr><th>Pass</th><th class="num">Round</th><th class="num">Changes</th></tr></thead><tbody>` +
      log.passes.map((p) => `<tr><td>${esc(p.pass)}</td><td class="num">${p.round ?? "–"}</td><td class="num">${p.changes}</td></tr>`).join("") + "</tbody>");
    view.appendChild(t);
  }
  listingView(view, `ssa:${which}:${fn}`, which === "ssa" ? ssaRows : optRows, {
    leading: [functionSelect(rerender), modeLabel],
    caption: which === "ssa"
      ? "Pruned SSA (Cytron et al.): φ-functions on the iterated dominance frontier where the variable is live."
      : "After SCCP, copy propagation, algebraic simplification, dominator-based GVN, DCE, block merging and compare-branch fusion.",
  });
}

/* ------------------------------------------------------------------ CFG */
function renderCFG(view) {
  if (needsBackEnd(view)) return;
  const f = state.report.functions[state.fn];
  const bar = el("div", { class: "toolbar" });
  bar.appendChild(functionSelect(rerender));
  const live = el("input", { type: "checkbox" });
  live.checked = !!state.steps["cfg-live"];
  live.addEventListener("change", () => { state.steps["cfg-live"] = live.checked; rerender(); });
  const lab = el("label", {}, "");
  lab.append(live, document.createTextNode("Show live-out sets"));
  bar.appendChild(lab);
  bar.appendChild(el("span", { class: "caption", style: "margin:0" }, "Edge labels: profiled probability (static prior). Dashed edges are loop back edges."));
  view.appendChild(bar);
  const canvas = makeCanvas(view);
  const blocks = f.blocks;
  const index = new Map(blocks.map((b, i) => [b.name, i]));
  const back = new Set(f.back_edges.map(([a, b]) => a + "→" + b));
  const succ = new Map(blocks.map((b) => [b.name, []]));
  for (const e of f.edges) succ.get(e.from).push(e.to);
  // Layer by longest path over forward edges.
  const layer = new Map(blocks.map((b) => [b.name, 0]));
  for (let iter = 0; iter < blocks.length; iter++) {
    let changed = false;
    for (const e of f.edges) {
      if (back.has(e.from + "→" + e.to)) continue;
      if (layer.get(e.to) < layer.get(e.from) + 1) { layer.set(e.to, layer.get(e.from) + 1); changed = true; }
    }
    if (!changed) break;
  }
  const layers = [];
  for (const b of blocks) { const l = layer.get(b.name); (layers[l] = layers[l] || []).push(b); }
  const CH = 7.1, LH = 15, PAD = 8, HEAD = 22, GAPX = 60, GAPY = 54;
  const size = new Map();
  for (const b of blocks) {
    const lines = b.instrs.slice();
    if (live.checked) lines.push("out: {" + b.live_out.join(", ") + "}");
    const w = Math.min(420, Math.max(150, ...lines.map((l) => l.length * CH + 2 * PAD), (b.name.length + 18) * CH));
    const h = HEAD + PAD + lines.length * LH + 4;
    size.set(b.name, { w, h, lines });
  }
  const pos = new Map();
  let y = 0, maxW = 0;
  for (const row of layers) {
    if (!row) continue;
    row.sort((a, b) => index.get(a.name) - index.get(b.name));
    const totalW = row.reduce((a, b) => a + size.get(b.name).w, 0) + GAPX * (row.length - 1);
    maxW = Math.max(maxW, totalW);
    const h = Math.max(...row.map((b) => size.get(b.name).h));
    row._y = y; row._w = totalW;
    y += h + GAPY;
  }
  for (const row of layers) {
    if (!row) continue;
    let x = (maxW - row._w) / 2;
    for (const b of row) { pos.set(b.name, { x, y: row._y }); x += size.get(b.name).w + GAPX; }
  }
  const edgeG = svg("g"), nodeG = svg("g");
  const defs = svg("defs");
  defs.innerHTML = `<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#475569"/></marker><marker id="arrow-back" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7C3AED"/></marker>`;
  canvas.g.append(defs, edgeG, nodeG);
  const maxCount = Math.max(1, ...blocks.map((b) => b.count));
  for (const e of f.edges) {
    const a = pos.get(e.from), b = pos.get(e.to), sa = size.get(e.from), sb = size.get(e.to);
    const isBack = back.has(e.from + "→" + e.to);
    let d, lx, ly;
    if (isBack) {
      const x1 = a.x + sa.w, y1 = a.y + sa.h / 2, x2 = b.x + sb.w, y2 = b.y + HEAD / 2;
      const off = 46 + 10 * (index.get(e.from) % 4);
      d = `M${x1},${y1} C${Math.max(x1, x2) + off},${y1} ${Math.max(x1, x2) + off},${y2} ${x2 + 2},${y2}`;
      lx = Math.max(x1, x2) + off - 18; ly = (y1 + y2) / 2;
    } else {
      const x1 = a.x + sa.w / 2, y1 = a.y + sa.h, x2 = b.x + sb.w / 2, y2 = b.y;
      const my = (y1 + y2) / 2;
      d = `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2 - 2}`;
      lx = (x1 + x2) / 2 + 4; ly = my - 3;
    }
    edgeG.appendChild(svg("path", { class: "cfg-edge" + (isBack ? " back" : ""), d, "marker-end": isBack ? "url(#arrow-back)" : "url(#arrow)" }));
    if (succ.get(e.from).length > 1) {
      edgeG.appendChild(svg("text", { class: "edge-label", x: lx, y: ly }, `${e.p_profile.toFixed(2)} (${e.p_static.toFixed(2)})`));
    }
  }
  for (const b of blocks) {
    const p = pos.get(b.name), s = size.get(b.name);
    const g = svg("g", { class: "cfg-block" + (b.count === 0 ? " cold" : ""), transform: `translate(${p.x},${p.y})` });
    g.appendChild(svg("rect", { class: "box", width: s.w, height: s.h, rx: 7 }));
    const heat = b.count / maxCount;
    const hc = b.count === 0 ? "#94A3B8" : heatColor(heat);
    g.appendChild(svg("rect", { class: "head", width: s.w, height: HEAD, rx: 7, fill: hc }));
    g.appendChild(svg("rect", { width: s.w, height: 8, y: HEAD - 8, fill: hc }));
    g.appendChild(svg("text", { class: "h", x: PAD, y: 15 }, `${b.name}`));
    g.appendChild(svg("text", { class: "h", x: s.w - PAD, y: 15, "text-anchor": "end" }, `×${fmt(b.count)}  d${b.loop_depth}`));
    s.lines.forEach((line, i) => g.appendChild(svg("text", { x: PAD, y: HEAD + PAD + 9 + i * LH }, line)));
    g.addEventListener("mouseenter", (e) => showTip(e, `${b.name}\nexecuted ${fmt(b.count)}× (training run)\nloop depth ${b.loop_depth}\nlive-in: {${b.live_in.join(", ")}}\nlive-out: {${b.live_out.join(", ")}}`));
    g.addEventListener("mouseleave", hideTip);
    nodeG.appendChild(g);
  }
  canvas.fit(maxW + 120, y);
}

/* ------------------------------------------------------------------ allocation */
const REG_COLORS = ["#4F46E5", "#059669", "#EA580C", "#DB2777", "#0284C7", "#7C3AED", "#CA8A04", "#0D9488",
                    "#DC2626", "#2563EB", "#65A30D", "#C026D3", "#0891B2", "#9333EA", "#E11D48", "#16A34A"];
function regShade(r, k) {
  return REG_COLORS[r % REG_COLORS.length];
}
/* Block-frequency heat: cool blue for rarely executed blocks through to hot red. */
function heatColor(t) {
  const stops = [[37, 99, 235], [124, 58, 237], [219, 39, 119], [234, 88, 12], [220, 38, 38]];
  const x = Math.max(0, Math.min(1, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x)), f = x - i;
  const c = stops[i].map((v, j) => Math.round(v + (stops[i + 1][j] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
/* Colour family of an AST node in the tree view. */
function astCategory(kind) {
  if (["Program", "Function", "GlobalVar", "VarDecl", "Param"].includes(kind)) return "decl";
  if (["If", "While", "For", "Break", "Continue", "Return", "Block"].includes(kind)) return "ctrl";
  if (["Assign", "ExprStmt", "Print"].includes(kind)) return "stmt";
  if (["Var", "Num"].includes(kind)) return "leaf";
  return "expr";
}
function renderAlloc(view) {
  if (needsBackEnd(view)) return;
  const f = state.report.functions[state.fn];
  const a = f.allocations[state.allocator];
  const k = state.report.options.k;
  const bar = el("div", { class: "toolbar" });
  bar.append(functionSelect(rerender), allocatorSelect(rerender));
  view.appendChild(bar);
  const nodes = f.interference.nodes;
  const edges = f.interference.edges;
  const stats = el("div", { class: "stats" });
  stats.innerHTML = `<div class="stat"><div class="v">${nodes.length}</div><div class="l">SSA values</div></div>
    <div class="stat"><div class="v">${edges.length}</div><div class="l">interference edges</div></div>
    <div class="stat"><div class="v">${f.chordal.is_chordal ? "yes" : "no"}</div><div class="l">chordal (PEO verified)</div></div>
    <div class="stat"><div class="v">${f.chordal.max_clique}</div><div class="l">max clique / MaxLive</div></div>
    <div class="stat"><div class="v">${a.spilled.length}</div><div class="l">spilled at k=${k}</div></div>
    <div class="stat"><div class="v">${fmt(a.realised_gain)}</div><div class="l">realised gain (test)</div></div>` +
    (a.coalitions && a.coalitions.length ? `<div class="stat"><div class="v">${a.coalitions.filter((c) => c.length > 1).length}</div><div class="l">φ-web coalitions</div></div>
    <div class="stat"><div class="v">${a.deviations}</div><div class="l">best-response moves</div></div>
    <div class="stat"><div class="v">${a.conceded.length}</div><div class="l">coalition concessions</div></div>` : "");
  view.appendChild(stats);

  const cols = el("div", { class: "two-col" });
  const left = el("div"), right = el("div");
  cols.append(left, right);
  view.appendChild(cols);
  const regLegend = Array.from({ length: k }, (_, i) => `<span><i style="background:${regShade(i, k)};border-color:${regShade(i, k)}"></i>r${i}</span>`).join("");
  left.appendChild(el("div", { class: "legend" }, `${regLegend}<span><i style="background:#fff;border-style:dashed;border-color:#DC2626"></i>spilled to its frame slot</span>`));
  const canvas = makeCanvas(left, "Interference graph · drag to pan · scroll to zoom");
  const n = nodes.length;
  const R = Math.max(150, n * 9.5);
  const P = new Map();
  const order = f.chordal.mcs_order;
  order.forEach((v, i) => {
    const ang = (2 * Math.PI * i) / Math.max(1, n) - Math.PI / 2;
    P.set(v, { x: R + R * Math.cos(ang) + 60, y: R + R * Math.sin(ang) + 30 });
  });
  const gain = (v) => (a.bids && a.bids[v] !== undefined ? a.bids[v] : a.gains[v] || 0);
  const maxGain = Math.max(1, ...nodes.map((v) => a.gains[v] || 0));
  const eg = svg("g"), ng = svg("g");
  canvas.g.append(eg, ng);
  const edgeEls = [];
  for (const [u, v] of edges) {
    const p = P.get(u), q = P.get(v);
    const line = svg("line", { class: "ig-edge", x1: p.x, y1: p.y, x2: q.x, y2: q.y });
    line.dataset.u = u; line.dataset.v = v;
    eg.appendChild(line);
    edgeEls.push(line);
  }
  for (const v of nodes) {
    const p = P.get(v);
    const reg = a.registers[v];
    const spilled = !reg;
    const g = svg("g", { class: "ig-node" + (spilled ? " spilled" : ""), transform: `translate(${p.x},${p.y})` });
    const rad = 9 + 9 * Math.sqrt(Math.max(0, a.gains[v] || 0) / maxGain);
    g.appendChild(svg("circle", { r: rad, fill: spilled ? "#fff" : regShade(parseInt(reg.slice(1), 10), k) }));
    if (reg) g.appendChild(svg("text", { class: "inside", "text-anchor": "middle", y: 3.5 }, reg));
    const ang = Math.atan2(p.y - (R + 30), p.x - (R + 60));
    g.appendChild(svg("text", { x: Math.cos(ang) * (rad + 6), y: Math.sin(ang) * (rad + 6) + 3, "text-anchor": Math.cos(ang) > 0.2 ? "start" : Math.cos(ang) < -0.2 ? "end" : "middle" }, v));
    g.addEventListener("mouseenter", (e) => {
      edgeEls.forEach((l) => l.classList.toggle("hot", l.dataset.u === v || l.dataset.v === v));
      showTip(e, `${v}\n${reg ? "register " + reg : "spilled"}\nMDP gain ${fmt(a.gains[v] || 0, 1)}${a.bids && a.bids[v] !== undefined ? "\ncoalition bid " + fmt(a.bids[v], 1) : ""}`);
    });
    g.addEventListener("mouseleave", () => { edgeEls.forEach((l) => l.classList.remove("hot")); hideTip(); });
    g.addEventListener("mousedown", (e) => e.stopPropagation());
    ng.appendChild(g);
  }
  canvas.fit(2 * R + 160, 2 * R + 80);

  const sorted = nodes.slice().sort((x, y) => gain(y) - gain(x));
  const rows = sorted.map((v) => `<tr><td class="mono">${esc(v)}</td><td class="num">${fmt(a.gains[v] ?? 0, 1)}</td><td class="num">${a.bids && a.bids[v] !== undefined ? fmt(a.bids[v], 1) : "–"}</td><td class="num">${a.live_range_blocks[v] ?? "–"}</td><td class="num">${a.sweeps[v] ?? "–"}</td><td class="mono">${a.registers[v] ? `<span class="reg-chip" style="background:${regShade(parseInt(a.registers[v].slice(1), 10), k)}">${a.registers[v]}</span>` : '<span class="slot-chip">slot</span>'}</td></tr>`).join("");
  const box = el("div", { class: "scroll-box" });
  box.appendChild(el("table", { class: "grid" }, `<thead><tr><th>Value</th><th class="num">G(v)</th><th class="num">Bid</th><th class="num">Live blocks</th><th class="num">PI rounds</th><th>Location</th></tr></thead><tbody>${rows}</tbody>`));
  right.appendChild(el("div", { class: "caption", style: "margin:0 0 8px" }, state.allocator === "linearscan"
    ? "Linear scan does not use gains; intervals are allocated in start order and the furthest-ending interval is spilled."
    : "G(v): expected residency gain from the per-value MDP (policy iteration). Bid: the coalition's total for loop-carried φ-webs."));
  right.appendChild(box);

  if (a.auction && a.auction.length) {
    const card = el("div", { class: "card", style: "margin-top:14px" });
    card.appendChild(el("div", { class: "card-head" }, `<span class="title">Sealed-bid auction rounds</span><span class="muted">${a.auction.length} contested cliques, processed in MCS order</span>`));
    const list = el("div", { class: "auction scroll-box", style: "max-height:300px;border:0;border-radius:0" });
    for (const r of a.auction) {
      list.appendChild(el("div", { class: "round" }, `When <b class="mono">${esc(r.value)}</b> arrives, its clique exceeds k:<div class="bids">` +
        r.contenders.map((c) => `<span class="bid ${c.wins ? "win" : "lose"}">${esc(c.value)} ${fmt(c.bid, 0)}</span>`).join("") + "</div>"));
    }
    card.appendChild(list);
    view.appendChild(card);
  }
  const mcs = el("div", { class: "card", style: "margin-top:14px" });
  mcs.appendChild(el("div", { class: "card-head" }, `<span class="title">Perfect elimination ordering</span><span class="muted">reverse of Maximum Cardinality Search</span>`));
  mcs.appendChild(el("div", { class: "card-body mono", style: "font-size:12px;line-height:1.8" }, f.chordal.peo.map(esc).join(" → ")));
  view.appendChild(mcs);
}

/* ------------------------------------------------------------------ target code */
function renderAsm(view) {
  if (needsBackEnd(view)) return;
  const t = state.report.targets[state.allocator];
  const rows = t.asm.map((r) => ({ text: r.text, line: r.line, tag: r.tag && r.tag !== "phi" && r.tag !== "param" && r.tag !== "arg" ? r.tag : null, ir: r.ir, kind: r.text.endsWith(":") ? "label" : "" }));
  const s = t.stats;
  const stats = el("div", { class: "stats" });
  stats.innerHTML = `<div class="stat"><div class="v">${fmt(s.code_size)}</div><div class="l">instructions (static)</div></div>
    <div class="stat"><div class="v">${fmt(s.cycles)}</div><div class="l">cycles (test run)</div></div>
    <div class="stat"><div class="v">${fmt(s.spill_memops)}</div><div class="l">spill loads + stores</div></div>
    <div class="stat"><div class="v">${pct(s.register_utilization)}</div><div class="l">register utilisation</div></div>`;
  view.appendChild(stats);
  listingView(view, "asm:" + state.allocator, rows, {
    leading: [allocatorSelect(rerender)],
    caption: "PG-RISC assembly: φ-functions become parallel copies, spilled values live in fp-relative slots, caller-saved registers are saved around calls. Hover a line to see the IR it came from.",
  });
}

/* ------------------------------------------------------------------ run & metrics */
function renderRun(view) {
  if (needsBackEnd(view)) return;
  const r = state.report;
  const ex = r.execution;
  const card = el("div", { class: "card" });
  card.appendChild(el("div", { class: "card-head" }, `<span class="title">Reference interpreter</span><span class="muted">${fmt(ex.test.steps)} IR instructions executed</span>`));
  const body = el("div", { class: "card-body" });
  body.appendChild(el("div", { class: "output" }, ex.test.error ? "runtime error: " + esc(ex.test.error) : (ex.test.output.join("\n") || "(no output)") + `\n→ main returned ${ex.test.return_value}`));
  card.appendChild(body);
  view.appendChild(card);

  const names = state.allocatorNames;
  const keys = Object.keys(r.targets);
  const best = Math.min(...keys.map((k) => r.targets[k].stats.cycles));
  const rows = keys.map((k) => {
    const s = r.targets[k].stats;
    return `<tr class="${s.cycles === best ? "best" : ""}"><td>${esc(names[k] || k)}</td><td class="num">${fmt(s.cycles)}</td><td class="num">${fmt(s.instructions)}</td><td class="num">${fmt(s.loads)}</td><td class="num">${fmt(s.stores)}</td><td class="num">${fmt(s.spill_memops)}</td><td class="num">${fmt(s.save_restore)}</td><td class="num">${pct(s.register_utilization)}</td><td class="num">${fmt(s.code_size)}</td><td class="num">${fmt(s.static_spills)}</td><td class="num">${fmt(s.realised_gain)}</td><td>${s.matches_reference ? "✓ matches" : "✗ " + esc(s.error || "differs")}</td></tr>`;
  }).join("");
  const t = el("div", { class: "card" });
  t.appendChild(el("div", { class: "card-head" }, `<span class="title">Simulated PG-RISC execution, k = ${r.options.k}</span><span class="muted">profile: training input · measured: test input</span>`));
  const scroll = el("div", { style: "overflow:auto" });
  scroll.appendChild(el("table", { class: "grid" }, `<thead><tr><th>Allocator</th><th class="num">Cycles</th><th class="num">Instrs</th><th class="num">Loads</th><th class="num">Stores</th><th class="num">Spill mem-ops</th><th class="num">Save/restore</th><th class="num">Reg. util.</th><th class="num">Code size</th><th class="num">Spilled values</th><th class="num">Realised gain</th><th>Output</th></tr></thead><tbody>${rows}</tbody>`));
  t.appendChild(scroll);
  view.appendChild(t);

  for (const [metric, label, invert] of [["cycles", "Cycles (lower is better)", false], ["spill_memops", "Spill memory operations (lower is better)", false], ["realised_gain", "Realised expected gain (higher is better)", true]]) {
    const c = el("div", { class: "card" });
    c.appendChild(el("div", { class: "card-head" }, `<span class="title">${label}</span>`));
    const bars = el("div", { class: "card-body bars" });
    const vals = keys.map((k) => r.targets[k].stats[metric]);
    const max = Math.max(1, ...vals);
    keys.forEach((k, i) => {
      const row = el("div", { class: "bar-row" });
      row.innerHTML = `<span>${esc(names[k] || k)}</span><div class="bar-track"><div class="bar-fill a-${esc(k)}" style="width:${(100 * vals[i] / max).toFixed(1)}%"></div></div><span class="val">${fmt(vals[i])}</span>`;
      bars.appendChild(row);
    });
    c.appendChild(bars);
    view.appendChild(c);
  }
  const outCard = el("div", { class: "card" });
  outCard.appendChild(el("div", { class: "card-head" }, `<span class="title">Program output on the simulated target (${esc(names[state.allocator])})</span>`));
  const s = r.targets[state.allocator].stats;
  outCard.appendChild(el("div", { class: "card-body" }, `<div class="output">${s.error ? "runtime error: " + esc(s.error) : esc(s.output.join("\n") || "(no output)")}</div>`));
  view.appendChild(outCard);
}

/* ------------------------------------------------------------------ grammar */
function renderGrammar(view) {
  const g = state.report.grammar;
  const stats = el("div", { class: "stats" });
  stats.innerHTML = `<div class="stat"><div class="v">${g.productions.length}</div><div class="l">productions</div></div>
    <div class="stat"><div class="v">${g.nonterminals.length}</div><div class="l">nonterminals</div></div>
    <div class="stat"><div class="v">${g.terminals.length}</div><div class="l">terminals</div></div>
    <div class="stat"><div class="v">${g.table.length}</div><div class="l">LL(1) table entries</div></div>
    <div class="stat"><div class="v">${g.conflicts.length}</div><div class="l">conflicts</div></div>`;
  view.appendChild(stats);
  view.appendChild(el("div", { class: "caption" }, g.is_ll1_modulo_dangling_else
    ? "The grammar is LL(1) except for the classical dangling-else conflict on (ElsePart, else), resolved by binding else to the nearest if."
    : "The grammar has LL(1) conflicts."));
  const cols = el("div", { class: "two-col" });
  const left = el("div", { class: "card" });
  left.appendChild(el("div", { class: "card-head" }, `<span class="title">Productions</span>`));
  left.appendChild(el("div", { class: "card-body mono", style: "font-size:12px;line-height:1.7;white-space:pre-wrap" }, g.productions.map((p, i) => `${String(i + 1).padStart(2, " ")}  ${esc(p)}`).join("\n")));
  const right = el("div", { class: "card" });
  right.appendChild(el("div", { class: "card-head" }, `<span class="title">FIRST and FOLLOW sets</span>`));
  const rows = g.nonterminals.map((a) => `<tr><td class="mono"><b>${esc(a)}</b></td><td class="mono">{ ${g.first[a].map(esc).join(", ")} }</td><td class="mono">{ ${g.follow[a].map(esc).join(", ")} }</td></tr>`).join("");
  const box = el("div", { style: "overflow:auto" });
  box.appendChild(el("table", { class: "grid" }, `<thead><tr><th>Nonterminal</th><th>FIRST</th><th>FOLLOW</th></tr></thead><tbody>${rows}</tbody>`));
  right.appendChild(box);
  cols.append(left, right);
  view.appendChild(cols);
}

/* ------------------------------------------------------------------ boot */
function loadExample(name) {
  const ex = state.examples.find((e) => e.name === name);
  if (!ex) return;
  src.value = ex.source;
  $("#train").value = ex.train.join(" ");
  $("#test").value = ex.test.join(" ");
  state.steps = {};
  state.astCollapsed.clear();
  refreshEditor();
  compileNow();
}

async function boot() {
  refreshEditor();
  try {
    const res = await fetch("/api/examples");
    const data = await res.json();
    state.examples = data.examples;
    state.allocatorNames = data.allocators;
    const sel = $("#example");
    for (const ex of state.examples) sel.appendChild(el("option", { value: ex.name }, esc(ex.title)));
    sel.appendChild(el("option", { value: "__custom" }, "Custom (keep editor)"));
    sel.addEventListener("change", () => { if (sel.value !== "__custom") loadExample(sel.value); });
    const start = state.examples.find((e) => e.name === "05_rarebranch") || state.examples[0];
    sel.value = start.name;
    loadExample(start.name);
  } catch (err) {
    setStatus("err", "Server unreachable");
  }
}
window.addEventListener("resize", () => { state.rendered[state.tab] = false; renderActive(); });
boot();
