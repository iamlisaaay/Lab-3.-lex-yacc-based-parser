/* MiniC web UI: редактор, візуалізація AST (d3.js), результати трансляції. */
'use strict';

const CAT_COLORS = {
  program: '--c-program', func: '--c-func', decl: '--c-decl', stmt: '--c-stmt',
  expr: '--c-expr', id: '--c-id', literal: '--c-literal', stack: '--c-stack',
};
const CAT_NAMES = {
  program: 'програма', func: 'функція', decl: 'оголошення', stmt: 'оператор',
  expr: 'вираз', id: 'ідентифікатор', literal: 'літерал', stack: 'стек LR',
};
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = sel => document.querySelector(sel);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

let state = { result: null, examples: [], orient: 'vertical', anim: null };

/* ------------------------------------------------------------------ редактор */
const editor = CodeMirror.fromTextArea($('#code'), {
  mode: 'text/x-csrc', theme: 'material-darker', lineNumbers: true, matchBrackets: true,
  indentUnit: 4, tabSize: 4, gutters: ['CodeMirror-linenumbers', 'diag-gutter'],
  extraKeys: { 'Ctrl-Enter': compile, 'Cmd-Enter': compile },
});
const viewers = {};
for (const [key, mode] of [['python', 'python'], ['js', 'javascript'], ['tac', null]]) {
  viewers[key] = CodeMirror($('#view-' + key), {
    mode, theme: 'material-darker', lineNumbers: true, readOnly: true, value: '',
  });
}
let markedLines = [];
editor.on('cursorActivity', () => {
  const c = editor.getCursor();
  $('#cursor-pos').textContent = `рядок ${c.line + 1}, стовпець ${c.ch + 1}`;
  highlightAstLine(c.line + 1);
});
editor.on('change', () => { try { localStorage.setItem('minic-code', editor.getValue()); } catch (e) { /* ignore */ } });

/* ------------------------------------------------------------------ вкладки */
document.querySelectorAll('#tabs button').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
function showTab(name) {
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === 'pane-' + name));
  if (viewers[name]) setTimeout(() => viewers[name].refresh(), 0);
  if (name === 'ast' && astRoot) setTimeout(fitTree, 0);
  try { localStorage.setItem('minic-tab', name); } catch (e) { /* ignore */ }
}

/* ------------------------------------------------------------------ приклади */
async function loadExamples() {
  const r = await fetch('/api/examples');
  state.examples = await r.json();
  const sel = $('#examples');
  sel.innerHTML = '<option value="">— приклади —</option>' +
    state.examples.map((e, i) => `<option value="${i}">${esc(e.name)} — ${esc(e.title.slice(0, 48))}</option>`).join('');
  sel.addEventListener('change', () => {
    if (sel.value === '') return;
    editor.setValue(state.examples[+sel.value].code);
    compile();
  });
  let saved = null;
  try { saved = localStorage.getItem('minic-code'); } catch (e) { /* ignore */ }
  editor.setValue(saved || (state.examples[1] || state.examples[0]).code);
  compile();
}

/* ------------------------------------------------------------------ компіляція */
$('#btn-compile').addEventListener('click', compile);
async function compile() {
  const btn = $('#btn-compile');
  btn.disabled = true; btn.textContent = '… компіляція';
  try {
    const r = await fetch('/api/compile', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: editor.getValue(), trace: $('#opt-trace').checked }),
    });
    const res = await r.json();
    state.result = res;
    render(res);
  } catch (e) {
    $('#diagnostics').innerHTML = `<div class="diag error"><span class="ic">✖</span>Сервер недоступний: ${esc(e.message)}. Запустіть: python minic.py --serve</div>`;
  } finally {
    btn.disabled = false; btn.textContent = '▶ Компілювати і запустити';
  }
}

function render(res) {
  renderDiagnostics(res);
  renderPills(res);
  stopAnim();
  if (res.ast) renderAST(res.ast); else clearAST();
  renderOutputs(res);
  renderCode(res);
  renderTokens(res.tokens || []);
  renderSymbols(res.symbols || []);
  renderTrace(res.trace || []);
}

function renderPills(res) {
  const t = res.timings || {};
  const pills = [
    ['токенів', (res.tokens || []).length],
    ['вузлів AST', res.stats && res.stats.ast_nodes || 0],
    ['кроків LR', (res.trace || []).length || '—'],
    ['помилок', res.errors.length, res.errors.length ? 'bad' : 'ok'],
    ['час', (t.total_ms || 0) + ' мс'],
  ];
  $('#pills').innerHTML = pills.map(([k, v, c]) => `<span class="pill ${c || ''}">${k}: <b>${v}</b></span>`).join('');
}

function renderDiagnostics(res) {
  editor.clearGutter('diag-gutter');
  markedLines.forEach(l => { editor.removeLineClass(l, 'background', 'line-error'); editor.removeLineClass(l, 'background', 'line-warn'); });
  markedLines = [];
  const items = [...res.errors.map(e => ({ ...e, sev: 'error' })), ...res.warnings.map(e => ({ ...e, sev: 'warn' }))];
  if (res.runtime_error) items.unshift({ ...res.runtime_error, sev: 'error' });
  const box = $('#diagnostics');
  $('#diag-count').textContent = `${res.errors.length} помилок, ${res.warnings.length} попереджень`;
  if (!items.length) {
    box.innerHTML = '<div class="diag ok">✔ Програма синтаксично і семантично коректна</div>';
    return;
  }
  box.innerHTML = items.map((e, i) =>
    `<div class="diag ${e.sev}" data-i="${i}"><span class="ic">${e.sev === 'error' ? '✖' : '⚠'}</span>` +
    `<span class="ph">${esc(e.phase)}</span><span>${e.line ? 'рядок ' + e.line + ': ' : ''}${esc(e.msg)}</span></div>`).join('');
  box.querySelectorAll('.diag').forEach(el => el.addEventListener('click', () => {
    const e = items[+el.dataset.i];
    if (e.line) { editor.setCursor({ line: e.line - 1, ch: Math.max(0, (e.col || 1) - 1) }); editor.focus(); }
  }));
  for (const e of [...items].reverse()) {          // помилки малюються останніми (поверх попереджень)
    if (!e.line) continue;
    const ln = e.line - 1;
    editor.addLineClass(ln, 'background', e.sev === 'error' ? 'line-error' : 'line-warn');
    markedLines.push(ln);
    const m = document.createElement('span');
    m.className = 'gutter-err'; m.textContent = e.sev === 'error' ? '●' : '▲'; m.title = e.msg;
    m.style.color = e.sev === 'error' ? css('--err') : css('--warn');
    editor.setGutterMarker(ln, 'diag-gutter', m);
  }
}

/* ------------------------------------------------------------------ виконання */
function runJS(code) {
  let out = '';
  globalThis.__minic_sink = s => { out += s; };
  try {
    (new Function(code))();
    return { output: out };
  } catch (e) {
    return { output: out, error: e.message };
  } finally {
    delete globalThis.__minic_sink;
  }
}

function setBadge(id, cls, text) { const b = $(id); b.className = 'badge ' + cls; b.textContent = text; }

function renderOutputs(res) {
  const interp = res.output;
  const pre = $('#out-interp');
  if (!res.ok) {
    pre.innerHTML = '<span class="rt-err">Компіляцію зупинено через помилки (див. «Діагностика»)</span>';
    setBadge('#badge-interp', 'bad', 'помилки');
  } else {
    pre.innerHTML = esc(interp || '') + (res.runtime_error ? `\n<span class="rt-err">Помилка виконання (рядок ${res.runtime_error.line}): ${esc(res.runtime_error.msg)}</span>` : '');
    setBadge('#badge-interp', res.runtime_error ? 'bad' : 'ok', 'exit ' + res.exit_code);
  }
  // Python
  const py = $('#out-py');
  if (res.codegen_errors && res.codegen_errors.python) {
    py.innerHTML = `<span class="rt-err">Трансляція неможлива: ${esc(res.codegen_errors.python.msg)}</span>`;
    setBadge('#badge-py', 'na', 'n/a');
  } else if (res.python_run) {
    const pr = res.python_run;
    py.innerHTML = esc(pr.output) + (pr.error ? `\n<span class="rt-err">${esc(pr.error)}</span>` : '');
    const same = pr.output === interp;
    setBadge('#badge-py', same ? 'ok' : 'bad', same ? '✔ збігається' : '✖ відрізняється');
  } else { py.textContent = ''; setBadge('#badge-py', 'na', '—'); }
  // JavaScript – виконується прямо тут, у браузері
  const jsPre = $('#out-js');
  if (res.codegen_errors && res.codegen_errors.js) {
    jsPre.innerHTML = `<span class="rt-err">Трансляція неможлива: ${esc(res.codegen_errors.js.msg)}</span>`;
    setBadge('#badge-js', 'na', 'n/a');
  } else if (res.ok && res.code.js && !(res.runtime_error && /ліміт кроків/.test(res.runtime_error.msg))) {
    const t0 = performance.now();
    const r = runJS(res.code.js);
    const dt = (performance.now() - t0).toFixed(1);
    jsPre.innerHTML = esc(r.output) + (r.error ? `\n<span class="rt-err">${esc(r.error)}</span>` : '');
    const same = r.output === interp;
    setBadge('#badge-js', same ? 'ok' : 'bad', (same ? '✔ збігається' : '✖ відрізняється') + ` · ${dt} мс`);
  } else { jsPre.textContent = ''; setBadge('#badge-js', 'na', '—'); }
  const st = res.stats || {}, t = res.timings || {};
  $('#run-stats').textContent = res.ok ?
    `Лексер ${t.lexer_ms} мс · парсер ${t.parser_ms} мс · семантика ${t.semantic_ms} мс · інтерпретація ${t.run_ms} мс · кроків інтерпретатора: ${st.steps} · виклики: ${Object.entries(st.calls || {}).map(([k, v]) => k + '×' + v).join(', ')}` : '';
}

function renderCode(res) {
  for (const k of ['python', 'js', 'tac']) {
    const err = res.codegen_errors && res.codegen_errors[k];
    viewers[k].setValue(res.code && res.code[k] ? res.code[k] : (err ? '// ' + err.msg : ''));
    const note = $('#note-' + k);
    if (note) {
      note.className = 'muted small' + (err ? ' note-err' : '');
      note.textContent = err ? `⚠ рядок ${err.line}: ${err.msg}` : (res.ok ? 'код виконується: Python – на сервері, JavaScript – у браузері (вкладка «Виконання»)' : '');
    }
    if (k === 'python' || k === 'js') {
      // прокрутка до початку програми (після runtime-бібліотеки)
      const text = viewers[k].getValue();
      const idx = text.split('\n').findIndex(l => l.includes('---------------- program'));
      if (idx > 0) setTimeout(() => viewers[k].scrollIntoView({ line: Math.min(idx + 25, viewers[k].lineCount() - 1), ch: 0 }), 50);
    }
  }
}
document.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', () => {
  navigator.clipboard.writeText(viewers[b.dataset.copy].getValue());
  b.textContent = '✔ скопійовано'; setTimeout(() => (b.textContent = 'Копіювати'), 1200);
}));
document.querySelectorAll('[data-download]').forEach(b => b.addEventListener('click', () => {
  const k = b.dataset.download;
  download(viewers[k].getValue(), { python: 'program.py', js: 'program.js', tac: 'program.tac' }[k], 'text/plain');
}));
function download(text, name, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

/* ------------------------------------------------------------------ токени, символи, протокол */
const KW = new Set(['VOID', 'CHAR', 'SHORT', 'INT', 'LONG', 'FLOAT', 'DOUBLE', 'SIGNED', 'UNSIGNED', 'CONST', 'STATIC', 'EXTERN',
  'IF', 'ELSE', 'WHILE', 'DO', 'FOR', 'SWITCH', 'CASE', 'DEFAULT', 'BREAK', 'CONTINUE', 'RETURN', 'SIZEOF']);
function tokClass(t) {
  if (KW.has(t)) return 'tk-kw';
  if (t === 'ID') return 'tk-id';
  if (/CONST|STRING/.test(t)) return 'tk-const';
  if (/OP|ASSIGN/.test(t) || '=+-*/%<>&|^!~?'.includes(t)) return 'tk-op';
  return 'tk-punct';
}
function renderTokens(tokens) {
  $('#tokens-table').innerHTML = '<tr><th>#</th><th>рядок:ст.</th><th>тип токена</th><th>лексема / значення</th></tr>' +
    tokens.map((t, i) => `<tr data-l="${t.line}" data-c="${t.col}"><td>${i + 1}</td><td>${t.line}:${t.col}</td>` +
      `<td><span class="tk ${tokClass(t.type)}">${esc(t.type)}</span></td><td>${esc(t.value)}</td></tr>`).join('');
  $('#tokens-table').querySelectorAll('tr[data-l]').forEach(tr => tr.addEventListener('click', () => {
    editor.setCursor({ line: tr.dataset.l - 1, ch: tr.dataset.c - 1 }); editor.focus();
  }));
}
function renderSymbols(syms) {
  $('#symbols-table').innerHTML = '<tr><th>область</th><th>вид</th><th>ім\'я</th><th>тип</th><th>рядок</th><th>ім\'я в Python/JS</th></tr>' +
    syms.map(s => `<tr data-l="${s.line}"><td>${esc(s.scope)}</td><td>${esc(s.kind)}</td><td>${esc(s.name)}</td>` +
      `<td>${esc(s.type)}</td><td>${s.line}</td><td>${esc(s.uname)}</td></tr>`).join('');
  $('#symbols-table').querySelectorAll('tr[data-l]').forEach(tr => tr.addEventListener('click', () => {
    editor.setCursor({ line: tr.dataset.l - 1, ch: 0 }); editor.focus();
  }));
}
function renderTrace(steps) {
  const f = $('#trace-filter').value.trim().toLowerCase();
  const onlyReduce = $('#trace-reduce-only').checked;
  const rows = [];
  steps.forEach((s, i) => {
    const a = s.action || '';
    if (onlyReduce && !a.startsWith('reduce')) return;
    const line = `${s.state} ${s.stack} ${s.lookahead} ${a}`.toLowerCase();
    if (f && !line.includes(f) && !(f.startsWith('state ') && s.state === f.slice(6))) return;
    if (rows.length > 2500) return;
    const cls = a.startsWith('shift') ? 'shift' : a.startsWith('reduce') ? 'reduce' : a === 'accept' ? 'accept' : '';
    rows.push(`<tr><td>${i + 1}</td><td>${esc(s.state)}</td><td class="stack" title="${esc(s.stack || '')}"><bdi>${esc(s.stack || '')}</bdi></td>` +
      `<td>${esc(s.lookahead || '')}</td><td class="${cls}" title="${esc(a)}">${esc(a)}</td></tr>`);
  });
  $('#trace-info').textContent = steps.length ? `кроків: ${steps.length}, shift: ${steps.filter(s => (s.action || '').startsWith('shift')).length}, reduce: ${steps.filter(s => (s.action || '').startsWith('reduce')).length}` : 'увімкніть «trace» і перекомпілюйте';
  $('#trace-table').innerHTML = '<colgroup><col style="width:52px"><col style="width:56px"><col><col style="width:22%"><col style="width:34%"></colgroup><tr><th>#</th><th>стан</th><th>стек символів</th><th>lookahead</th><th>дія</th></tr>' + rows.join('');
}
$('#trace-filter').addEventListener('input', () => state.result && renderTrace(state.result.trace || []));
$('#trace-reduce-only').addEventListener('change', () => state.result && renderTrace(state.result.trace || []));

async function loadGrammar() {
  const g = await (await fetch('/api/grammar')).json();
  const cards = [
    ['метод', g.method], ['терміналів', g.terminals.length], ['нетерміналів', g.nonterminals.length],
    ['продукцій', g.n_productions], ['станів LALR', g.n_states],
    ['конфліктів S/R', g.sr_conflicts, g.sr_conflicts === 0], ['конфліктів R/R', g.rr_conflicts, g.rr_conflicts === 0],
  ];
  $('#grammar-stats').innerHTML = cards.map(([k, v, good]) => `<div class="card ${good ? 'good' : ''}"><div class="v">${v}</div><div class="k">${k}</div></div>`).join('') +
    `<div class="card" style="grid-column: span 2"><div class="k">таблиця пріоритетів (%prec)</div><div style="font-family:var(--mono);font-size:12px">${g.precedence.map(p => esc(p.join(' '))).join('<br>')}<br><span class="muted">IFX &lt; ELSE ⇒ «висячий else» → shift</span></div></div>`;
  const nonterms = new Set(g.nonterminals);
  const renderList = () => {
    const f = $('#grammar-filter').value.trim().toLowerCase();
    $('#grammar-list').innerHTML = g.productions.map(p => {
      if (f && !p.toLowerCase().includes(f)) return '';
      const [lhs, rhs] = p.split(' -> ');
      const r = (rhs || '').split(' ').map(s => nonterms.has(s) ? esc(s) : `<span class="t">${esc(s)}</span>`).join(' ');
      return `<li><span class="lhs">${esc(lhs)}</span> → ${r || '<i>ε</i>'}</li>`;
    }).join('');
  };
  $('#grammar-filter').addEventListener('input', renderList);
  renderList();
}

/* ------------------------------------------------------------------ AST (d3.js) */
const svg = d3.select('#ast-view').append('svg');
const gRoot = svg.append('g');
const gLinks = gRoot.append('g');
const gNodes = gRoot.append('g');
const zoom = d3.zoom().scaleExtent([0.08, 3]).on('zoom', ev => gRoot.attr('transform', ev.transform));
svg.call(zoom).on('dblclick.zoom', null);
let astRoot = null;

$('#legend').innerHTML = Object.keys(CAT_NAMES).map(k => `<span><i style="background:${css(CAT_COLORS[k])}"></i>${CAT_NAMES[k]}</span>`).join('') +
  '<span class="muted">· клік – згорнути/розгорнути · колесо – масштаб · перетягування – зсув</span>';

function nodeLabel(d) { return d.data.name; }
function nodeSize(d) {
  const label = nodeLabel(d);
  const w = Math.max(44, Math.min(260, label.length * 7.4 + 22));
  const h = d.data.ctype ? 36 : 26;
  return [w, h];
}
function color(d) { return css(CAT_COLORS[d.data.cat] || '--c-stack'); }

function clearAST() {
  astRoot = null;
  gLinks.selectAll('*').remove(); gNodes.selectAll('*').remove();
  $('#ast-view .placeholder') || d3.select('#ast-view').append('div').attr('class', 'placeholder').text('AST недоступне через синтаксичні помилки');
  const ph = $('#ast-view .placeholder'); if (ph) ph.style.display = 'grid';
}

function renderAST(data, opts = {}) {
  const ph = $('#ast-view .placeholder'); if (ph) ph.style.display = 'none';
  astRoot = d3.hierarchy(data);
  astRoot.each(d => { d.id = d.data.seq; });
  if (!opts.keepAll) {
    // великі дерева спочатку згортаємо на глибині 6
    const n = astRoot.descendants().length;
    if (n > 220) astRoot.each(d => { if (d.depth >= 6 && d.children) { d._children = d.children; d.children = null; } });
  }
  update(astRoot, true);
}

function layout(root) {
  const vertical = state.orient === 'vertical';
  root.each(d => { [d.w, d.h] = nodeSize(d); });
  let tree;
  if (vertical) {
    tree = d3.tree().nodeSize([1, 78]).separation((a, b) => (a.w + b.w) / 2 + (a.parent === b.parent ? 14 : 30));
  } else {
    const maxW = d3.max(root.descendants(), d => d.w);
    tree = d3.tree().nodeSize([1, Math.min(300, maxW + 50)]).separation((a, b) => (a.h + b.h) / 2 + (a.parent === b.parent ? 8 : 18));
  }
  tree(root);
  root.each(d => {
    if (vertical) { d.px = d.x; d.py = d.y; } else { d.px = d.y; d.py = d.x; }
  });
}

function linkPath(s, t) {
  if (state.orient === 'vertical') {
    const y1 = s.py + s.h / 2, y2 = t.py - t.h / 2, my = (y1 + y2) / 2;
    return `M${s.px},${y1}C${s.px},${my} ${t.px},${my} ${t.px},${y2}`;
  }
  const x1 = s.px + s.w / 2, x2 = t.px - t.w / 2, mx = (x1 + x2) / 2;
  return `M${x1},${s.py}C${mx},${s.py} ${mx},${t.py} ${x2},${t.py}`;
}

function update(root, fit, freshIds) {
  layout(root);
  const nodes = root.descendants();
  const links = root.links();
  const dur = fit ? 0 : 350;

  const link = gLinks.selectAll('path.link').data(links, d => d.target.id);
  link.exit().remove();
  link.enter().append('path').attr('class', 'link')
    .attr('d', d => linkPath(d.source, d.source.data._fake ? d.target : d.source))
    .merge(link).attr('stroke-dasharray', d => d.source.data._fake ? '4 4' : null)
    .transition().duration(dur).attr('d', d => linkPath(d.source, d.target));

  const node = gNodes.selectAll('g.node').data(nodes, d => d.id);
  node.exit().transition().duration(dur / 2).style('opacity', 0).remove();
  const enter = node.enter().append('g').attr('class', 'node')
    .attr('transform', d => { const p = d.parent || d; return `translate(${p.px},${p.py})`; })
    .style('opacity', 0)
    .on('click', (ev, d) => onNodeClick(d))
    .on('mousemove', (ev, d) => showTip(ev, d))
    .on('mouseleave', hideTip);
  enter.append('rect');
  enter.append('text').attr('class', 'main').attr('text-anchor', 'middle');
  enter.append('text').attr('class', 'sub').attr('text-anchor', 'middle');
  enter.append('text').attr('class', 'role').attr('text-anchor', 'middle');
  enter.append('text').attr('class', 'badge-count').attr('text-anchor', 'start');

  const all = enter.merge(node);
  all.classed('collapsed', d => !!d._children)
    .classed('fresh', d => !!(freshIds && freshIds.has(d.id)));
  all.select('rect')
    .attr('x', d => -d.w / 2).attr('y', d => -d.h / 2).attr('width', d => d.w).attr('height', d => d.h)
    .attr('fill', d => d3.color(color(d)).darker(2.4).copy({ opacity: 0.92 }))
    .attr('stroke', d => color(d));
  all.select('text.main').text(nodeLabel).attr('y', d => d.data.ctype ? -2 : 4);
  all.select('text.sub').text(d => d.data.ctype ? ': ' + d.data.ctype : '').attr('y', 12);
  all.select('text.role').text(d => d.data.role || '')
    .attr('y', d => state.orient === 'vertical' ? -d.h / 2 - 4 : -d.h / 2 - 3)
    .attr('x', 0);
  all.select('text.badge-count').text(d => d._children ? '+' + countDesc(d) : '')
    .attr('x', d => d.w / 2 + 4).attr('y', 4);
  all.transition().duration(dur).style('opacity', 1).attr('transform', d => `translate(${d.px},${d.py})`);
  if (fit) setTimeout(fitTree, 0);
}

function countDesc(d) { let n = 0; (d._children || []).forEach(c => { n += 1; c.each(() => n++); n--; }); return n; }

function onNodeClick(d) {
  if (state.anim && state.anim.timer) return;
  if (d.children) { d._children = d.children; d.children = null; }
  else if (d._children) { d.children = d._children; d._children = null; }
  update(astRoot, false);
  if (d.data.line) {
    editor.setCursor({ line: d.data.line - 1, ch: 0 });
    editor.scrollIntoView({ line: d.data.line - 1, ch: 0 }, 80);
  }
}

function highlightAstLine(line) {
  gNodes.selectAll('g.node').classed('hl', d => d.data.line === line && d.data.kind !== 'Program');
}

const tip = $('#tooltip');
function showTip(ev, d) {
  const a = d.data;
  let s = `<b>${esc(a.kind)}</b>  <span class="muted">(${esc(CAT_NAMES[a.cat] || a.cat)})</span>`;
  if (a.role) s += `\nроль у батьку: ${esc(a.role)}`;
  if (a.ctype) s += `\nтип: ${esc(a.ctype)}`;
  if (a.attrs) for (const [k, v] of Object.entries(a.attrs)) s += `\n${esc(k)} = ${esc(v)}`;
  if (a.line) s += `\nрядок: ${a.line}`;
  s += `\nпорядок створення (згортка №): ${a.seq}`;
  const kids = (d.children || d._children || []).length;
  if (kids) s += `\nнащадків: ${kids}${d._children ? ' (згорнуто)' : ''}`;
  tip.innerHTML = s; tip.style.display = 'block';
  tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - 370) + 'px';
  tip.style.top = (ev.clientY + 14) + 'px';
}
function hideTip() { tip.style.display = 'none'; }

function fitTree() {
  if (!astRoot) return;
  const box = gRoot.node().getBBox();
  const el = $('#ast-view');
  const W = el.clientWidth, H = el.clientHeight;
  if (!box.width || !W) return;
  const k = Math.min(1.2, 0.92 * Math.min(W / box.width, H / box.height));
  const tx = W / 2 - k * (box.x + box.width / 2), ty = Math.max(20, H / 2 - k * (box.y + box.height / 2));
  svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k));
}

$('#ast-fit').addEventListener('click', fitTree);
$('#ast-expand').addEventListener('click', () => {
  if (state.anim) stopAnim();
  if (!astRoot) return;
  astRoot.each(d => { if (d._children) { d.children = d._children; d._children = null; } });
  (function expandAll(d) { if (d._children) { d.children = d._children; d._children = null; } (d.children || []).forEach(expandAll); })(astRoot);
  update(astRoot, true);
});
$('#ast-collapse').addEventListener('click', () => {
  if (state.anim) stopAnim();
  if (!astRoot) return;
  (function expandAll(d) { if (d._children) { d.children = d._children; d._children = null; } (d.children || []).forEach(expandAll); })(astRoot);
  astRoot.each(d => { if (d.depth >= 3 && d.children) { d._children = d.children; d.children = null; } });
  update(astRoot, true);
});
$('#ast-orient').addEventListener('click', () => {
  state.orient = state.orient === 'vertical' ? 'horizontal' : 'vertical';
  if (astRoot) update(astRoot, true);
});
$('#ast-svg').addEventListener('click', () => {
  const clone = svg.node().cloneNode(true);
  const box = gRoot.node().getBBox();
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('viewBox', `${box.x - 20} ${box.y - 20} ${box.width + 40} ${box.height + 40}`);
  clone.setAttribute('width', box.width + 40); clone.setAttribute('height', box.height + 40);
  clone.querySelector('g').removeAttribute('transform');
  const style = `<style>.link{fill:none;stroke:#3a4458;stroke-width:1.4px}text{font-family:Consolas,monospace;font-size:12px;fill:#e6e9f0}text.sub{font-size:10px;fill:#8a93a6}text.role{font-size:9.5px;fill:#6b7488;font-style:italic}</style><rect x="${box.x - 20}" y="${box.y - 20}" width="${box.width + 40}" height="${box.height + 40}" fill="#0f1117"/>`;
  clone.insertAdjacentHTML('afterbegin', style);
  download(new XMLSerializer().serializeToString(clone), 'ast.svg', 'image/svg+xml');
});

/* ------------------------------------------------------------------ анімація побудови знизу-вгору */
/* LALR-аналізатор створює вузли під час згорток (reduce). Порядок створення (seq) показує,
   як із «лісу» піддерев на стеку поступово складається одне дерево – корінь з'являється останнім. */
function flatten(data) {
  const list = [];
  (function walk(n, parent) {
    const item = { data: n, parent, kids: [] };
    list.push(item);
    if (parent) parent.kids.push(item);
    (n.children || []).forEach(c => walk(c, item));
  })(data, null);
  return list;
}

function buildForest(flat, upto) {
  const visible = new Set(flat.filter(x => x.data.seq <= upto));
  const clone = x => {
    const { children, ...rest } = x.data;
    const kids = x.kids.filter(k => visible.has(k)).map(clone);
    return kids.length ? { ...rest, children: kids } : { ...rest };
  };
  const roots = [...visible].filter(x => !x.parent || !visible.has(x.parent)).sort((a, b) => a.data.seq - b.data.seq);
  if (roots.length === 1 && !roots[0].parent) return clone(roots[0]);
  return { name: `стек LR: ${roots.length} піддерев`, kind: 'Stack', cat: 'stack', seq: 0, _fake: true, children: roots.map(clone) };
}

function animStep(i) {
  const a = state.anim;
  const seq = a.seqs[i];
  $('#anim-slider').value = i;
  const forest = buildForest(a.flat, seq);
  astRoot = d3.hierarchy(forest);
  astRoot.each(d => { d.id = d.data.seq; });
  const item = a.flat.find(x => x.data.seq === seq);
  update(astRoot, false, new Set([seq]));
  $('#anim-caption').textContent = `згортка ${i + 1}/${a.seqs.length}: створено ${item.data.kind}` + (item.data.line ? ` (рядок ${item.data.line})` : '');
  if (item.data.line) editor.setCursor({ line: item.data.line - 1, ch: 0 });
  if (i % 6 === 0) fitTree();
}

$('#anim-play').addEventListener('click', () => {
  if (!state.result || !state.result.ast) return;
  if (state.anim && state.anim.timer) {          // пауза
    clearInterval(state.anim.timer); state.anim.timer = null;
    $('#anim-play').textContent = '▶ Продовжити';
    return;
  }
  const flat = flatten(state.result.ast);
  const seqs = flat.map(x => x.data.seq).sort((a, b) => a - b);
  const slider = $('#anim-slider');
  slider.max = seqs.length - 1;
  state.anim = { flat, seqs, i: state.anim ? state.anim.i : 0 };
  if (state.anim.i >= seqs.length - 1) state.anim.i = 0;
  $('#anim-play').textContent = '⏸ Пауза';
  const delay = Math.max(40, Math.min(260, 9000 / seqs.length));
  state.anim.timer = setInterval(() => {
    const a = state.anim;
    animStep(a.i);
    a.i++;
    if (a.i >= a.seqs.length) { clearInterval(a.timer); a.timer = null; $('#anim-play').textContent = '▶ Побудова знизу-вгору'; setTimeout(fitTree, 400); }
  }, delay);
});
$('#anim-slider').addEventListener('input', ev => {
  if (!state.result || !state.result.ast) return;
  if (!state.anim) {
    const flat = flatten(state.result.ast);
    state.anim = { flat, seqs: flat.map(x => x.data.seq).sort((a, b) => a - b), i: 0 };
    $('#anim-slider').max = state.anim.seqs.length - 1;
  }
  if (state.anim.timer) { clearInterval(state.anim.timer); state.anim.timer = null; $('#anim-play').textContent = '▶ Побудова знизу-вгору'; }
  state.anim.i = +ev.target.value;
  animStep(state.anim.i);
});
function stopAnim() {
  if (state.anim && state.anim.timer) clearInterval(state.anim.timer);
  const wasAnim = !!state.anim;
  state.anim = null;
  $('#anim-play').textContent = '▶ Побудова знизу-вгору';
  $('#anim-caption').textContent = '';
  if (wasAnim && state.result && state.result.ast) renderAST(state.result.ast);
}
svg.on('dblclick', () => { if (state.anim && !state.anim.timer) stopAnim(); });

window.addEventListener('resize', () => { if (astRoot) fitTree(); });

/* ------------------------------------------------------------------ старт */
loadExamples();
loadGrammar();
let savedTab = null;
try { savedTab = localStorage.getItem('minic-tab'); } catch (e) { /* ignore */ }
if (savedTab && document.querySelector(`#tabs [data-tab="${savedTab}"]`)) showTab(savedTab);
