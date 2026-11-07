"""Семантичний аналіз MiniC.

* таблиця символів із вкладеними областями видимості (scope chain);
* перевірка оголошень: неоголошені/повторно оголошені імена, кількість аргументів функцій;
* виведення та перевірка типів виразів (анотація node.ctype) – потрібна генераторам коду,
  наприклад, щоб відрізнити цілочисельне ділення 7/2 від дійсного 7.0/2;
* контекстні перевірки: break/continue поза циклом, case поза switch, return у void-функції,
  присвоєння не-lvalue, індексування не-масиву тощо;
* присвоєння унікальних імен (uname) для трансляції у мови з іншими правилами областей видимості.
"""
import keyword

from . import astnodes as A
from .ctype import CType, INT, DOUBLE, VOID, CHAR_PTR, arith_result
from .parser import const_eval

# Імена, які не можна використовувати в згенерованому Python/JS коді без перейменування
RESERVED = set(keyword.kwlist) | {
    'int', 'float', 'str', 'len', 'range', 'list', 'print', 'chr', 'ord', 'abs', 'min', 'max',
    'sum', 'input', 'bool', 'type', 'object', 'id', 'math', 'sys', 'exit', 'round', 'pow',
    # JavaScript
    'var', 'let', 'const', 'function', 'new', 'this', 'delete', 'typeof', 'instanceof', 'void',
    'switch', 'case', 'default', 'do', 'catch', 'throw', 'finally', 'debugger', 'enum', 'export',
    'extends', 'super', 'implements', 'interface', 'package', 'private', 'protected', 'public',
    'static', 'yield', 'await', 'arguments', 'eval', 'undefined', 'NaN', 'Infinity', 'Math',
    'Number', 'String', 'Array', 'Object', 'console', 'process', 'Deno', 'window', 'globalThis',
    'null', 'true', 'false', 'char', 'double', 'long', 'short', 'byte', 'boolean', 'goto',
    'native', 'transient', 'volatile', 'synchronized', 'throws', 'with',
}


def safe_name(name):
    if name in RESERVED or name.startswith('_rt_') or name.startswith('__'):
        return name + '_'
    return name


class Symbol:
    def __init__(self, name, ctype, kind, line=0, is_global=False):
        self.name, self.ctype, self.kind, self.line = name, ctype, kind, line
        self.is_global = is_global
        self.uname = safe_name(name)
        self.used = False
        self.params = None           # для функцій – список типів параметрів
        self.defined = False
        self.node = None

    def __repr__(self):
        return '%s %s %s' % (self.kind, self.ctype, self.name)


# name: (тип результату, мін. к-сть аргументів, макс. (None = змінна кількість))
BUILTINS = {
    'printf': (INT, 1, None), 'puts': (INT, 1, 1), 'putchar': (INT, 1, 1),
    'abs': (INT, 1, 1), 'fabs': (DOUBLE, 1, 1), 'sqrt': (DOUBLE, 1, 1), 'pow': (DOUBLE, 2, 2),
    'floor': (DOUBLE, 1, 1), 'ceil': (DOUBLE, 1, 1), 'strlen': (INT, 1, 1), 'exit': (VOID, 1, 1),
}


class Scope:
    def __init__(self, parent=None):
        self.parent, self.symbols = parent, {}

    def lookup(self, name):
        s = self
        while s:
            if name in s.symbols:
                return s.symbols[name]
            s = s.parent
        return None


class SemanticAnalyzer:
    def __init__(self):
        self.errors, self.warnings = [], []
        self.globals = Scope()
        self.scope = self.globals
        self.func = None              # поточна функція (FuncDef)
        self.loop_depth = 0
        self.switch_stack = []
        self.used_unames = set()
        self.global_unames = set()
        self.symbols_table = []       # для відображення у веб-інтерфейсі

    # ------------------------------------------------------------ helpers
    def error(self, node, msg):
        self.errors.append({'phase': 'semantic', 'line': getattr(node, 'line', 0), 'col': 0,
                            'msg': msg})

    def warn(self, node, msg):
        self.warnings.append({'phase': 'semantic', 'line': getattr(node, 'line', 0), 'col': 0,
                              'msg': msg})

    def declare(self, sym, node):
        if sym.name in self.scope.symbols:
            prev = self.scope.symbols[sym.name]
            self.error(node, "повторне оголошення '%s' (раніше в рядку %d)" % (sym.name, prev.line))
            return prev
        self.scope.symbols[sym.name] = sym
        if sym.is_global:
            self.global_unames.add(sym.uname)
        else:
            base, n = sym.uname, 1
            while sym.uname in self.used_unames or sym.uname in self.global_unames:
                sym.uname = '%s_%d' % (base, n)
                n += 1
            self.used_unames.add(sym.uname)
        self.symbols_table.append({
            'name': sym.name, 'type': str(sym.ctype), 'kind': sym.kind, 'line': sym.line,
            'scope': 'global' if sym.is_global else (self.func.name if self.func else '?'),
            'uname': sym.uname})
        return sym

    def push(self):
        self.scope = Scope(self.scope)

    def pop(self):
        for sym in self.scope.symbols.values():
            if not sym.used and sym.kind == 'var':
                self.warnings.append({'phase': 'semantic', 'line': sym.line, 'col': 0,
                                      'msg': "змінна '%s' оголошена, але не використовується"
                                             % sym.name})
        self.scope = self.scope.parent

    # ------------------------------------------------------------ вхід
    def analyze(self, program):
        # 1-й прохід: сигнатури всіх функцій (дозволяє взаємну рекурсію без прототипів)
        for d in program.decls:
            if isinstance(d, (A.FuncDef, A.FuncDecl)):
                self.declare_function(d)
        for d in program.decls:
            if isinstance(d, A.VarDecl):
                self.var_decl(d, is_global=True)
            elif isinstance(d, A.FuncDef):
                self.func_def(d)
        main = self.globals.lookup('main')
        if not main or main.kind != 'func' or not main.defined:
            self.errors.append({'phase': 'semantic', 'line': 0, 'col': 0,
                                'msg': "не знайдено функцію 'int main()' – програму неможливо запустити"})
        for sym in self.globals.symbols.values():
            if sym.kind == 'func' and not sym.defined and sym.used:
                self.error(sym.node, "функцію '%s' оголошено, але не визначено" % sym.name)
        return self.errors, self.warnings

    def declare_function(self, d):
        sym = self.globals.symbols.get(d.name)
        ptypes = [p.ptype for p in d.params]
        if sym:
            if sym.kind != 'func':
                self.error(d, "'%s' вже оголошено як змінну" % d.name)
                return
            if len(sym.params) != len(ptypes):
                self.error(d, "конфлікт оголошень функції '%s': різна кількість параметрів" % d.name)
            if isinstance(d, A.FuncDef):
                if sym.defined:
                    self.error(d, "повторне визначення функції '%s'" % d.name)
                sym.defined, sym.node = True, d
            return
        if d.name in BUILTINS:
            self.warn(d, "функція '%s' перевизначає вбудовану" % d.name)
        sym = Symbol(d.name, d.ret, 'func', d.line, is_global=True)
        sym.params = ptypes
        sym.defined = isinstance(d, A.FuncDef)
        sym.node = d
        self.declare(sym, d)
        d.sym = sym

    def func_def(self, f):
        self.func = f
        f.sym = self.globals.lookup(f.name)
        f.globals_assigned = set()
        f.has_return_value = False
        self.used_unames = set()
        self.push()
        for p in f.params:
            if p.name is None:
                self.error(p, 'параметр функції без імені')
                continue
            if p.ptype.is_void:
                self.error(p, "параметр '%s' не може мати тип void" % p.name)
            sym = Symbol(p.name, p.ptype, 'param', p.line)
            sym.used = True
            p.sym = self.declare(sym, p)
        self.compound(f.body, new_scope=False)
        self.pop()
        if not f.ret.is_void and not f.has_return_value and f.name != 'main':
            self.warn(f, "функція '%s' не повертає значення" % f.name)
        self.func = None

    # ------------------------------------------------------------ оголошення
    def var_decl(self, d, is_global=False):
        t = d.vtype
        if t.is_void:
            self.error(d, "змінна '%s' не може мати тип void" % d.name)
        init = d.init
        # виведення розміру масиву з ініціалізатора: int a[] = {1,2,3}; char s[] = "hi";
        if t.dims and t.dims[0] is None:
            if isinstance(init, A.InitList):
                d.vtype = t = t.copy(dims=(len(init.items),) + t.dims[1:])
            elif isinstance(init, A.StringLit):
                d.vtype = t = t.copy(dims=(len(init.value) + 1,) + t.dims[1:])
            else:
                self.error(d, "невідомий розмір масиву '%s'" % d.name)
                d.vtype = t = t.copy(dims=(1,) + t.dims[1:])
        if None in t.dims:
            self.error(d, "невказаний розмір внутрішнього виміру масиву '%s'" % d.name)
            d.vtype = t = t.copy(dims=tuple(x or 1 for x in t.dims))
        if init is not None:
            self.check_initializer(d, t, init)
        sym = Symbol(d.name, t, 'var', d.line, is_global)
        if is_global:
            sym.used = True
        d.sym = self.declare(sym, d)

    def check_initializer(self, d, t, init):
        if isinstance(init, A.InitList):
            if not t.is_array:
                if len(init.items) != 1:
                    self.error(d, "скалярну змінну '%s' ініціалізовано списком" % d.name)
                for it in init.items:
                    self.check_initializer(d, t, it)
                return
            if len(init.items) > t.dims[0]:
                self.error(d, "забагато ініціалізаторів для масиву '%s'" % d.name)
            el = t.element()
            for it in init.items:
                if isinstance(it, A.InitList) or el.is_array:
                    if isinstance(it, A.InitList):
                        self.check_initializer(d, el, it)
                    else:
                        self.expr(it)
                else:
                    self.check_initializer(d, el, it)
            return
        if t.is_array:
            if isinstance(init, A.StringLit) and t.base == 'char' and len(t.dims) == 1:
                init.ctype = CHAR_PTR
                if len(init.value) + 1 > t.dims[0]:
                    self.error(d, "рядок задовгий для масиву '%s'" % d.name)
                return
            self.error(d, "масив '%s' потрібно ініціалізувати списком {...}" % d.name)
            return
        vt = self.expr(init)
        self.check_assign_compat(init, t, vt)

    def check_assign_compat(self, node, target, value):
        if value is None or target is None:
            return
        if target.is_arith and value.is_arith:
            return
        if target.is_pointer:
            if value.is_pointer or value.is_array:
                if value.base != target.base and target.base != 'void' and value.base != 'void':
                    self.warn(node, 'несумісні типи вказівників: %s та %s' % (target, value))
                return
            if isinstance(node, A.Const) and node.value == 0:
                return
            self.warn(node, 'присвоєння цілого числа вказівнику (%s)' % target)
            return
        if target.is_arith and (value.is_pointer or value.is_array):
            self.warn(node, 'присвоєння вказівника змінній типу %s' % target)
            return
        if value.is_void:
            self.error(node, 'використання значення void-виразу')

    # ------------------------------------------------------------ оператори
    def stmt(self, s):
        if s is None:
            return
        m = getattr(self, 's_' + type(s).__name__, None)
        if m is None:
            self.error(s, 'непідтримуваний оператор %s' % type(s).__name__)
        else:
            m(s)

    def compound(self, c, new_scope=True):
        if new_scope:
            self.push()
        for item in c.items:
            self.stmt(item)
        if new_scope:
            self.pop()

    def s_Compound(self, c):
        self.compound(c)

    def s_DeclList(self, d):
        for v in d.decls:
            if isinstance(v, A.VarDecl):
                self.var_decl(v)
            else:
                self.error(v, 'оголошення функції всередині блоку не підтримується')

    def s_ExprStmt(self, s):
        self.expr(s.expr)

    def s_EmptyStmt(self, s):
        pass

    def cond(self, e):
        t = self.expr(e)
        if t is not None and not (t.is_scalar or t.is_array):
            self.error(e, 'умова має бути скалярного типу')

    def s_If(self, s):
        self.cond(s.cond)
        self.stmt(s.then)
        self.stmt(s.other)

    def loop_body(self, body):
        self.loop_depth += 1
        saved = self.switch_stack
        self.switch_stack = []        # case всередині циклу всередині switch – вже не той switch
        self.stmt(body)
        self.switch_stack = saved
        self.loop_depth -= 1

    def s_While(self, s):
        self.cond(s.cond)
        self.loop_body(s.body)

    def s_DoWhile(self, s):
        self.loop_body(s.body)
        self.cond(s.cond)

    def s_For(self, s):
        self.push()
        if isinstance(s.init, A.DeclList):
            self.s_DeclList(s.init)
        elif s.init is not None:
            self.expr(s.init)
        if s.cond is not None:
            self.cond(s.cond)
        if s.step is not None:
            self.expr(s.step)
        self.loop_body(s.body)
        self.pop()

    def s_Switch(self, s):
        t = self.expr(s.expr)
        if t is not None and not t.is_integer:
            self.error(s, 'вираз switch має бути цілого типу')
        self.switch_stack.append({'values': set(), 'default': False, 'node': s})
        # сегменти switch: case-мітки мають бути безпосередньо у тілі (без Duff's device)
        body_items = s.body.items if isinstance(s.body, A.Compound) else [s.body]
        self.push()
        for item in body_items:
            self.stmt(item)
        self.pop()
        self.switch_stack.pop()

    def s_Case(self, s):
        if not self.switch_stack:
            self.error(s, "мітка 'case' поза оператором switch")
        else:
            self.expr(s.expr)
            try:
                s.value = int(const_eval(s.expr))
            except (ValueError, TypeError, ZeroDivisionError):
                self.error(s, 'значення case має бути цілою константою')
                s.value = 0
            info = self.switch_stack[-1]
            if s.value in info['values']:
                self.error(s, 'повторне значення case %d' % s.value)
            info['values'].add(s.value)
        self.stmt(s.stmt)

    def s_Default(self, s):
        if not self.switch_stack:
            self.error(s, "мітка 'default' поза оператором switch")
        elif self.switch_stack[-1]['default']:
            self.error(s, "повторна мітка 'default'")
        else:
            self.switch_stack[-1]['default'] = True
        self.stmt(s.stmt)

    def s_Break(self, s):
        if self.loop_depth == 0 and not self.switch_stack:
            self.error(s, "'break' поза циклом або switch")

    def s_Continue(self, s):
        if self.loop_depth == 0:
            self.error(s, "'continue' поза циклом")

    def s_Return(self, s):
        ret = self.func.ret
        if s.expr is None:
            if not ret.is_void:
                self.warn(s, "'return' без значення у функції, що повертає %s" % ret)
            return
        t = self.expr(s.expr)
        self.func.has_return_value = True
        if ret.is_void:
            self.error(s, "void-функція '%s' не може повертати значення" % self.func.name)
        else:
            self.check_assign_compat(s.expr, ret, t)

    # ------------------------------------------------------------ вирази
    def expr(self, e):
        m = getattr(self, 'e_' + type(e).__name__, None)
        if m is None:
            self.error(e, 'непідтримуваний вираз %s' % type(e).__name__)
            t = INT
        else:
            t = m(e)
        e.ctype = t
        return t

    def is_lvalue(self, e):
        if isinstance(e, A.Id):
            return e.sym is not None and e.sym.kind in ('var', 'param') and not e.ctype.is_array
        if isinstance(e, A.Index):
            return e.ctype is not None and not e.ctype.is_array
        return isinstance(e, A.Deref)

    def mark_assigned(self, target):
        if isinstance(target, A.Id) and target.sym and target.sym.is_global and self.func:
            self.func.globals_assigned.add(target.sym.uname)

    def e_Const(self, e):
        return DOUBLE if e.kind == 'float' else INT

    def e_StringLit(self, e):
        return CHAR_PTR

    def e_Id(self, e):
        sym = self.scope.lookup(e.name)
        if sym is None:
            self.error(e, "неоголошений ідентифікатор '%s'" % e.name)
            return INT
        if sym.kind == 'func':
            self.error(e, "ім'я функції '%s' використано як змінну" % e.name)
            return INT
        sym.used = True
        e.sym = sym
        return sym.ctype

    def e_BinOp(self, e):
        lt, rt = self.expr(e.left), self.expr(e.right)
        op = e.op
        if op in ('&&', '||'):
            return INT
        if op in ('<', '>', '<=', '>=', '==', '!='):
            return INT
        lp = lt.is_pointer or lt.is_array
        rp = rt.is_pointer or rt.is_array
        if op in ('+', '-') and (lp or rp):
            if op == '+' and lp and rp:
                self.error(e, 'не можна додавати два вказівники')
                return INT
            if op == '-' and lp and rp:
                return INT                     # різниця вказівників
            if rp and op == '-':
                self.error(e, 'не можна віднімати вказівник від числа')
                return INT
            ptr = lt if lp else rt
            other = rt if lp else lt
            if not other.is_integer:
                self.error(e, 'арифметика вказівників вимагає цілого зміщення')
            return ptr.decay() if ptr.is_array else ptr
        if not (lt.is_arith and rt.is_arith):
            self.error(e, "невірні типи операндів для '%s': %s та %s" % (op, lt, rt))
            return INT
        if op in ('%', '&', '|', '^', '<<', '>>'):
            if not (lt.is_integer and rt.is_integer):
                self.error(e, "оператор '%s' вимагає цілих операндів" % op)
            return arith_result(lt, rt) if op not in ('<<', '>>') else CType(lt.base if lt.base == 'long' else 'int', unsigned=lt.unsigned)
        if op == '/' and isinstance(e.right, A.Const) and e.right.value == 0:
            self.warn(e, 'ділення на нуль')
        return arith_result(lt, rt)

    def e_UnaryOp(self, e):
        t = self.expr(e.operand)
        if e.op == '!':
            return INT
        if e.op == '~':
            if not t.is_integer:
                self.error(e, "оператор '~' вимагає цілого операнда")
            return INT if t.base == 'char' else t
        if not t.is_arith:
            self.error(e, "унарний '%s' вимагає числового операнда" % e.op)
            return INT
        return INT if t.base in ('char', 'short') else t

    def e_IncDec(self, e):
        t = self.expr(e.target)
        if not self.is_lvalue(e.target):
            self.error(e, "операнд '%s' має бути змінною (lvalue)" % e.op)
        elif not (t.is_arith or t.is_pointer):
            self.error(e, "'%s' незастосовний до типу %s" % (e.op, t))
        self.mark_assigned(e.target)
        return t

    def e_Assign(self, e):
        tt = self.expr(e.target)
        vt = self.expr(e.value)
        if isinstance(e.target, A.Id) and e.target.sym is None:
            return tt                       # вже повідомлено «неоголошений ідентифікатор»
        if not self.is_lvalue(e.target):
            if tt.is_array:
                self.error(e, 'масиву не можна присвоїти значення')
            else:
                self.error(e, 'ліва частина присвоєння не є lvalue')
            return tt
        if tt.const:
            self.error(e, 'присвоєння константі')
        self.mark_assigned(e.target)
        if e.op == '=':
            self.check_assign_compat(e.value, tt, vt)
        else:
            op = e.op[:-1]
            if op in ('%', '&', '|', '^', '<<', '>>') and not (tt.is_integer and vt.is_integer):
                self.error(e, "оператор '%s' вимагає цілих операндів" % e.op)
            elif tt.is_pointer and op in ('+', '-'):
                if not vt.is_integer:
                    self.error(e, 'арифметика вказівників вимагає цілого зміщення')
            elif not (tt.is_arith and vt.is_arith):
                self.error(e, "невірні типи для '%s'" % e.op)
        return tt

    def e_Ternary(self, e):
        self.cond(e.cond)
        a, b = self.expr(e.then), self.expr(e.other)
        if a.is_arith and b.is_arith:
            return arith_result(a, b) if a != b else a
        return a

    def e_Call(self, e):
        sym = self.globals.lookup(e.name)
        arg_types = [self.expr(a) for a in e.args]
        if sym is not None and sym.kind == 'func':
            sym.used = True
            e.sym = sym
            if len(arg_types) != len(sym.params):
                self.error(e, "функція '%s' очікує %d аргумент(ів), передано %d"
                           % (e.name, len(sym.params), len(arg_types)))
            for a, at, pt in zip(e.args, arg_types, sym.params):
                if pt.is_array or pt.is_pointer:
                    if not (at.is_array or at.is_pointer) and not (isinstance(a, A.Const) and a.value == 0):
                        self.error(a, "аргумент для параметра-масиву/вказівника функції '%s' має бути масивом або вказівником" % e.name)
                elif at.is_array or at.is_pointer:
                    self.error(a, "передано масив/вказівник у параметр типу %s функції '%s'" % (pt, e.name))
            return sym.ctype
        if e.name in BUILTINS:
            e.sym = None
            ret, lo, hi = BUILTINS[e.name]
            if len(arg_types) < lo or (hi is not None and len(arg_types) > hi):
                self.error(e, "неправильна кількість аргументів для '%s'" % e.name)
            if e.name == 'printf' and e.args and not isinstance(e.args[0], A.StringLit):
                self.warn(e, 'форматний рядок printf не є літералом')
            return ret
        self.error(e, "виклик неоголошеної функції '%s'" % e.name)
        return INT

    def e_Index(self, e):
        bt = self.expr(e.base)
        it = self.expr(e.index)
        if not it.is_integer:
            self.error(e, 'індекс масиву має бути цілим')
        if not (bt.is_array or bt.is_pointer):
            self.error(e, 'індексування значення, що не є масивом чи вказівником (%s)' % bt)
            return INT
        if bt.is_array and isinstance(e.index, A.Const) and bt.dims[0] is not None:
            if not (0 <= e.index.value < bt.dims[0]):
                self.warn(e, 'індекс %d поза межами масиву [0..%d]' % (e.index.value, bt.dims[0] - 1))
        return bt.element()

    def e_AddrOf(self, e):
        t = self.expr(e.operand)
        if isinstance(e.operand, A.Id) and t.is_array:
            return t.decay()
        if not self.is_lvalue(e.operand):
            self.error(e, "операнд '&' має бути змінною або елементом масиву")
        return t.pointer_to()

    def e_Deref(self, e):
        t = self.expr(e.operand)
        if not (t.is_pointer or t.is_array):
            self.error(e, "розіменування ('*') не-вказівника типу %s" % t)
            return INT
        return t.element()

    def e_Cast(self, e):
        self.expr(e.operand)
        return e.to

    def e_SizeOf(self, e):
        if e.of_type is not None:
            e.value = e.of_type.size()
        else:
            e.value = self.expr(e.operand).size()
        return CType('long', unsigned=True)

    def e_Comma(self, e):
        t = INT
        for x in e.exprs:
            t = self.expr(x)
        return t

    def e_InitList(self, e):
        self.error(e, 'список ініціалізації можна використовувати лише в оголошенні')
        return INT


def analyze(program):
    sa = SemanticAnalyzer()
    errors, warnings = sa.analyze(program)
    return errors, warnings, sa.symbols_table
