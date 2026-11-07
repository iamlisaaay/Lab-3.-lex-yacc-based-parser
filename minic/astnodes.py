"""Вузли абстрактного синтаксичного дерева (AST) MiniC.

Кожен вузол знає:
  * _fields – список полів-нащадків (вузли або списки вузлів);
  * _attrs  – «листові» атрибути (ім'я, оператор, значення, тип);
  * line    – рядок у вихідному коді;
  * seq     – порядковий номер створення. Оскільки LALR-аналізатор будує дерево
              знизу-вгору (під час згорток), seq показує порядок згорток – це
              використовується для анімації побудови AST у браузері;
  * ctype   – тип виразу, який проставляє семантичний аналізатор.
"""
import itertools

_seq = itertools.count(1)


def reset_seq():
    global _seq
    _seq = itertools.count(1)


class Node:
    _fields = ()
    _attrs = ()
    category = 'node'

    def __init__(self, *args, line=0):
        names = self._attrs + self._fields
        if len(args) > len(names):
            raise TypeError('%s: забагато аргументів' % type(self).__name__)
        for name, value in zip(names, args):
            setattr(self, name, value)
        for name in names[len(args):]:
            setattr(self, name, None)
        self.line = line
        self.seq = next(_seq)
        self.ctype = None

    # нащадки у вигляді пар (роль, вузол)
    def children(self):
        for name in self._fields:
            value = getattr(self, name)
            if isinstance(value, Node):
                yield name, value
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Node):
                        yield name, item

    def label(self):
        return type(self).__name__

    def to_dict(self, role=None):
        """Серіалізація для d3.js (d3.hierarchy)."""
        d = {'name': self.label(), 'kind': type(self).__name__, 'cat': self.category,
             'line': self.line, 'seq': self.seq}
        if role:
            d['role'] = role
        if self.ctype is not None:
            d['ctype'] = str(self.ctype)
        attrs = {}
        for a in self._attrs:
            v = getattr(self, a)
            if v is not None and not isinstance(v, (Node, list)):
                attrs[a] = str(v)
        if attrs:
            d['attrs'] = attrs
        kids = [child.to_dict(r) for r, child in self.children()]
        if kids:
            d['children'] = kids
        return d

    def pretty(self, prefix='', is_last=True, role=None, out=None):
        """Текстове дерево для консолі."""
        top = out is None
        out = [] if top else out
        connector = '' if not prefix and role is None else ('└── ' if is_last else '├── ')
        extra = (' : ' + str(self.ctype)) if self.ctype is not None else ''
        out.append(prefix + connector + (role + ': ' if role else '') + self.label() + extra)
        kids = list(self.children())
        new_prefix = prefix + ('' if connector == '' else ('    ' if is_last else '│   '))
        for i, (r, ch) in enumerate(kids):
            ch.pretty(new_prefix, i == len(kids) - 1, r, out)
        return '\n'.join(out) if top else None

    def __repr__(self):
        return self.label()


# ---------------------------------------------------------------- програма
class Program(Node):
    _fields = ('decls',)
    category = 'program'


class FuncDef(Node):
    _attrs = ('ret', 'name')
    _fields = ('params', 'body')
    category = 'func'

    def label(self):
        return 'FuncDef %s %s()' % (self.ret, self.name)


class FuncDecl(Node):
    _attrs = ('ret', 'name')
    _fields = ('params',)
    category = 'func'

    def label(self):
        return 'FuncDecl %s %s()' % (self.ret, self.name)


class Param(Node):
    _attrs = ('ptype', 'name')
    category = 'decl'

    def label(self):
        return 'Param %s %s' % (self.ptype, self.name or '')


class VarDecl(Node):
    _attrs = ('vtype', 'name')
    _fields = ('init',)
    category = 'decl'

    def label(self):
        return 'VarDecl %s %s' % (self.vtype, self.name)


class InitList(Node):
    _fields = ('items',)
    category = 'expr'

    def label(self):
        return 'InitList {}'


class DeclList(Node):
    _fields = ('decls',)
    category = 'decl'


# ---------------------------------------------------------------- оператори
class Compound(Node):
    _fields = ('items',)
    category = 'stmt'

    def label(self):
        return 'Block { }'


class If(Node):
    _fields = ('cond', 'then', 'other')
    category = 'stmt'


class While(Node):
    _fields = ('cond', 'body')
    category = 'stmt'


class DoWhile(Node):
    _fields = ('body', 'cond')
    category = 'stmt'


class For(Node):
    _fields = ('init', 'cond', 'step', 'body')
    category = 'stmt'


class Switch(Node):
    _fields = ('expr', 'body')
    category = 'stmt'


class Case(Node):
    _fields = ('expr', 'stmt')
    category = 'stmt'


class Default(Node):
    _fields = ('stmt',)
    category = 'stmt'


class Return(Node):
    _fields = ('expr',)
    category = 'stmt'


class Break(Node):
    category = 'stmt'


class Continue(Node):
    category = 'stmt'


class ExprStmt(Node):
    _fields = ('expr',)
    category = 'stmt'


class EmptyStmt(Node):
    category = 'stmt'

    def label(self):
        return 'Empty ;'


# ---------------------------------------------------------------- вирази
class BinOp(Node):
    _attrs = ('op',)
    _fields = ('left', 'right')
    category = 'expr'

    def label(self):
        return 'BinOp ' + self.op


class UnaryOp(Node):
    _attrs = ('op',)
    _fields = ('operand',)
    category = 'expr'

    def label(self):
        return 'Unary ' + self.op


class IncDec(Node):
    _attrs = ('op', 'prefix')
    _fields = ('target',)
    category = 'expr'

    def label(self):
        return ('Pre' if self.prefix else 'Post') + ' ' + self.op


class Assign(Node):
    _attrs = ('op',)
    _fields = ('target', 'value')
    category = 'expr'

    def label(self):
        return 'Assign ' + self.op


class Ternary(Node):
    _fields = ('cond', 'then', 'other')
    category = 'expr'

    def label(self):
        return 'Ternary ?:'


class Call(Node):
    _attrs = ('name',)
    _fields = ('args',)
    category = 'expr'

    def label(self):
        return 'Call %s()' % self.name


class Index(Node):
    _fields = ('base', 'index')
    category = 'expr'

    def label(self):
        return 'Index [ ]'


class AddrOf(Node):
    _fields = ('operand',)
    category = 'expr'

    def label(self):
        return 'AddrOf &'


class Deref(Node):
    _fields = ('operand',)
    category = 'expr'

    def label(self):
        return 'Deref *'


class Cast(Node):
    _attrs = ('to',)
    _fields = ('operand',)
    category = 'expr'

    def label(self):
        return 'Cast (%s)' % self.to


class SizeOf(Node):
    _attrs = ('of_type',)
    _fields = ('operand',)
    category = 'expr'

    def label(self):
        return 'sizeof' + (' (%s)' % self.of_type if self.of_type is not None else '')


class Comma(Node):
    _fields = ('exprs',)
    category = 'expr'

    def label(self):
        return 'Comma ,'


class Id(Node):
    _attrs = ('name',)
    category = 'id'

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sym = None          # заповнює семантичний аналізатор

    def label(self):
        return self.name


class Const(Node):
    _attrs = ('value', 'kind')
    category = 'literal'

    def label(self):
        if self.kind == 'char':
            return repr(chr(self.value))
        return str(self.value)


class StringLit(Node):
    _attrs = ('value',)
    category = 'literal'

    def label(self):
        s = self.value.encode('unicode_escape').decode('ascii')
        return '"' + (s if len(s) <= 24 else s[:22] + '…') + '"'
