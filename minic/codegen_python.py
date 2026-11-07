"""Трансляція AST MiniC → Python 3.8+.

Основні відмінності мов і як вони долаються:
  * блочні області видимості C → функціональні в Python: семантичний аналізатор дає
    кожній локальній змінній унікальне ім'я (uname), тож затінення не ламає код;
  * for(init; cond; step) → while; `continue` у for спочатку виконує step;
  * do-while → while True + перевірка умови в кінці (і перед continue);
  * switch з fallthrough → `while True` + номер стартового сегмента (див. gen_switch);
  * присвоєння/інкремент всередині виразу → оператор := (walrus) або хелпери _rt_set/_rt_postinc;
  * цілочисельне ділення C (до нуля) → _rt_idiv, остача → _rt_imod (бо // і % у Python округлюють вниз);
  * порівняння, && || ! у значеннєвому контексті дають int 0/1, як у C.
"""
from . import astnodes as A
from .codegen_common import CodegenError, Emitter, flatten_switch, COMPARISON
from .runtime import PY_RUNTIME

ATOM, UNARY, MUL, ADD, SHIFT, BAND, BXOR, BOR, CMP, NOT, AND, OR, TERN = (
    100, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0)

BIN_PREC = {'*': MUL, '/': MUL, '%': MUL, '+': ADD, '-': ADD, '<<': SHIFT, '>>': SHIFT,
            '&': BAND, '^': BXOR, '|': BOR}

BUILTIN_MAP = {'printf': '_rt_printf', 'puts': '_rt_puts', 'putchar': '_rt_putchar',
               'strlen': '_rt_strlen', 'abs': 'abs', 'fabs': '_rt_math.fabs',
               'sqrt': '_rt_math.sqrt', 'pow': '_rt_math.pow', 'floor': '_rt_math.floor',
               'ceil': '_rt_math.ceil', 'exit': '_rt_sys.exit'}


def contains_continue(node):
    """Чи є у вузлі continue, що належить зовнішньому циклу (не вкладеному)."""
    if isinstance(node, A.Continue):
        return True
    if isinstance(node, (A.While, A.DoWhile, A.For)):
        return False
    return any(contains_continue(c) for _, c in node.children())


class PythonGenerator:
    def __init__(self):
        self.out = Emitter('    ')
        self.loops = []        # стек: ('loop', continue_fn) | ('switch', flag_name)
        self.counter = 0

    def new_name(self, prefix):
        self.counter += 1
        return '_rt_%s%d' % (prefix, self.counter)

    # ---------------------------------------------------------------- програма
    def generate(self, program):
        o = self.out
        o.emit('# -*- coding: utf-8 -*-')
        o.emit('# Згенеровано транслятором MiniC (C -> Python 3)')
        o.emit('# ---------------- runtime ----------------')
        for line in PY_RUNTIME.strip('\n').split('\n'):
            o.lines.append(line)
        o.emit('# ---------------- program ----------------')
        o.emit()
        for d in program.decls:
            if isinstance(d, A.VarDecl):
                self.var_decl(d)
        for d in program.decls:
            if isinstance(d, A.FuncDef):
                o.emit()
                self.func(d)
        o.emit()
        o.emit()
        o.emit("if __name__ == '__main__':")
        o.emit('    _rt_code = main()')
        o.emit('    _rt_sys.stdout.flush()')
        o.emit('    _rt_sys.exit(_rt_code if isinstance(_rt_code, int) else 0)')
        return o.text()

    def func(self, f):
        o = self.out
        params = ', '.join(p.sym.uname for p in f.params)
        o.emit('def %s(%s):' % (f.sym.uname, params))
        o.level += 1
        if f.globals_assigned:
            o.emit('global ' + ', '.join(sorted(f.globals_assigned)))
        self.block(f.body.items)
        o.level -= 1

    def block(self, items):
        start = len(self.out.lines)
        for s in items:
            self.stmt(s)
        if len(self.out.lines) == start:
            self.out.emit('pass')

    # ---------------------------------------------------------------- оголошення
    def zero(self, t):
        return '0.0' if t.base in ('float', 'double') and not t.ptr else '0'

    def array_expr(self, t, init):
        n, el = t.dims[0], t.element()
        if init is None:
            if el.is_array:
                return '[%s for _ in range(%d)]' % (self.array_expr(el, None), n)
            return '[%s] * %d' % (self.zero(el), n)
        if isinstance(init, A.StringLit):
            return '_rt_str(%r, %d)' % (init.value, n)
        items = init.items
        if el.is_array and not any(isinstance(x, (A.InitList, A.StringLit)) for x in items):
            # «плаский» ініціалізатор багатовимірного масиву: розбиваємо на рядки
            chunk = el.size() // max(1, scalar_size(el))
            rows = [A.InitList(items[i:i + chunk]) for i in range(0, len(items), chunk)]
            items = rows
        if el.is_array:
            parts = [self.array_expr(el, it) for it in items]
            s = '[' + ', '.join(parts) + ']'
            if len(parts) < n:
                s += ' + [%s for _ in range(%d)]' % (self.array_expr(el, None), n - len(parts))
            return s
        parts = [self.convert(it, el) for it in items]
        s = '[' + ', '.join(parts) + ']'
        if len(parts) < n:
            s += ' + [%s] * %d' % (self.zero(el), n - len(parts))
        return s

    def var_decl(self, d):
        t, name = d.vtype, d.sym.uname
        if t.is_array:
            self.out.emit('%s = %s' % (name, self.array_expr(t, d.init)))
            return
        init = d.init
        if isinstance(init, A.InitList):
            init = init.items[0] if init.items else None
        if init is None:
            self.out.emit('%s = %s' % (name, self.zero(t)))
        else:
            if t.is_pointer and not (init.ctype and (init.ctype.is_array or init.ctype.is_pointer)):
                if not (isinstance(init, A.Const) and init.value == 0):
                    raise CodegenError('вказівник на скалярну змінну не підтримується у Python', d.line)
            self.out.emit('%s = %s' % (name, self.convert(init, t)))

    def convert(self, e, t):
        """Вираз e, приведений до типу змінної t (float → int відкидає дробову частину)."""
        s, p = self.ex(e)
        vt = e.ctype
        if t.is_integer and vt is not None and vt.is_float:
            return 'int(%s)' % s
        if t.base == 'char' and t.is_integer and not isinstance(e, A.Const):
            return s
        if t.is_float and isinstance(e, A.Const) and e.kind != 'float':
            return repr(float(e.value))
        return s

    # ---------------------------------------------------------------- оператори
    def stmt(self, s):
        m = getattr(self, 's_' + type(s).__name__, None)
        if m is None:
            raise CodegenError('оператор %s не підтримується' % type(s).__name__, s.line)
        m(s)

    def s_Compound(self, s):
        for it in s.items:
            self.stmt(it)

    def s_DeclList(self, s):
        for d in s.decls:
            self.var_decl(d)

    def s_EmptyStmt(self, s):
        pass

    def s_ExprStmt(self, s):
        self.stmt_expr(s.expr)

    def stmt_expr(self, e):
        """Вираз на рівні оператора: присвоєння/інкременти генеруються як оператори Python."""
        o = self.out
        if isinstance(e, A.Comma):
            for x in e.exprs:
                self.stmt_expr(x)
            return
        if isinstance(e, A.IncDec):
            tgt = self.target(e.target)
            o.emit('%s %s= 1' % (tgt, '+' if e.op == '++' else '-'))
            return
        if isinstance(e, A.Assign):
            tgt = self.target(e.target)
            o.emit('%s = %s' % (tgt, self.assign_value(e, tgt)))
            return
        o.emit(self.expr(e))

    def target(self, t):
        if isinstance(t, A.Id):
            return t.sym.uname
        if isinstance(t, A.Index):
            return '%s[%s]' % (self.sub(t.base, ATOM), self.expr(t.index))
        if isinstance(t, A.Deref):
            idx = self.deref_as_index(t)
            if idx:
                return idx
        raise CodegenError('присвоєння через вказівник не підтримується у Python-трансляції', t.line)

    def assign_value(self, e, tgt):
        tt = e.target.ctype
        if e.op == '=':
            return self.convert(e.value, tt)
        op = e.op[:-1]
        both_int = tt.is_integer and e.value.ctype.is_integer
        if op == '/' and both_int:
            s = '_rt_idiv(%s, %s)' % (tgt, self.expr(e.value))
        elif op == '%':
            s = '_rt_imod(%s, %s)' % (tgt, self.expr(e.value))
        else:
            s = '%s %s %s' % (tgt, op, self.sub(e.value, BIN_PREC[op] + 1))
        if tt.is_integer and e.value.ctype.is_float:
            s = 'int(%s)' % s
        return s

    def s_If(self, s, keyword='if'):
        o = self.out
        o.emit('%s %s:' % (keyword, self.cond(s.cond)))
        o.level += 1
        self.block([s.then])
        o.level -= 1
        if s.other is not None:
            if isinstance(s.other, A.If):
                self.s_If(s.other, 'elif')
            else:
                o.emit('else:')
                o.level += 1
                self.block([s.other])
                o.level -= 1

    def loop(self, body, cont_fn):
        self.loops.append(('loop', cont_fn))
        self.out.level += 1
        self.block([body])
        self.out.level -= 1
        self.loops.pop()

    def s_While(self, s):
        self.out.emit('while %s:' % self.cond(s.cond))
        self.loop(s.body, lambda: self.out.emit('continue'))

    def s_DoWhile(self, s):
        o = self.out
        o.emit('while True:  # do-while')
        check = 'if not (%s):' % self.cond(s.cond)

        def cont():
            o.emit(check)
            o.emit('    break')
            o.emit('continue')
        self.loop(s.body, cont)
        o.level += 1
        o.emit(check)
        o.emit('    break')
        o.level -= 1

    def s_For(self, s):
        o = self.out
        if isinstance(s.init, A.DeclList):
            self.s_DeclList(s.init)
        elif s.init is not None:
            self.stmt_expr(s.init)
        o.emit('while %s:' % (self.cond(s.cond) if s.cond is not None else 'True'))

        def step():
            if s.step is not None:
                self.stmt_expr(s.step)

        def cont():
            step()
            o.emit('continue')
        self.loop(s.body, cont)
        o.level += 1
        step()
        o.level -= 1

    def s_Switch(self, s):
        """switch → вибір стартового сегмента + `while True`, щоб break працював як у C.

            _rt_swN = {1: 0, 2: 1}.get(expr, <default або кількість сегментів>)
            while True:
                if _rt_swN <= 0: ...сегмент 0...
                if _rt_swN <= 1: ...сегмент 1...   # fallthrough: виконуються всі наступні
                break
        """
        o = self.out
        segs = flatten_switch(s)
        sw = self.new_name('sw')
        mapping, default = [], len(segs)
        for k, (labels, _) in enumerate(segs):
            for lab in labels:
                if lab == 'default':
                    default = k
                else:
                    mapping.append('%d: %d' % (lab, k))
        o.emit('%s = {%s}.get(%s, %d)' % (sw, ', '.join(mapping), self.expr(s.expr), default))
        flag = self.new_name('cont') if contains_continue(s.body) else None
        if flag:
            o.emit('%s = False' % flag)
        o.emit('while True:  # switch')
        self.loops.append(('switch', flag))
        o.level += 1
        for k, (labels, stmts) in enumerate(segs):
            if not labels:
                continue                     # недосяжний код до першої мітки
            o.emit('if %s <= %d:  # %s' % (sw, k, ', '.join('case %s' % l if l != 'default'
                                                            else 'default' for l in labels)))
            o.level += 1
            self.block(stmts)
            o.level -= 1
        o.emit('break')
        o.level -= 1
        self.loops.pop()
        if flag:
            o.emit('if %s:' % flag)
            o.level += 1
            self.s_Continue(A.Continue(line=s.line))
            o.level -= 1

    def s_Case(self, s):
        raise CodegenError('мітка case всередині вкладеного оператора не підтримується', s.line)

    s_Default = s_Case

    def s_Break(self, s):
        self.out.emit('break')

    def s_Continue(self, s):
        kind, data = self.loops[-1]
        if kind == 'switch':
            self.out.emit('%s = True' % data)
            self.out.emit('break')
        else:
            data()

    def s_Return(self, s):
        self.out.emit('return' if s.expr is None else 'return ' + self.expr(s.expr))

    # ---------------------------------------------------------------- вирази
    def expr(self, e):
        return self.ex(e)[0]

    def sub(self, e, min_prec):
        s, p = self.ex(e)
        return s if p >= min_prec else '(%s)' % s

    def ex(self, e):
        """Повертає (текст, пріоритет) – дужки ставляться лише там, де потрібно."""
        m = getattr(self, 'e_' + type(e).__name__, None)
        if m is None:
            raise CodegenError('вираз %s не підтримується' % type(e).__name__, e.line)
        return m(e)

    def cond(self, e):
        """Вираз у булевому контексті (if/while/&&/||/!) – без перетворення в 0/1."""
        return self.cex(e)[0]

    def cex(self, e):
        if isinstance(e, A.BinOp) and e.op in ('&&', '||'):
            prec = AND if e.op == '&&' else OR
            kw = ' and ' if e.op == '&&' else ' or '
            l, lp = self.cex(e.left)
            r, rp = self.cex(e.right)
            l = l if lp >= prec else '(%s)' % l
            r = r if rp > prec else '(%s)' % r
            return l + kw + r, prec
        if isinstance(e, A.BinOp) and e.op in COMPARISON:
            return '%s %s %s' % (self.sub(e.left, CMP + 1), e.op, self.sub(e.right, CMP + 1)), CMP
        if isinstance(e, A.UnaryOp) and e.op == '!':
            s, p = self.cex(e.operand)
            return 'not ' + (s if p >= NOT else '(%s)' % s), NOT
        return self.ex(e)

    def e_Const(self, e):
        if e.kind == 'float':
            return repr(float(e.value)), ATOM
        if e.kind == 'char':
            c = chr(e.value)
            if c.isprintable() and c not in '\\\'':
                return "ord('%s')" % c, ATOM
            return str(e.value), ATOM
        return str(e.value), ATOM

    def e_StringLit(self, e):
        return repr(e.value), ATOM

    def e_Id(self, e):
        return e.sym.uname, ATOM

    def e_BinOp(self, e):
        op = e.op
        if op in ('&&', '||') or op in COMPARISON:
            return '(1 if %s else 0)' % self.cond(e) if op in ('&&', '||') else 'int(%s)' % self.cond(e), ATOM
        lt, rt = e.left.ctype, e.right.ctype
        if (lt and (lt.is_pointer or lt.is_array)) or (rt and (rt.is_pointer or rt.is_array)):
            raise CodegenError('арифметика вказівників не підтримується у Python-трансляції', e.line)
        int_op = lt.is_integer and rt.is_integer
        if op == '/' and int_op:
            return '_rt_idiv(%s, %s)' % (self.expr(e.left), self.expr(e.right)), ATOM
        if op == '%':
            return '_rt_imod(%s, %s)' % (self.expr(e.left), self.expr(e.right)), ATOM
        prec = BIN_PREC[op]
        return '%s %s %s' % (self.sub(e.left, prec), op, self.sub(e.right, prec + 1)), prec

    def e_UnaryOp(self, e):
        if e.op == '!':
            return 'int(%s)' % self.cond(e), ATOM
        if e.op == '+':
            return self.ex(e.operand)
        return e.op + self.sub(e.operand, UNARY), UNARY

    def e_IncDec(self, e):
        d = 1 if e.op == '++' else -1
        t = e.target
        if isinstance(t, A.Id):
            n = t.sym.uname
            s = '(%s := %s %s 1)' % (n, n, '+' if d > 0 else '-')
            if not e.prefix:
                s = '(%s %s 1)' % (s, '-' if d > 0 else '+')
            return s, ATOM
        if isinstance(t, A.Index):
            fn = '_rt_preinc' if e.prefix else '_rt_postinc'
            return '%s(%s, %s, %d)' % (fn, self.sub(t.base, ATOM), self.expr(t.index), d), ATOM
        raise CodegenError('інкремент через вказівник не підтримується у Python', e.line)

    def e_Assign(self, e):
        t = e.target
        if isinstance(t, A.Id):
            n = t.sym.uname
            return '(%s := %s)' % (n, self.assign_value(e, n)), ATOM
        if isinstance(t, A.Index):
            base, idx = self.sub(t.base, ATOM), self.expr(t.index)
            return '_rt_set(%s, %s, %s)' % (base, idx, self.assign_value(e, '%s[%s]' % (base, idx))), ATOM
        raise CodegenError('присвоєння через вказівник не підтримується у Python', e.line)

    def e_Ternary(self, e):
        return '%s if %s else %s' % (self.sub(e.then, OR), self.cond(e.cond),
                                     self.sub(e.other, TERN)), TERN

    def e_Call(self, e):
        args = ', '.join(self.expr(a) for a in e.args)
        if e.sym is None:
            return '%s(%s)' % (BUILTIN_MAP[e.name], args), ATOM
        return '%s(%s)' % (e.sym.uname, args), ATOM

    def e_Index(self, e):
        return '%s[%s]' % (self.sub(e.base, ATOM), self.expr(e.index)), ATOM

    def deref_as_index(self, e):
        """*a → a[0], *(a + i) → a[i] для масивів."""
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
            return s, ATOM
        raise CodegenError("розіменування вказівника ('*') не підтримується у Python-трансляції "
                           "(інтерпретатор AST підтримує)", e.line)

    def e_AddrOf(self, e):
        if isinstance(e.operand, A.Id) and e.operand.ctype.is_array:
            return e.operand.sym.uname, ATOM
        raise CodegenError("взяття адреси ('&') не підтримується у Python-трансляції "
                           "(інтерпретатор AST підтримує)", e.line)

    def e_Cast(self, e):
        t, src = e.to, e.operand.ctype
        s = self.expr(e.operand)
        if t.ptr:
            raise CodegenError('приведення до вказівника не підтримується', e.line)
        if t.base == 'char':
            return '_rt_char(%s)' % s, ATOM
        if t.is_integer:
            if src is not None and src.is_integer:
                return self.ex(e.operand)              # (int) від цілого – нічого не робить
            return 'int(%s)' % s, ATOM
        if t.is_float:
            return 'float(%s)' % s, ATOM
        return s, ATOM

    def e_SizeOf(self, e):
        return str(e.value), ATOM

    def e_Comma(self, e):
        return '(%s)[-1]' % ', '.join(self.expr(x) for x in e.exprs), ATOM


def scalar_size(t):
    """Розмір скалярного елемента (для розбиття плаского ініціалізатора)."""
    b = t
    while b.is_array:
        b = b.element()
    return b.size()


def generate(program):
    return PythonGenerator().generate(program)
