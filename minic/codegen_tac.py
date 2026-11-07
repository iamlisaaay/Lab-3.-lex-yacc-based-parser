"""Генерація проміжного триадресного коду (Three-Address Code, TAC).

Класичне проміжне представлення з курсу компіляторів («Dragon Book», розд. 6):
    x = y op z      x = op y      x = y
    goto L          if x goto L   ifFalse x goto L
    param x         t = call f, n return x
    x = a[i]        a[i] = x      t = &x   t = *p   *p = x
Тимчасові значення – t1, t2, ...; мітки – L1, L2, ...
Індекси масивів переводяться у зміщення в байтах: a[i][j] для int a[3][4] →
    t1 = i * 16 ; t2 = j * 4 ; t3 = t1 + t2 ; t4 = a[t3]
Логічні && та || обчислюються скорочено (short-circuit) через умовні переходи.
"""
from . import astnodes as A
from .codegen_common import CodegenError, flatten_switch


class TACGenerator:
    def __init__(self):
        self.lines = []
        self.t = 0
        self.l = 0
        self.loops = []          # стек (мітка continue, мітка break)

    def temp(self):
        self.t += 1
        return 't%d' % self.t

    def label(self):
        self.l += 1
        return 'L%d' % self.l

    def emit(self, s):
        self.lines.append('    ' + s)

    def put_label(self, lab):
        self.lines.append(lab + ':')

    # ---------------------------------------------------------------- програма
    def generate(self, program):
        self.lines.append('# Триадресний код (TAC), згенерований MiniC')
        globals_ = [d for d in program.decls if isinstance(d, A.VarDecl)]
        if globals_:
            self.lines.append('')
            self.lines.append('.globals')
            for d in globals_:
                self.lines.append('    %s %s  (%d bytes)' % (d.vtype, d.sym.uname, d.vtype.size()))
            self.lines.append('')
            self.lines.append('function _init_globals:')
            for d in globals_:
                self.var_decl(d)
            self.lines.append('end _init_globals')
        for d in program.decls:
            if isinstance(d, A.FuncDef):
                self.lines.append('')
                params = ', '.join('%s %s' % (p.ptype, p.sym.uname) for p in d.params)
                self.lines.append('function %s(%s):    # returns %s' % (d.sym.uname, params, d.ret))
                self.t = 0
                for s in d.body.items:
                    self.stmt(s)
                if not self.lines[-1].strip().startswith('return'):
                    self.emit('return')
                self.lines.append('end %s' % d.sym.uname)
        n = sum(1 for x in self.lines if x.startswith('    ') and not x.strip().startswith('#'))
        self.lines.append('')
        self.lines.append('# інструкцій: %d, міток: %d' % (n, self.l))
        return '\n'.join(self.lines) + '\n'

    # ---------------------------------------------------------------- оголошення
    def var_decl(self, d):
        t = d.vtype
        name = d.sym.uname
        if d.init is None:
            return
        if t.is_array:
            el = t
            while el.is_array:
                el = el.element()
            width = el.size()
            for off, v in self.flat_init(t, d.init):
                self.emit('%s[%d] = %s' % (name, off * width, v))
            return
        init = d.init.items[0] if isinstance(d.init, A.InitList) else d.init
        self.emit('%s = %s' % (name, self.expr(init)))

    def flat_init(self, t, init, base=0):
        if isinstance(init, A.StringLit):
            return [(base + i, str(ord(c))) for i, c in enumerate(init.value + '\0')]
        res = []
        el = t.element()
        stride = 1
        for dsz in el.dims:
            stride *= dsz
        if el.is_array and not any(isinstance(x, A.InitList) for x in init.items):
            for i, x in enumerate(init.items):
                res.append((base + i, self.expr(x)))
            return res
        for i, x in enumerate(init.items):
            if el.is_array:
                res += self.flat_init(el, x, base + i * stride)
            else:
                res.append((base + i, self.expr(x)))
        return res

    # ---------------------------------------------------------------- оператори
    def stmt(self, s):
        m = getattr(self, 's_' + type(s).__name__, None)
        if m is None:
            raise CodegenError('TAC: оператор %s не підтримується' % type(s).__name__, s.line)
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
        self.expr(s.expr, want=False)

    def s_If(self, s):
        c = self.expr(s.cond)
        l_else, l_end = self.label(), self.label()
        self.emit('ifFalse %s goto %s' % (c, l_else if s.other else l_end))
        self.stmt(s.then)
        if s.other:
            self.emit('goto ' + l_end)
            self.put_label(l_else)
            self.stmt(s.other)
        self.put_label(l_end)

    def s_While(self, s):
        l_begin, l_end = self.label(), self.label()
        self.put_label(l_begin)
        c = self.expr(s.cond)
        self.emit('ifFalse %s goto %s' % (c, l_end))
        self.loops.append((l_begin, l_end))
        self.stmt(s.body)
        self.loops.pop()
        self.emit('goto ' + l_begin)
        self.put_label(l_end)

    def s_DoWhile(self, s):
        l_body, l_cont, l_end = self.label(), self.label(), self.label()
        self.put_label(l_body)
        self.loops.append((l_cont, l_end))
        self.stmt(s.body)
        self.loops.pop()
        self.put_label(l_cont)
        c = self.expr(s.cond)
        self.emit('if %s goto %s' % (c, l_body))
        self.put_label(l_end)

    def s_For(self, s):
        if isinstance(s.init, A.DeclList):
            self.s_DeclList(s.init)
        elif s.init is not None:
            self.expr(s.init, want=False)
        l_cond, l_step, l_end = self.label(), self.label(), self.label()
        self.put_label(l_cond)
        if s.cond is not None:
            c = self.expr(s.cond)
            self.emit('ifFalse %s goto %s' % (c, l_end))
        self.loops.append((l_step, l_end))
        self.stmt(s.body)
        self.loops.pop()
        self.put_label(l_step)
        if s.step is not None:
            self.expr(s.step, want=False)
        self.emit('goto ' + l_cond)
        self.put_label(l_end)

    def s_Switch(self, s):
        v = self.expr(s.expr)
        segs = flatten_switch(s)
        l_end = self.label()
        seg_labels = [self.label() for _ in segs]
        default = l_end
        for (labels, _), lab in zip(segs, seg_labels):
            for x in labels:
                if x == 'default':
                    default = lab
                else:
                    t = self.temp()
                    self.emit('%s = %s == %d' % (t, v, x))
                    self.emit('if %s goto %s' % (t, lab))
        self.emit('goto ' + default)
        cont = self.loops[-1][0] if self.loops else None
        self.loops.append((cont, l_end))
        for (labels, stmts), lab in zip(segs, seg_labels):
            self.put_label(lab)
            for st in stmts:
                self.stmt(st)
        self.loops.pop()
        self.put_label(l_end)

    def s_Case(self, s):
        raise CodegenError('TAC: case у вкладеному операторі не підтримується', s.line)

    s_Default = s_Case

    def s_Break(self, s):
        self.emit('goto %s    # break' % self.loops[-1][1])

    def s_Continue(self, s):
        for cont, _ in reversed(self.loops):
            if cont:
                self.emit('goto %s    # continue' % cont)
                return

    def s_Return(self, s):
        if s.expr is None:
            self.emit('return')
        else:
            self.emit('return ' + self.expr(s.expr))

    # ---------------------------------------------------------------- вирази
    def expr(self, e, want=True):
        m = getattr(self, 'e_' + type(e).__name__, None)
        if m is None:
            raise CodegenError('TAC: вираз %s не підтримується' % type(e).__name__, e.line)
        return m(e, want) if type(e) in (A.Call, A.IncDec) else m(e)

    def e_Const(self, e):
        return repr(e.value) if e.kind == 'float' else str(e.value)

    def e_StringLit(self, e):
        return '"%s"' % e.value.encode('unicode_escape').decode('ascii').replace('"', '\\"')

    def e_Id(self, e):
        return e.sym.uname

    def e_BinOp(self, e):
        if e.op in ('&&', '||'):
            t = self.temp()
            l_short, l_end = self.label(), self.label()
            a = self.expr(e.left)
            jump = 'ifFalse' if e.op == '&&' else 'if'
            self.emit('%s %s goto %s' % (jump, a, l_short))
            b = self.expr(e.right)
            self.emit('%s %s goto %s' % (jump, b, l_short))
            self.emit('%s = %d' % (t, 1 if e.op == '&&' else 0))
            self.emit('goto ' + l_end)
            self.put_label(l_short)
            self.emit('%s = %d' % (t, 0 if e.op == '&&' else 1))
            self.put_label(l_end)
            return t
        a = self.expr(e.left)
        b = self.expr(e.right)
        lt, rt = e.left.ctype, e.right.ctype
        # арифметика вказівників: зміщення множиться на розмір елемента
        if e.op in ('+', '-') and lt and (lt.is_pointer or lt.is_array) and rt and rt.is_integer:
            w = lt.element().size()
            if w != 1:
                tw = self.temp()
                self.emit('%s = %s * %d' % (tw, b, w))
                b = tw
        t = self.temp()
        op = e.op
        if op == '/' and lt and rt and lt.is_integer and rt.is_integer:
            op = '/i'           # цілочисельне ділення
        self.emit('%s = %s %s %s' % (t, a, op, b))
        if op == '-' and lt and rt and (lt.is_pointer or lt.is_array) and (rt.is_pointer or rt.is_array):
            w = lt.element().size()           # різниця вказівників – у елементах, не байтах
            t2 = self.temp()
            self.emit('%s = %s /i %d' % (t2, t, w))
            return t2
        return t

    def e_UnaryOp(self, e):
        a = self.expr(e.operand)
        if e.op == '+':
            return a
        t = self.temp()
        self.emit('%s = %s%s' % (t, 'minus ' if e.op == '-' else e.op, a))
        return t

    def address(self, e):
        """Для a[i][j] повертає (ім'я масиву, тимчасова змінна зі зміщенням у байтах)."""
        idx = []
        base = e
        while isinstance(base, A.Index):
            idx.append(base)
            base = base.base
        idx.reverse()
        name = self.expr(base)
        offset = None
        for node in idx:
            i = self.expr(node.index)
            w = node.ctype.size() if node.ctype is not None else 4
            t = self.temp()
            self.emit('%s = %s * %d' % (t, i, w))
            if offset is None:
                offset = t
            else:
                t2 = self.temp()
                self.emit('%s = %s + %s' % (t2, offset, t))
                offset = t2
        return name, offset

    def store(self, target, value):
        if isinstance(target, A.Id):
            self.emit('%s = %s' % (target.sym.uname, value))
            return target.sym.uname
        if isinstance(target, A.Index):
            name, off = self.address(target)
            self.emit('%s[%s] = %s' % (name, off, value))
            return value
        if isinstance(target, A.Deref):
            p = self.expr(target.operand)
            self.emit('*%s = %s' % (p, value))
            return value
        raise CodegenError('TAC: недопустиме lvalue', target.line)

    def e_Assign(self, e):
        v = self.expr(e.value)
        if e.op != '=':
            cur = self.expr(e.target)
            t = self.temp()
            self.emit('%s = %s %s %s' % (t, cur, e.op[:-1], v))
            v = t
        return self.store(e.target, v)

    def e_IncDec(self, e, want=True):
        cur = self.expr(e.target)
        old = None
        if not e.prefix and want:
            old = self.temp()
            self.emit('%s = %s' % (old, cur))
        t = self.temp()
        step = 1
        tt = e.target.ctype
        if tt is not None and tt.is_pointer:
            step = tt.element().size()
        self.emit('%s = %s %s %d' % (t, cur, '+' if e.op == '++' else '-', step))
        self.store(e.target, t)
        return old if old is not None else t

    def e_Ternary(self, e):
        t = self.temp()
        l_else, l_end = self.label(), self.label()
        c = self.expr(e.cond)
        self.emit('ifFalse %s goto %s' % (c, l_else))
        self.emit('%s = %s' % (t, self.expr(e.then)))
        self.emit('goto ' + l_end)
        self.put_label(l_else)
        self.emit('%s = %s' % (t, self.expr(e.other)))
        self.put_label(l_end)
        return t

    def e_Call(self, e, want=True):
        args = [self.expr(a) for a in e.args]
        for a in args:
            self.emit('param ' + a)
        name = e.sym.uname if e.sym is not None else e.name
        if want and not (e.ctype is not None and e.ctype.is_void):
            t = self.temp()
            self.emit('%s = call %s, %d' % (t, name, len(args)))
            return t
        self.emit('call %s, %d' % (name, len(args)))
        return '_'

    def e_Index(self, e):
        name, off = self.address(e)
        t = self.temp()
        if e.ctype is not None and e.ctype.is_array:
            self.emit('%s = &%s[%s]' % (t, name, off))
        else:
            self.emit('%s = %s[%s]' % (t, name, off))
        return t

    def e_AddrOf(self, e):
        t = self.temp()
        if isinstance(e.operand, A.Index):
            name, off = self.address(e.operand)
            self.emit('%s = &%s[%s]' % (t, name, off))
        else:
            self.emit('%s = &%s' % (t, self.expr(e.operand)))
        return t

    def e_Deref(self, e):
        p = self.expr(e.operand)
        t = self.temp()
        self.emit('%s = *%s' % (t, p))
        return t

    def e_Cast(self, e):
        a = self.expr(e.operand)
        t = self.temp()
        self.emit('%s = (%s) %s' % (t, e.to, a))
        return t

    def e_SizeOf(self, e):
        return str(e.value)

    def e_Comma(self, e):
        r = None
        for x in e.exprs:
            r = self.expr(x)
        return r


def generate(program):
    return TACGenerator().generate(program)
