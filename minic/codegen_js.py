"""Трансляція AST MiniC → JavaScript (ES2015+).

JavaScript синтаксично близький до C (блоки з let, for, do-while, switch з fallthrough,
++/--, присвоєння як вираз, оператор кома), тому трансляція майже структурна.
Семантичні відмінності:
  * всі числа – double: цілочисельне ділення → _rt_idiv (Math.trunc), float→int → Math.trunc;
  * порівняння дають boolean → у значеннєвому контексті Number(...) (C: 0/1);
  * масиви → Array (багатовимірні – масив масивів), char[] → масив кодів символів.
Згенерований код виконується у браузері (вкладка Output) та в Node/Deno.
"""
from . import astnodes as A
from .codegen_common import CodegenError, Emitter, COMPARISON, flatten_switch
from .runtime import JS_RUNTIME

# пріоритети операторів JavaScript (збігаються з C)
ATOM, POSTFIX, UNARY, MUL, ADD, SHIFT, REL, EQ, BAND, BXOR, BOR, LAND, LOR, TERN, ASSIGN, COMMA = (
    100, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 1)
BIN_PREC = {'*': MUL, '/': MUL, '%': MUL, '+': ADD, '-': ADD, '<<': SHIFT, '>>': SHIFT,
            '<': REL, '>': REL, '<=': REL, '>=': REL, '==': EQ, '!=': EQ,
            '&': BAND, '^': BXOR, '|': BOR, '&&': LAND, '||': LOR}
JS_OP = {'==': '===', '!=': '!=='}

BUILTIN_MAP = {'printf': '_rt_printf', 'puts': '_rt_puts', 'putchar': '_rt_putchar',
               'strlen': '_rt_strlen', 'abs': 'Math.abs', 'fabs': 'Math.abs', 'sqrt': 'Math.sqrt',
               'pow': 'Math.pow', 'floor': 'Math.floor', 'ceil': 'Math.ceil'}


class JSGenerator:
    def __init__(self):
        self.out = Emitter('  ')

    def generate(self, program):
        o = self.out
        o.emit('// Згенеровано транслятором MiniC (C -> JavaScript)')
        o.emit("'use strict';")
        o.emit('// ---------------- runtime ----------------')
        for line in JS_RUNTIME.strip('\n').split('\n'):
            o.lines.append(line)
        o.emit('// ---------------- program ----------------')
        o.emit()
        for d in program.decls:
            if isinstance(d, A.VarDecl):
                self.var_decl(d)
        for d in program.decls:
            if isinstance(d, A.FuncDef):
                o.emit()
                self.func(d)
        o.emit()
        o.emit('let __exit_code = 0;')
        o.emit('try { __exit_code = main(); } finally { _rt_flush(); }')
        return o.text()

    def func(self, f):
        o = self.out
        params = ', '.join(p.sym.uname for p in f.params)
        o.emit('function %s(%s) {' % (f.sym.uname, params))
        o.level += 1
        for s in f.body.items:
            self.stmt(s)
        o.level -= 1
        o.emit('}')

    # ---------------------------------------------------------------- оголошення
    def zero(self, t):
        return '0'

    def init_value(self, t, init):
        if isinstance(init, A.StringLit):
            return '"%s"' % self.js_str(init.value)
        if isinstance(init, A.InitList):
            return '[' + ', '.join(self.init_value(t.element() if t.is_array else t, x)
                                   for x in init.items) + ']'
        return self.convert(init, t)

    def array_expr(self, t, init):
        dims = list(t.dims)
        if init is None:
            if len(dims) == 1:
                return 'new Array(%d).fill(0)' % dims[0]
            return '_rt_arr([%s], 0)' % ', '.join(map(str, dims))
        if isinstance(init, A.StringLit):
            return '_rt_str("%s", %d)' % (self.js_str(init.value), dims[0])
        items = init.items
        el = t.element()
        if el.is_array and not any(isinstance(x, A.InitList) for x in items):
            inner = 1
            for d in el.dims:
                inner *= d
            vals = [self.convert(x, el) for x in items]

            def nest(vs, ds):
                if len(ds) == 1:
                    return '[' + ', '.join(vs) + ']'
                step = 1
                for d in ds[1:]:
                    step *= d
                return '[' + ', '.join(nest(vs[i:i + step], ds[1:]) for i in range(0, len(vs), step)) + ']'
            lit = nest(vals, dims)
        else:
            lit = self.init_value(t, init)
        if len(dims) == 1 and len(items) == dims[0]:
            return lit
        return '_rt_init([%s], %s, 0)' % (', '.join(map(str, dims)), lit)

    def var_decl(self, d):
        t, name = d.vtype, d.sym.uname
        if t.is_array:
            self.out.emit('let %s = %s;' % (name, self.array_expr(t, d.init)))
            return
        init = d.init
        if isinstance(init, A.InitList):
            init = init.items[0] if init.items else None
        if init is None:
            self.out.emit('let %s = 0;' % name)
        else:
            if t.is_pointer and not (init.ctype and (init.ctype.is_array or init.ctype.is_pointer)):
                if not (isinstance(init, A.Const) and init.value == 0):
                    raise CodegenError('вказівник на скалярну змінну не підтримується у JavaScript', d.line)
            self.out.emit('let %s = %s;' % (name, self.convert(init, t)))

    def decl_inline(self, dl):
        parts = []
        for d in dl.decls:
            init = d.init
            if d.vtype.is_array:
                parts.append('%s = %s' % (d.sym.uname, self.array_expr(d.vtype, init)))
            else:
                parts.append('%s = %s' % (d.sym.uname, self.convert(init, d.vtype) if init is not None else '0'))
        return 'let ' + ', '.join(parts)

    def convert(self, e, t, min_prec=ASSIGN):
        s, p = self.ex(e)
        vt = e.ctype
        if t.is_integer and vt is not None and vt.is_float:
            return 'Math.trunc(%s)' % s
        return s if p >= min_prec else '(%s)' % s

    @staticmethod
    def js_str(s):
        out = []
        for ch in s:
            if ch == '"':
                out.append('\\"')
            elif ch == '\\':
                out.append('\\\\')
            elif ch == '\n':
                out.append('\\n')
            elif ch == '\t':
                out.append('\\t')
            elif ch == '\r':
                out.append('\\r')
            elif ord(ch) < 32 or ord(ch) == 127:
                out.append('\\x%02x' % ord(ch))
            else:
                out.append(ch)
        return ''.join(out)

    # ---------------------------------------------------------------- оператори
    def stmt(self, s):
        m = getattr(self, 's_' + type(s).__name__, None)
        if m is None:
            raise CodegenError('оператор %s не підтримується' % type(s).__name__, s.line)
        m(s)

    def body(self, s):
        """Тіло керуючої конструкції завжди у фігурних дужках."""
        o = self.out
        o.level += 1
        if isinstance(s, A.Compound):
            for it in s.items:
                self.stmt(it)
        else:
            self.stmt(s)
        o.level -= 1

    def s_Compound(self, s):
        self.out.emit('{')
        self.body(s)
        self.out.emit('}')

    def s_DeclList(self, s):
        for d in s.decls:
            self.var_decl(d)

    def s_EmptyStmt(self, s):
        self.out.emit(';')

    def s_ExprStmt(self, s):
        self.out.emit(self.expr(s.expr) + ';')

    def s_If(self, s):
        o = self.out
        o.emit('if (%s) {' % self.cond(s.cond))
        self.body(s.then)
        other = s.other
        while isinstance(other, A.If):          # else if-ланцюжок
            o.emit('} else if (%s) {' % self.cond(other.cond))
            self.body(other.then)
            other = other.other
        if other is not None:
            o.emit('} else {')
            self.body(other)
        o.emit('}')

    def s_While(self, s):
        self.out.emit('while (%s) {' % self.cond(s.cond))
        self.body(s.body)
        self.out.emit('}')

    def s_DoWhile(self, s):
        self.out.emit('do {')
        self.body(s.body)
        self.out.emit('} while (%s);' % self.cond(s.cond))

    def s_For(self, s):
        if isinstance(s.init, A.DeclList):
            init = self.decl_inline(s.init)
        elif s.init is not None:
            init = self.expr(s.init)
        else:
            init = ''
        cond = self.cond(s.cond) if s.cond is not None else ''
        step = self.expr(s.step) if s.step is not None else ''
        self.out.emit('for (%s; %s; %s) {' % (init, cond, step))
        self.body(s.body)
        self.out.emit('}')

    def s_Switch(self, s):
        """switch у JS має ту саму семантику, що й у C (fallthrough, break, default)."""
        o = self.out
        o.emit('switch (%s) {' % self.expr(s.expr))
        o.level += 1
        for labels, stmts in flatten_switch(s):
            for lab in labels:
                o.emit('default:' if lab == 'default' else 'case %d:' % lab)
            o.level += 1
            for st in stmts:
                self.stmt(st)
            o.level -= 1
        o.level -= 1
        o.emit('}')

    def s_Case(self, s):
        raise CodegenError('мітка case всередині вкладеного оператора не підтримується', s.line)

    s_Default = s_Case

    def s_Break(self, s):
        self.out.emit('break;')

    def s_Continue(self, s):
        self.out.emit('continue;')

    def s_Return(self, s):
        self.out.emit('return;' if s.expr is None else 'return %s;' % self.expr(s.expr))

    # ---------------------------------------------------------------- вирази
    def expr(self, e):
        return self.ex(e)[0]

    def sub(self, e, min_prec):
        s, p = self.ex(e)
        return s if p >= min_prec else '(%s)' % s

    def ex(self, e):
        m = getattr(self, 'e_' + type(e).__name__, None)
        if m is None:
            raise CodegenError('вираз %s не підтримується' % type(e).__name__, e.line)
        return m(e)

    def cond(self, e):
        return self.cex(e)[0]

    def cex(self, e):
        if isinstance(e, A.BinOp) and (e.op in ('&&', '||') or e.op in COMPARISON):
            prec = BIN_PREC[e.op]
            if e.op in ('&&', '||'):
                l, lp = self.cex(e.left)
                r, rp = self.cex(e.right)
            else:
                l, lp = self.ex(e.left)
                r, rp = self.ex(e.right)
            l = l if lp >= prec else '(%s)' % l
            r = r if rp > prec else '(%s)' % r
            return '%s %s %s' % (l, JS_OP.get(e.op, e.op), r), prec
        if isinstance(e, A.UnaryOp) and e.op == '!':
            s, p = self.cex(e.operand)
            return '!' + (s if p >= UNARY else '(%s)' % s), UNARY
        return self.ex(e)

    def e_Const(self, e):
        if e.kind == 'float':
            return repr(float(e.value)), ATOM
        if e.kind == 'char':
            c = chr(e.value)
            if c.isprintable() and c not in "\\'*/":
                return "%d /* '%s' */" % (e.value, c), ATOM
        return str(e.value), ATOM

    def e_StringLit(self, e):
        return '"%s"' % self.js_str(e.value), ATOM

    def e_Id(self, e):
        return e.sym.uname, ATOM

    def e_BinOp(self, e):
        op = e.op
        if op in ('&&', '||'):
            return '(%s) ? 1 : 0' % self.cond(e), TERN
        if op in COMPARISON:
            return 'Number(%s)' % self.cond(e), ATOM
        lt, rt = e.left.ctype, e.right.ctype
        if (lt and (lt.is_pointer or lt.is_array)) or (rt and (rt.is_pointer or rt.is_array)):
            raise CodegenError('арифметика вказівників не підтримується у JavaScript-трансляції', e.line)
        if op == '/' and lt.is_integer and rt.is_integer:
            return '_rt_idiv(%s, %s)' % (self.expr(e.left), self.expr(e.right)), ATOM
        prec = BIN_PREC[op]
        return '%s %s %s' % (self.sub(e.left, prec), op, self.sub(e.right, prec + 1)), prec

    def e_UnaryOp(self, e):
        if e.op == '!':
            return 'Number(%s)' % self.cond(e), ATOM
        s = self.sub(e.operand, UNARY)
        if e.op == '-' and s.startswith('-'):
            s = '(%s)' % s
        return e.op + s, UNARY

    def lval(self, t):
        if isinstance(t, A.Id):
            return t.sym.uname
        if isinstance(t, A.Index):
            return '%s[%s]' % (self.sub(t.base, POSTFIX), self.expr(t.index))
        if isinstance(t, A.Deref):
            s = self.deref_as_index(t)
            if s:
                return s
        raise CodegenError('присвоєння через вказівник не підтримується у JavaScript-трансляції', t.line)

    def e_IncDec(self, e):
        tgt = self.lval(e.target)
        if e.prefix:
            return e.op + tgt, UNARY
        return tgt + e.op, POSTFIX

    def e_Assign(self, e):
        tgt = self.lval(e.target)
        tt, vt = e.target.ctype, e.value.ctype
        if e.op == '=':
            return '%s = %s' % (tgt, self.convert(e.value, tt)), ASSIGN
        op = e.op[:-1]
        if op == '/' and tt.is_integer and vt.is_integer:
            return '%s = _rt_idiv(%s, %s)' % (tgt, tgt, self.expr(e.value)), ASSIGN
        if tt.is_integer and vt.is_float:
            return '%s = Math.trunc(%s %s %s)' % (tgt, tgt, op, self.sub(e.value, BIN_PREC[op] + 1)), ASSIGN
        return '%s %s %s' % (tgt, e.op, self.sub(e.value, ASSIGN)), ASSIGN

    def e_Ternary(self, e):
        return '%s ? %s : %s' % (self.sub_cond(e.cond, LOR), self.sub(e.then, ASSIGN),
                                 self.sub(e.other, TERN)), TERN

    def sub_cond(self, e, min_prec):
        s, p = self.cex(e)
        return s if p >= min_prec else '(%s)' % s

    def e_Call(self, e):
        args = ', '.join(self.sub(a, ASSIGN) for a in e.args)
        if e.sym is None:
            if e.name == 'exit':
                return '(() => { throw new Error("exit(" + (%s) + ")"); })()' % args, ATOM
            return '%s(%s)' % (BUILTIN_MAP[e.name], args), ATOM
        return '%s(%s)' % (e.sym.uname, args), ATOM

    def e_Index(self, e):
        return '%s[%s]' % (self.sub(e.base, POSTFIX), self.expr(e.index)), POSTFIX

    def deref_as_index(self, e):
        x = e.operand
        if x.ctype is not None and (x.ctype.is_array or x.ctype.is_pointer):
            if isinstance(x, A.Id):
                return '%s[0]' % x.sym.uname
            if isinstance(x, A.BinOp) and x.op == '+' and isinstance(x.left, A.Id) \
                    and x.left.ctype and (x.left.ctype.is_array or x.left.ctype.is_pointer):
                return '%s[%s]' % (x.left.sym.uname, self.expr(x.right))
        return None

    def e_Deref(self, e):
        s = self.deref_as_index(e)
        if s:
            return s, POSTFIX
        raise CodegenError("розіменування вказівника ('*') не підтримується у JavaScript-трансляції "
                           "(інтерпретатор AST підтримує)", e.line)

    def e_AddrOf(self, e):
        if isinstance(e.operand, A.Id) and e.operand.ctype.is_array:
            return e.operand.sym.uname, ATOM
        raise CodegenError("взяття адреси ('&') не підтримується у JavaScript-трансляції "
                           "(інтерпретатор AST підтримує)", e.line)

    def e_Cast(self, e):
        t, src = e.to, e.operand.ctype
        if t.ptr:
            raise CodegenError('приведення до вказівника не підтримується', e.line)
        if t.base == 'char':
            return '_rt_char(%s)' % self.expr(e.operand), ATOM
        if t.is_integer:
            if src is not None and src.is_integer:
                return self.ex(e.operand)
            return 'Math.trunc(%s)' % self.expr(e.operand), ATOM
        return self.ex(e.operand)

    def e_SizeOf(self, e):
        return str(e.value), ATOM

    def e_Comma(self, e):
        return ', '.join(self.sub(x, ASSIGN) for x in e.exprs), COMMA


def generate(program):
    return JSGenerator().generate(program)
