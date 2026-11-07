"""Інтерпретатор AST (семантика = обчислення) для MiniC.

Модель пам'яті:
  * скалярна змінна – елемент словника кадру (Frame.vars[name]);
  * масив – список Python (багатовимірний – список списків);
  * вказівник – об'єкт Ref(контейнер, ключ): &x -> Ref(frame.vars, 'x'),
    &a[3] / a -> Ref(list, 3) / Ref(list, 0). Арифметика вказівників змінює ключ.
Типи C емулюються при збереженні значення: int – 32-бітне з переповненням, char – 8 біт,
float/double – float. Цілочисельне ділення і остача – з округленням до нуля, як у C.
"""
import math
import sys

from . import astnodes as A
from .runtime import c_format, c_idiv, c_imod


class CRuntimeError(Exception):
    def __init__(self, msg, line=0):
        super().__init__(msg)
        self.line = line


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    def __init__(self, value):
        self.value = value


class _Exit(Exception):
    def __init__(self, code):
        self.code = code


class Ref:
    """Вказівник: адреса = (контейнер, ключ)."""
    __slots__ = ('cont', 'key')

    def __init__(self, cont, key):
        self.cont, self.key = cont, key

    def get(self):
        try:
            return self.cont[self.key]
        except (IndexError, KeyError):
            raise CRuntimeError('розіменування вказівника за межами масиву')

    def set(self, v):
        if isinstance(self.key, int) and not (0 <= self.key < len(self.cont)):
            raise CRuntimeError('запис за межі масиву через вказівник (індекс %d)' % self.key)
        self.cont[self.key] = v

    def offset(self, n):
        if not isinstance(self.key, int):
            raise CRuntimeError('арифметика вказівника на скалярну змінну')
        return Ref(self.cont, self.key + n)

    def __eq__(self, other):
        return isinstance(other, Ref) and self.cont is other.cont and self.key == other.key

    def __hash__(self):
        return hash((id(self.cont), self.key))

    def __bool__(self):
        return True

    def __repr__(self):
        return '0x%04x+%s' % (id(self.cont) & 0xFFFF, self.key)


class Frame:
    __slots__ = ('vars', 'parent')

    def __init__(self, parent=None):
        self.vars, self.parent = {}, parent

    def find(self, name):
        f = self
        while f is not None:
            if name in f.vars:
                return f.vars
            f = f.parent
        raise CRuntimeError("невідома змінна '%s'" % name)


def convert(value, t):
    """Перетворення значення до C-типу t при збереженні (емуляція переповнення)."""
    if t is None or t.ptr or t.dims:
        return value
    if isinstance(value, Ref):
        return value
    b = t.base
    if b in ('float', 'double'):
        return float(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CRuntimeError('перетворення nan/inf у ціле')
        value = int(value)             # int() відкидає дробову частину (до нуля) – як у C
    bits = {'char': 8, 'short': 16, 'int': 32, 'long': 64}.get(b, 32)
    value &= (1 << bits) - 1
    if not t.unsigned and value >= 1 << (bits - 1):
        value -= 1 << bits
    return value


class Interpreter:
    MAX_STEPS = 3_000_000
    MAX_DEPTH = 400

    def __init__(self, program, max_steps=None):
        self.program = program
        self.out = []
        self.steps = 0
        self.depth = 0
        self.max_steps = max_steps or self.MAX_STEPS
        self.funcs = {d.name: d for d in program.decls if isinstance(d, A.FuncDef)}
        self.globals = Frame()
        self.line = 0
        self.call_counts = {}
        self._sdisp = {}
        self._edisp = {}

    # ------------------------------------------------------------ запуск
    def run(self):
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 20000))
        exit_code, error = 0, None
        try:
            for d in self.program.decls:
                if isinstance(d, A.VarDecl):
                    self.declare(d, self.globals)
            exit_code = self.call_function('main', [])
            if not isinstance(exit_code, int):
                exit_code = 0
        except _Exit as ex:
            exit_code = ex.code
        except CRuntimeError as ex:
            error = {'phase': 'runtime', 'line': ex.line or self.line, 'col': 0, 'msg': str(ex)}
            exit_code = -1
        except ZeroDivisionError:
            error = {'phase': 'runtime', 'line': self.line, 'col': 0, 'msg': 'ділення на нуль'}
            exit_code = -1
        except RecursionError:
            error = {'phase': 'runtime', 'line': self.line, 'col': 0,
                     'msg': 'переповнення стеку (занадто глибока рекурсія)'}
            exit_code = -1
        finally:
            sys.setrecursionlimit(old_limit)
        return ''.join(self.out), exit_code, error

    # ------------------------------------------------------------ змінні
    def default_value(self, t):
        if t.dims:
            n = t.dims[0]
            el = t.element()
            return [self.default_value(el) for _ in range(n)]
        if t.ptr:
            return 0
        return 0.0 if t.base in ('float', 'double') else 0

    def fill(self, storage, t, init):
        """Заповнення масиву з ініціалізатора (вкладеного або «плаского»)."""
        if isinstance(init, A.StringLit):
            codes = [ord(c) for c in init.value]
            for i, c in enumerate(codes[:len(storage)]):
                storage[i] = convert(c, t.element())
            return
        items = init.items
        el = t.element()
        if el.is_array and not any(isinstance(x, (A.InitList, A.StringLit)) for x in items):
            flat = [self.eval(x) for x in items]          # int m[2][2] = {1,2,3,4};
            self._fill_flat(storage, t, iter(flat))
            return
        for i, it in enumerate(items[:len(storage)]):
            if el.is_array:
                if isinstance(it, (A.InitList, A.StringLit)):
                    self.fill(storage[i], el, it)
            else:
                v = it.items[0] if isinstance(it, A.InitList) else it
                storage[i] = convert(self.eval(v), el)

    def _fill_flat(self, storage, t, it):
        el = t.element()
        for i in range(len(storage)):
            if el.is_array:
                self._fill_flat(storage[i], el, it)
            else:
                try:
                    storage[i] = convert(next(it), el)
                except StopIteration:
                    return

    def declare(self, d, frame):
        t = d.vtype
        if t.dims:
            storage = self.default_value(t)
            if d.init is not None:
                self.fill(storage, t, d.init)
            frame.vars[d.name] = storage
        else:
            init = d.init
            if isinstance(init, A.InitList):
                init = init.items[0] if init.items else None
            frame.vars[d.name] = convert(self.eval(init), t) if init is not None else self.default_value(t)

    # ------------------------------------------------------------ виклики
    def call_function(self, name, args, line=0):
        f = self.funcs.get(name)
        if f is None:
            return self.call_builtin(name, args, line)
        self.depth += 1
        if self.depth > self.MAX_DEPTH:
            raise CRuntimeError('переповнення стеку викликів (рекурсія глибше %d)' % self.MAX_DEPTH, line)
        self.call_counts[name] = self.call_counts.get(name, 0) + 1
        frame = Frame(self.globals)
        for p, v in zip(f.params, args):
            frame.vars[p.name] = convert(v, p.ptype)
        try:
            self.exec_block(f.body.items, frame)
            result = 0
        except _Return as r:
            result = r.value
        finally:
            self.depth -= 1
        if f.ret.is_void:
            return None
        return convert(result if result is not None else 0, f.ret)

    def to_str(self, v):
        if isinstance(v, Ref):
            out, i = [], v.key
            cont = v.cont
            while isinstance(i, int) and i < len(cont) and cont[i] != 0:
                out.append(chr(cont[i] & 0xFF))
                i += 1
            return ''.join(out)
        if isinstance(v, list):
            return self.to_str(Ref(v, 0))
        return str(v)

    def call_builtin(self, name, args, line):
        if name == 'printf':
            fmt = self.to_str(args[0])
            conv = [self.to_str(a) if isinstance(a, Ref) else a for a in args[1:]]
            s = c_format(fmt, conv)
            self.out.append(s)
            return len(s)
        if name == 'puts':
            self.out.append(self.to_str(args[0]) + '\n')
            return 1
        if name == 'putchar':
            self.out.append(chr(int(args[0]) & 0xFF))
            return args[0]
        if name == 'strlen':
            return len(self.to_str(args[0]))
        if name == 'abs':
            return abs(int(args[0]))
        if name == 'exit':
            raise _Exit(int(args[0]))
        fn = {'fabs': math.fabs, 'sqrt': math.sqrt, 'floor': math.floor, 'ceil': math.ceil,
              'pow': math.pow}.get(name)
        if fn is None:
            raise CRuntimeError("невідома функція '%s'" % name, line)
        try:
            return float(fn(*[float(a) for a in args]))
        except (ValueError, OverflowError):
            return float('nan')

    # ------------------------------------------------------------ оператори
    def tick(self, node):
        self.steps += 1
        self.line = node.line
        if self.steps > self.max_steps:
            raise CRuntimeError('перевищено ліміт кроків виконання (%d) – можливо, нескінченний цикл'
                                % self.max_steps, node.line)

    def exec_block(self, items, frame):
        for item in items:
            self.exec(item, frame)

    def exec(self, s, frame):
        self.tick(s)
        m = self._sdisp.get(type(s))
        if m is None:
            m = self._sdisp[type(s)] = getattr(self, 'x_' + type(s).__name__)
        m(s, frame)

    def x_Compound(self, s, frame):
        self.exec_block(s.items, Frame(frame))

    def x_DeclList(self, s, frame):
        for d in s.decls:
            self.declare_local(d, frame)

    def declare_local(self, d, frame):
        saved = self.frame_for_eval
        self.frame_for_eval = frame
        try:
            self.declare(d, frame)
        finally:
            self.frame_for_eval = saved

    frame_for_eval = None

    def x_ExprStmt(self, s, frame):
        self.ev(s.expr, frame)

    def x_EmptyStmt(self, s, frame):
        pass

    def x_If(self, s, frame):
        if self.truth(self.ev(s.cond, frame)):
            self.exec(s.then, frame)
        elif s.other is not None:
            self.exec(s.other, frame)

    def x_While(self, s, frame):
        while self.truth(self.ev(s.cond, frame)):
            self.tick(s)
            try:
                self.exec(s.body, frame)
            except _Break:
                break
            except _Continue:
                continue

    def x_DoWhile(self, s, frame):
        while True:
            self.tick(s)
            try:
                self.exec(s.body, frame)
            except _Break:
                break
            except _Continue:
                pass
            if not self.truth(self.ev(s.cond, frame)):
                break

    def x_For(self, s, frame):
        f = Frame(frame)
        if isinstance(s.init, A.DeclList):
            for d in s.init.decls:
                self.declare_local(d, f)
        elif s.init is not None:
            self.ev(s.init, f)
        while s.cond is None or self.truth(self.ev(s.cond, f)):
            self.tick(s)
            try:
                self.exec(s.body, f)
            except _Break:
                break
            except _Continue:
                pass
            if s.step is not None:
                self.ev(s.step, f)

    def switch_segments(self, s):
        """Розгортання тіла switch у плаский список: мітки + оператори."""
        if hasattr(s, '_flat'):
            return s._flat
        flat = []

        def add(item):
            if isinstance(item, A.Case):
                flat.append(('case', item.value))
                add(item.stmt)
            elif isinstance(item, A.Default):
                flat.append(('default', None))
                add(item.stmt)
            else:
                flat.append(('stmt', item))
        items = s.body.items if isinstance(s.body, A.Compound) else [s.body]
        for it in items:
            add(it)
        s._flat = flat
        return flat

    def x_Switch(self, s, frame):
        v = self.ev(s.expr, frame)
        flat = self.switch_segments(s)
        start = None
        for i, (kind, val) in enumerate(flat):
            if kind == 'case' and val == v:
                start = i
                break
        if start is None:
            start = next((i for i, (k, _) in enumerate(flat) if k == 'default'), None)
        if start is None:
            return
        f = Frame(frame)
        try:
            for kind, item in flat[start:]:
                if kind == 'stmt':
                    self.exec(item, f)
        except _Break:
            pass

    def x_Case(self, s, frame):
        self.exec(s.stmt, frame)

    def x_Default(self, s, frame):
        self.exec(s.stmt, frame)

    def x_Break(self, s, frame):
        raise _Break()

    def x_Continue(self, s, frame):
        raise _Continue()

    def x_Return(self, s, frame):
        raise _Return(self.ev(s.expr, frame) if s.expr is not None else None)

    # ------------------------------------------------------------ вирази
    @staticmethod
    def truth(v):
        if isinstance(v, Ref):
            return True
        return v != 0

    def eval(self, e):
        """Обчислення в глобальному контексті / контексті оголошення."""
        return self.ev(e, self.frame_for_eval or self.globals)

    def ev(self, e, frame):
        m = self._edisp.get(type(e))
        if m is None:
            m = self._edisp[type(e)] = getattr(self, 'v_' + type(e).__name__)
        return m(e, frame)

    def rvalue(self, v):
        """Масив у виразі «розпадається» на вказівник на перший елемент."""
        return Ref(v, 0) if isinstance(v, list) else v

    # --- lvalue: повертає (контейнер, ключ, тип)
    def lvalue(self, e, frame):
        if isinstance(e, A.Id):
            return frame.find(e.name), e.name, e.ctype
        if isinstance(e, A.Index):
            base = self.rvalue(self.ev(e.base, frame))
            idx = self.ev(e.index, frame)
            if not isinstance(base, Ref) or not isinstance(base.key, int):
                raise CRuntimeError('індексування не-масиву', e.line)
            k = base.key + int(idx)
            if not (0 <= k < len(base.cont)):
                raise CRuntimeError('індекс %d поза межами масиву розміром %d' % (k, len(base.cont)), e.line)
            return base.cont, k, e.ctype
        if isinstance(e, A.Deref):
            p = self.ev(e.operand, frame)
            if not isinstance(p, Ref):
                raise CRuntimeError('розіменування нульового або недійсного вказівника', e.line)
            if isinstance(p.key, int) and not (0 <= p.key < len(p.cont)):
                raise CRuntimeError('розіменування вказівника за межами масиву', e.line)
            return p.cont, p.key, e.ctype
        raise CRuntimeError('вираз не є lvalue', e.line)

    def v_Const(self, e, frame):
        return e.value

    def v_StringLit(self, e, frame):
        if not hasattr(e, '_storage'):
            e._storage = [ord(c) for c in e.value] + [0]
        return Ref(e._storage, 0)

    def v_Id(self, e, frame):
        return self.rvalue(frame.find(e.name)[e.name])

    def v_Index(self, e, frame):
        cont, k, _ = self.lvalue(e, frame)
        return self.rvalue(cont[k])

    def v_Deref(self, e, frame):
        cont, k, _ = self.lvalue(e, frame)
        return self.rvalue(cont[k])

    def v_AddrOf(self, e, frame):
        if isinstance(e.operand, A.Id):
            store = frame.find(e.operand.name)
            v = store[e.operand.name]
            if isinstance(v, list):
                return Ref(v, 0)
            return Ref(store, e.operand.name)
        cont, k, _ = self.lvalue(e.operand, frame)
        if isinstance(cont[k], list):
            return Ref(cont[k], 0)
        return Ref(cont, k)

    def arith(self, op, a, b, line=0):
        # арифметика вказівників
        if isinstance(a, Ref) or isinstance(b, Ref):
            if op == '+':
                return a.offset(int(b)) if isinstance(a, Ref) else b.offset(int(a))
            if op == '-':
                if isinstance(b, Ref):
                    if a.cont is not b.cont:
                        raise CRuntimeError('різниця вказівників на різні масиви', line)
                    return a.key - b.key
                return a.offset(-int(b))
            if op in ('==', '!='):
                eq = (a == b) if isinstance(a, Ref) and isinstance(b, Ref) else False
                return int(eq if op == '==' else not eq)
            if op in ('<', '>', '<=', '>=') and isinstance(a, Ref) and isinstance(b, Ref):
                a, b = a.key, b.key
            else:
                raise CRuntimeError("операція '%s' над вказівником" % op, line)
        if op == '+':
            return a + b
        if op == '-':
            return a - b
        if op == '*':
            return a * b
        if op == '/':
            if isinstance(a, int) and isinstance(b, int):
                if b == 0:
                    raise CRuntimeError('цілочисельне ділення на нуль', line)
                return c_idiv(a, b)
            if b == 0:
                return math.copysign(math.inf, a) if a else math.nan
            return a / b
        if op == '%':
            if b == 0:
                raise CRuntimeError('остача від ділення на нуль', line)
            return c_imod(int(a), int(b))
        if op == '<':
            return int(a < b)
        if op == '>':
            return int(a > b)
        if op == '<=':
            return int(a <= b)
        if op == '>=':
            return int(a >= b)
        if op == '==':
            return int(a == b)
        if op == '!=':
            return int(a != b)
        if op == '&':
            return a & b
        if op == '|':
            return a | b
        if op == '^':
            return a ^ b
        if op == '<<':
            return a << b
        if op == '>>':
            return a >> b
        raise CRuntimeError('невідомий оператор ' + op, line)

    def v_BinOp(self, e, frame):
        op = e.op
        if op == '&&':
            return int(self.truth(self.ev(e.left, frame)) and self.truth(self.ev(e.right, frame)))
        if op == '||':
            return int(self.truth(self.ev(e.left, frame)) or self.truth(self.ev(e.right, frame)))
        a = self.ev(e.left, frame)
        b = self.ev(e.right, frame)
        r = self.arith(op, a, b, e.line)
        if e.ctype is not None and e.ctype.is_integer and isinstance(r, int):
            r = convert(r, e.ctype)                  # переповнення проміжних результатів int
        return r

    def v_UnaryOp(self, e, frame):
        v = self.ev(e.operand, frame)
        if e.op == '-':
            return convert(-v, e.ctype) if isinstance(v, int) else -v
        if e.op == '+':
            return v
        if e.op == '!':
            return int(not self.truth(v))
        if e.op == '~':
            return ~v
        raise CRuntimeError('невідомий унарний оператор', e.line)

    def v_IncDec(self, e, frame):
        cont, k, t = self.lvalue(e.target, frame)
        old = cont[k]
        delta = 1 if e.op == '++' else -1
        new = old.offset(delta) if isinstance(old, Ref) else convert(old + delta, t)
        cont[k] = new
        return new if e.prefix else old

    def v_Assign(self, e, frame):
        value = self.ev(e.value, frame)
        cont, k, t = self.lvalue(e.target, frame)
        if e.op != '=':
            value = self.arith(e.op[:-1], cont[k], value, e.line)
        if isinstance(value, list):
            raise CRuntimeError('присвоєння масиву', e.line)
        value = convert(value, t)
        cont[k] = value
        return value

    def v_Ternary(self, e, frame):
        return self.ev(e.then, frame) if self.truth(self.ev(e.cond, frame)) else self.ev(e.other, frame)

    def v_Call(self, e, frame):
        args = [self.ev(a, frame) for a in e.args]
        saved = self.line
        r = self.call_function(e.name, args, e.line)
        self.line = saved
        return r

    def v_Cast(self, e, frame):
        v = self.ev(e.operand, frame)
        if e.to.ptr:
            return v
        if isinstance(v, Ref):
            raise CRuntimeError('приведення вказівника до числа не підтримується', e.line)
        return convert(v, e.to)

    def v_SizeOf(self, e, frame):
        return e.value

    def v_Comma(self, e, frame):
        r = None
        for x in e.exprs:
            r = self.ev(x, frame)
        return r


def run(program, max_steps=None):
    it = Interpreter(program, max_steps)
    out, code, err = it.run()
    return out, code, err, {'steps': it.steps, 'calls': it.call_counts}
