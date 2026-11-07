"""Спільні частини генераторів коду."""
from . import astnodes as A


class CodegenError(Exception):
    def __init__(self, msg, line=0):
        super().__init__(msg)
        self.line = line


class Emitter:
    """Накопичувач рядків коду з відступами."""

    def __init__(self, indent='    '):
        self.lines, self.level, self.indent = [], 0, indent

    def emit(self, line=''):
        self.lines.append((self.indent * self.level + line) if line else '')

    def text(self):
        return '\n'.join(self.lines) + '\n'


def flatten_switch(sw):
    """Тіло switch -> список сегментів [(labels, [stmts])], labels: список значень або 'default'."""
    segments = []
    items = sw.body.items if isinstance(sw.body, A.Compound) else [sw.body]

    def add(item):
        if isinstance(item, (A.Case, A.Default)):
            label = item.value if isinstance(item, A.Case) else 'default'
            if segments and not segments[-1][1]:
                segments[-1][0].append(label)        # case 1: case 2: ...
            else:
                segments.append(([label], []))
            add(item.stmt)
        else:
            if not segments:
                segments.append(([], []))           # недосяжний код перед першою міткою
            segments[-1][1].append(item)
    for it in items:
        add(it)
    return segments


def is_atom(e):
    return isinstance(e, (A.Id, A.Const, A.StringLit, A.Call, A.Index, A.SizeOf))


COMPARISON = ('<', '>', '<=', '>=', '==', '!=')
