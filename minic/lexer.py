"""Лексичний аналізатор MiniC на базі PLY (Python Lex-Yacc) – аналог Lex/Flex.

PLY.lex збирає всі правила t_XXX в один великий регулярний вираз (master regex):
  * правила-функції додаються у порядку оголошення у файлі;
  * правила-рядки сортуються за спаданням довжини регулярного виразу
    (тому '<<=' перевіряється раніше за '<<', а '<<' раніше за '<');
  * односимвольні 'literals' перевіряються останніми.
"""
import ply.lex as lex

# Зарезервовані слова: ID-правило перевіряє цей словник (стандартний прийом Lex,
# щоб не роздувати автомат окремими регулярними виразами для кожного ключового слова).
reserved = {
    'void': 'VOID', 'char': 'CHAR', 'short': 'SHORT', 'int': 'INT', 'long': 'LONG',
    'float': 'FLOAT', 'double': 'DOUBLE', 'signed': 'SIGNED', 'unsigned': 'UNSIGNED',
    'const': 'CONST', 'static': 'STATIC', 'extern': 'EXTERN',
    'if': 'IF', 'else': 'ELSE', 'while': 'WHILE', 'do': 'DO', 'for': 'FOR',
    'switch': 'SWITCH', 'case': 'CASE', 'default': 'DEFAULT',
    'break': 'BREAK', 'continue': 'CONTINUE', 'return': 'RETURN', 'sizeof': 'SIZEOF',
}

tokens = [
    'ID', 'INT_CONST', 'FLOAT_CONST', 'CHAR_CONST', 'STRING_LITERAL',
    'INC_OP', 'DEC_OP', 'LEFT_OP', 'RIGHT_OP', 'LE_OP', 'GE_OP', 'EQ_OP', 'NE_OP',
    'AND_OP', 'OR_OP',
    'MUL_ASSIGN', 'DIV_ASSIGN', 'MOD_ASSIGN', 'ADD_ASSIGN', 'SUB_ASSIGN',
    'LEFT_ASSIGN', 'RIGHT_ASSIGN', 'AND_ASSIGN', 'XOR_ASSIGN', 'OR_ASSIGN',
] + sorted(set(reserved.values()))

literals = ';,{}()[]:=&!~-+*/%<>^|?'

_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0', '\\': '\\', "'": "'", '"': '"',
            'a': '\a', 'b': '\b', 'f': '\f', 'v': '\v', '?': '?'}


def unescape(body):
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == '\\' and i + 1 < len(body):
            n = body[i + 1]
            if n == 'x':
                j = i + 2
                while j < len(body) and body[j] in '0123456789abcdefABCDEF':
                    j += 1
                out.append(chr(int(body[i + 2:j] or '0', 16)))
                i = j
                continue
            if n in '01234567':
                j = i + 1
                while j < len(body) and j < i + 4 and body[j] in '01234567':
                    j += 1
                out.append(chr(int(body[i + 1:j], 8)))
                i = j
                continue
            out.append(_ESCAPES.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


class CLexer:
    tokens = tokens
    literals = literals
    t_ignore = ' \t\r\f\v'

    # багатосимвольні оператори (рядкові правила)
    t_LEFT_ASSIGN = r'<<='
    t_RIGHT_ASSIGN = r'>>='
    t_ADD_ASSIGN = r'\+='
    t_SUB_ASSIGN = r'-='
    t_MUL_ASSIGN = r'\*='
    t_DIV_ASSIGN = r'/='
    t_MOD_ASSIGN = r'%='
    t_AND_ASSIGN = r'&='
    t_XOR_ASSIGN = r'\^='
    t_OR_ASSIGN = r'\|='
    t_INC_OP = r'\+\+'
    t_DEC_OP = r'--'
    t_LEFT_OP = r'<<'
    t_RIGHT_OP = r'>>'
    t_LE_OP = r'<='
    t_GE_OP = r'>='
    t_EQ_OP = r'=='
    t_NE_OP = r'!='
    t_AND_OP = r'&&'
    t_OR_OP = r'\|\|'

    def __init__(self, errors=None):
        self.errors = errors if errors is not None else []
        self.lexer = lex.lex(module=self, optimize=False, debug=False)

    # ---- правила-функції (порядок важливий!) ---------------------------
    def t_COMMENT_BLOCK(self, t):
        r'/\*(.|\n)*?\*/'
        t.lexer.lineno += t.value.count('\n')          # коментар відкидається

    def t_COMMENT_LINE(self, t):
        r'//[^\n]*'

    def t_PREPROCESSOR(self, t):
        r'\#[^\n]*'

    def t_FLOAT_CONST(self, t):
        r'((\d+\.\d*|\.\d+)([eE][+-]?\d+)?|\d+[eE][+-]?\d+)[fFlL]?'
        t.value = float(t.value.rstrip('fFlL'))
        return t

    def t_INT_CONST(self, t):
        r'(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)[uUlL]*'
        s = t.value.rstrip('uUlL')
        if s[:2].lower() == '0x':
            t.value = int(s, 16)
        elif len(s) > 1 and s[0] == '0':
            t.value = int(s, 8)
        else:
            t.value = int(s)
        return t

    def t_CHAR_CONST(self, t):
        r"'([^'\\\n]|\\.|\\x[0-9a-fA-F]+|\\[0-7]{1,3})'"
        t.value = ord(unescape(t.value[1:-1])[0])
        return t

    def t_STRING_LITERAL(self, t):
        r'"([^"\\\n]|\\.)*"'
        t.value = unescape(t.value[1:-1])
        return t

    def t_ID(self, t):
        r'[A-Za-z_][A-Za-z0-9_]*'
        t.type = reserved.get(t.value, 'ID')
        return t

    def t_newline(self, t):
        r'\n+'
        t.lexer.lineno += len(t.value)

    def t_error(self, t):
        self.errors.append({'phase': 'lexer', 'line': t.lexer.lineno, 'col': self.column(t),
                            'msg': "Невідомий символ '%s'" % t.value[0]})
        t.lexer.skip(1)

    # ---- допоміжне ------------------------------------------------------
    def column(self, t):
        start = self.lexer.lexdata.rfind('\n', 0, t.lexpos) + 1
        return t.lexpos - start + 1

    def tokenize(self, text):
        """Повний список токенів (для вкладки 'Tokens' у веб-інтерфейсі)."""
        self.lexer.input(text)
        self.lexer.lineno = 1
        result = []
        for tok in iter(self.lexer.token, None):
            value = tok.value
            if tok.type == 'CHAR_CONST':
                value = repr(chr(value)) + ' (%d)' % value
            elif tok.type == 'STRING_LITERAL':
                value = '"' + value.encode('unicode_escape').decode('ascii') + '"'
            result.append({'type': tok.type, 'value': str(value), 'line': tok.lineno,
                           'col': self.column(tok)})
        return result
