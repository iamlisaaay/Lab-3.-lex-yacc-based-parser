"""Рантайм-бібліотеки для згенерованого коду (Python та JavaScript).

Один і той самий Python-код PY_RUNTIME:
  * вставляється на початок кожної згенерованої Python-програми;
  * виконується тут через exec(), щоб інтерпретатор AST використовував ту саму
    реалізацію printf – це гарантує однаковий вивід інтерпретатора і транслятора.
"""

PY_RUNTIME = r'''
import math as _rt_math
import re as _rt_re
import sys as _rt_sys

_RT_SPEC = _rt_re.compile(r'%([-+ #0]*)(\*|\d+)?(?:\.(\*|\d*))?(hh|h|ll|l|L|z|j|t)?([diouxXeEfFgGcsp%])')


def _rt_cstr(v):
    """C-рядок (str або список кодів, що закінчується 0) -> str."""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        out = []
        for c in v:
            if c == 0:
                break
            out.append(chr(c))
        return ''.join(out)
    return str(v)


def _rt_format(fmt, args):
    """Реалізація форматування printf з C."""
    fmt = _rt_cstr(fmt)
    args = list(args)
    res, pos, ai = [], 0, 0
    for m in _RT_SPEC.finditer(fmt):
        res.append(fmt[pos:m.start()])
        pos = m.end()
        flags, width, prec, length, conv = m.groups()
        if conv == '%':
            res.append('%')
            continue
        if width == '*':
            width = str(int(args[ai])); ai += 1
        if prec == '*':
            prec = str(int(args[ai])); ai += 1
        arg = args[ai] if ai < len(args) else 0
        ai += 1
        spec = '%' + flags + (width or '') + ('.' + (prec or '0') if prec is not None else '')
        if conv in 'di':
            spec, val = spec + 'd', int(arg)
        elif conv == 'u':
            spec, val = spec + 'd', int(arg) % (1 << (64 if length in ('l', 'll') else 32))
        elif conv in 'oxX':
            val = int(arg)
            if val < 0:
                val %= 1 << (64 if length in ('l', 'll') else 32)
            spec += conv
        elif conv in 'eEfFgG':
            spec, val = spec + conv, float(arg)
        elif conv == 'c':
            spec, val = spec + 'c', (arg if isinstance(arg, str) else chr(int(arg) & 0xFF))
        elif conv == 's':
            spec, val = spec + 's', _rt_cstr(arg)
        else:  # %p
            spec, val = spec + 's', '0x%x' % (id(arg) & 0xFFFFFF)
        res.append(spec % val)
    res.append(fmt[pos:])
    return ''.join(res)


def _rt_printf(fmt, *args):
    s = _rt_format(fmt, args)
    _rt_sys.stdout.write(s)
    return len(s)


def _rt_puts(s):
    _rt_sys.stdout.write(_rt_cstr(s) + '\n')
    return 1


def _rt_putchar(c):
    _rt_sys.stdout.write(chr(int(c) & 0xFF))
    return c


def _rt_strlen(s):
    return len(_rt_cstr(s))


def _rt_idiv(a, b):
    """Цілочисельне ділення C: округлення до нуля (у Python // округлює вниз)."""
    if b == 0:
        raise ZeroDivisionError('ділення на нуль')
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _rt_imod(a, b):
    """Остача C: знак як у діленого (у Python % має знак дільника)."""
    return a - b * _rt_idiv(a, b)


def _rt_char(v):
    v = int(v) & 0xFF
    return v - 256 if v > 127 else v


def _rt_set(c, k, v):
    c[k] = v
    return v


def _rt_preinc(c, k, d):
    c[k] += d
    return c[k]


def _rt_postinc(c, k, d):
    old = c[k]
    c[k] = old + d
    return old


def _rt_str(s, n):
    """char s[n] = "..." -> список кодів символів із завершальним нулем."""
    codes = [ord(ch) for ch in s] + [0]
    return codes + [0] * (n - len(codes))
'''

_ns = {}
exec(PY_RUNTIME, _ns)
c_format = _ns['_rt_format']
c_idiv = _ns['_rt_idiv']
c_imod = _ns['_rt_imod']


JS_RUNTIME = r'''
const __out = [];
function _rt_cstr(v) {
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) { let s = ''; for (const c of v) { if (c === 0) break; s += String.fromCharCode(c); } return s; }
  return String(v);
}
function _rt_num(x) { return typeof x === 'boolean' ? (x ? 1 : 0) : Number(x); }
function _rt_special(x) { return Number.isNaN(x) ? 'nan' : (x > 0 ? 'inf' : '-inf'); }
function _rt_exp(s) { return s.replace(/e([+-])(\d)$/, 'e$10$2'); }
function _rt_g(x, p, alt, upper) {
  if (p === 0) p = 1;
  if (x === 0) return alt ? (0).toFixed(p - 1) : '0';
  let s, X = Number(x.toExponential(p - 1).split('e')[1]);
  if (p > X && X >= -4) s = x.toFixed(p - 1 - X); else s = _rt_exp(x.toExponential(p - 1));
  if (!alt) {
    if (s.includes('e')) { let [m, ex] = s.split('e'); if (m.includes('.')) m = m.replace(/\.?0+$/, ''); s = m + 'e' + ex; }
    else if (s.includes('.')) s = s.replace(/\.?0+$/, '');
  }
  return upper ? s.toUpperCase() : s;
}
function _rt_format(fmt, args) {
  fmt = _rt_cstr(fmt);
  const re = /%([-+ #0]*)(\*|\d+)?(?:\.(\*|\d*))?(hh|h|ll|l|L|z|j|t)?([diouxXeEfFgGcsp%])/g;
  let ai = 0;
  return fmt.replace(re, (m, flags, width, prec, len, conv) => {
    if (conv === '%') return '%';
    if (width === '*') width = String(args[ai++]);
    if (prec === '*') prec = String(args[ai++]);
    const arg = ai < args.length ? args[ai] : 0; ai++;
    const left = flags.includes('-'), zero = flags.includes('0') && !left;
    const plus = flags.includes('+'), space = flags.includes(' '), alt = flags.includes('#');
    let p = prec === undefined ? undefined : Number(prec || 0);
    let body, sign = '', numeric = true;
    if ('di'.includes(conv) || conv === 'u' || 'oxX'.includes(conv)) {
      let v = Math.trunc(_rt_num(arg));
      if (conv === 'u' || 'oxX'.includes(conv)) { if (v < 0) v = (len === 'l' || len === 'll') ? v + 2 ** 64 : v >>> 0; }
      if (v < 0) { sign = '-'; v = -v; } else if (plus && 'di'.includes(conv)) sign = '+'; else if (space && 'di'.includes(conv)) sign = ' ';
      body = conv === 'o' ? v.toString(8) : conv === 'x' ? v.toString(16) : conv === 'X' ? v.toString(16).toUpperCase() : String(v);
      if (alt && (conv === 'x' || conv === 'X') && v !== 0) sign += conv === 'x' ? '0x' : '0X';
      if (p !== undefined) { while (body.length < p) body = '0' + body; }
    } else if ('eEfFgG'.includes(conv)) {
      let v = _rt_num(arg);
      if (v < 0 || Object.is(v, -0)) { sign = '-'; v = -v; } else if (plus) sign = '+'; else if (space) sign = ' ';
      const pp = p === undefined ? 6 : p;
      if (!Number.isFinite(v)) { body = _rt_special(v); numeric = false; }
      else if (conv === 'f' || conv === 'F') body = v.toFixed(pp) + (alt && pp === 0 ? '.' : '');
      else if (conv === 'e' || conv === 'E') { body = _rt_exp(v.toExponential(pp)); if (conv === 'E') body = body.toUpperCase(); }
      else body = _rt_g(v, pp, alt, conv === 'G');
    } else if (conv === 'c') { body = typeof arg === 'string' ? arg : String.fromCharCode(_rt_num(arg) & 255); numeric = false; }
    else if (conv === 's') { body = _rt_cstr(arg); if (p !== undefined) body = body.slice(0, p); numeric = false; }
    else { body = '0x' + (Math.floor(Math.random() * 0xffffff)).toString(16); numeric = false; }
    let s = sign + body;
    const w = width ? Number(width) : 0;
    if (s.length < w) {
      if (left) s = s + ' '.repeat(w - s.length);
      else if (zero && numeric && !(p !== undefined && 'diouxX'.includes(conv))) s = sign + '0'.repeat(w - s.length) + body;
      else s = ' '.repeat(w - s.length) + s;
    }
    return s;
  });
}
function _rt_printf(fmt, ...args) { const s = _rt_format(fmt, args); __out.push(s); return s.length; }
function _rt_puts(s) { __out.push(_rt_cstr(s) + '\n'); return 1; }
function _rt_putchar(c) { __out.push(String.fromCharCode(_rt_num(c) & 255)); return c; }
function _rt_strlen(s) { return _rt_cstr(s).length; }
function _rt_idiv(a, b) { a = _rt_num(a); b = _rt_num(b); if (b === 0) throw new Error('ділення на нуль'); return Math.trunc(a / b); }
function _rt_imod(a, b) { a = _rt_num(a); b = _rt_num(b); if (b === 0) throw new Error('ділення на нуль'); return a % b; }
function _rt_char(v) { v = Math.trunc(_rt_num(v)) & 255; return v > 127 ? v - 256 : v; }
function _rt_arr(dims, fill) {
  if (dims.length === 1) return new Array(dims[0]).fill(fill);
  return Array.from({ length: dims[0] }, () => _rt_arr(dims.slice(1), fill));
}
function _rt_init(dims, values, fill) {
  const a = _rt_arr(dims, fill);
  const put = (dst, src) => { for (let i = 0; i < src.length && i < dst.length; i++) { if (Array.isArray(src[i])) put(dst[i], src[i]); else dst[i] = src[i]; } };
  put(a, values); return a;
}
function _rt_str(s, n) { const a = new Array(n).fill(0); for (let i = 0; i < s.length && i < n; i++) a[i] = s.charCodeAt(i); return a; }
function _rt_flush() {
  const s = __out.join(''); __out.length = 0;
  if (globalThis.__minic_sink) globalThis.__minic_sink(s);
  else if (typeof process !== 'undefined' && process.stdout) process.stdout.write(s);
  else if (typeof Deno !== 'undefined') Deno.stdout.writeSync(new TextEncoder().encode(s));
  else console.log(s);
}
'''
