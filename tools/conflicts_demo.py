"""Демонстрація конфліктів LALR-аналізу та способів їх розв'язання у yacc (PLY).

    python tools/conflicts_demo.py

1. Неоднозначна граматика виразів  E → E+E | E-E | E*E | num
   а) без таблиці пріоритетів: shift/reduce конфлікти; yacc за замовчуванням обирає SHIFT,
      тому 10-4-3 рахується як 10-(4-3)=9, а 2*3+4 як 2*(3+4)=14  (неправильно!);
   б) з %left '+' '-'  %left '*' : конфлікти розв'язуються пріоритетами → 3 і 10.
2. «Висячий else»: S → if c S | if c S else S | x — 1 shift/reduce конфлікт;
   shift за замовчуванням прив'язує else до найближчого if (як вимагає стандарт C);
   %prec IFX / %nonassoc ELSE прибирає попередження.
3. Reduce/reduce конфлікт: A → id, B → id в однаковому контексті – yacc обирає правило,
   яке оголошене РАНІШЕ у файлі граматики (а це майже завжди помилка в граматиці).
4. Граматика LR(1), але НЕ LALR(1): при злитті LR(1)-станів з однаковими ядрами виникає
   reduce/reduce конфлікт, якого немає в канонічному LR(1)-автоматі.
"""
import io
import os
import re
import sys

import ply.yacc as yacc

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'conflicts_out')
os.makedirs(OUT, exist_ok=True)


class Tok:
    def __init__(self, type_, value, pos):
        self.type, self.value, self.lineno, self.lexpos = type_, value, 1, pos

    def __repr__(self):
        return '%s(%r)' % (self.type, self.value)


class MiniLexer:
    """Мінімальний лексер із інтерфейсом PLY (input/token) для демонстраційних граматик."""

    def __init__(self, classify):
        self.classify = classify

    def input(self, text):
        self.toks = [Tok(*self.classify(m.group(0)), m.start())
                     for m in re.finditer(r'\d+|if|else|id|[a-z]|\S', text)]
        self.toks.reverse()

    def token(self):
        return self.toks.pop() if self.toks else None


def build(obj, name):
    log = io.StringIO()
    lexer = MiniLexer(obj.classify)
    parser = yacc.yacc(module=obj, debug=True, debugfile=name + '.out', outputdir=OUT,
                       write_tables=False, errorlog=yacc.PlyLogger(log))
    text = log.getvalue()
    sr = re.search(r'(\d+) shift/reduce conflict', text)
    rr = re.search(r'(\d+) reduce/reduce conflict', text)
    return lexer, parser, (int(sr.group(1)) if sr else 0), (int(rr.group(1)) if rr else 0), text


def header(title):
    print('\n' + '=' * 78 + '\n' + title + '\n' + '=' * 78)


# ---------------------------------------------------------------------------- 1
class ExprGrammar:
    tokens = ('NUM',)
    literals = '+-*()'

    def __init__(self, with_precedence):
        if with_precedence:
            # аналог:  %left '+' '-'
            #          %left '*'
            self.precedence = (('left', '+', '-'), ('left', '*'))

    @staticmethod
    def classify(w):
        return ('NUM', int(w)) if w.isdigit() else (w, w)

    def p_e_bin(self, p):
        '''e : e '+' e
             | e '-' e
             | e '*' e'''
        a, b = p[1], p[3]
        p[0] = (a[0] + b[0] if p[2] == '+' else a[0] - b[0] if p[2] == '-' else a[0] * b[0],
                '(%s %s %s)' % (a[1], p[2], b[1]))

    def p_e_num(self, p):
        '''e : NUM'''
        p[0] = (p[1], str(p[1]))

    def p_e_paren(self, p):
        '''e : '(' e ')' '''
        p[0] = p[2]

    def p_error(self, p):
        print('  syntax error', p)


# ---------------------------------------------------------------------------- 2
class IfGrammar:
    tokens = ('IF', 'ELSE', 'C', 'X')

    def __init__(self, with_precedence):
        if with_precedence:
            self.precedence = (('nonassoc', 'IFX'), ('nonassoc', 'ELSE'))
            self.p_s_if.__func__.__doc__ = '''s : IF C s %prec IFX'''

    @staticmethod
    def classify(w):
        return {'if': 'IF', 'else': 'ELSE', 'c': 'C'}.get(w, 'X'), w

    def p_s_if(self, p):
        '''s : IF C s'''
        p[0] = 'if(%s)' % p[3]

    def p_s_ifelse(self, p):
        '''s : IF C s ELSE s'''
        p[0] = 'if(%s else %s)' % (p[3], p[5])

    def p_s_x(self, p):
        '''s : X'''
        p[0] = 'x'

    def p_error(self, p):
        print('  syntax error', p)


# ---------------------------------------------------------------------------- 3
class RRGrammar:
    tokens = ('ID', 'X')

    @staticmethod
    def classify(w):
        return ('ID' if w == 'id' else 'X'), w

    def p_s(self, p):
        '''s : a X
             | b X'''
        p[0] = 's(%s)' % p[1]

    def p_a(self, p):
        '''a : ID'''
        p[0] = 'A'

    def p_b(self, p):
        '''b : ID'''
        p[0] = 'B'

    def p_error(self, p):
        print('  syntax error', p)


# ---------------------------------------------------------------------------- 4
class NotLALR:
    """S → a A d | b B d | a B e | b A e ;  A → c ;  B → c   (класичний приклад з Dragon Book)."""
    tokens = ('A', 'B', 'C', 'D', 'E')

    @staticmethod
    def classify(w):
        return w.upper(), w

    def p_s(self, p):
        '''s : A x D
             | A y E
             | B x E
             | B y D'''
        p[0] = ''.join(str(v) for v in p[1:])

    def p_x(self, p):
        '''x : C'''
        p[0] = 'X'

    def p_y(self, p):
        '''y : C'''
        p[0] = 'Y'

    def p_error(self, p):
        print('  syntax error at', p.value if p else 'EOF')


def main():
    header('1. Неоднозначна граматика виразів:  e : e + e | e - e | e * e | NUM')
    for prec in (False, True):
        lexer, parser, sr, rr, _ = build(ExprGrammar(prec), 'expr_prec' if prec else 'expr_noprec')
        print('\n%s таблиці пріоритетів: shift/reduce = %d, reduce/reduce = %d'
              % ('З' if prec else 'БЕЗ', sr, rr))
        for src in ('10 - 4 - 3', '2 * 3 + 4', '2 + 3 * 4'):
            val, tree = parser.parse(src, lexer=lexer)
            print('   %-12s →  %-22s = %d' % (src, tree, val))
    print('\n  Висновок: за замовчуванням yacc обирає SHIFT, що дає правоасоціативність і ігнорує\n'
          '  пріоритет. %left/%right/%nonassoc задають пріоритет токенам; правило отримує пріоритет\n'
          '  свого останнього термінала. Конфлікт S/R: якщо пріоритет правила > токена → reduce,\n'
          '  менший → shift, рівний → за асоціативністю (left → reduce, right → shift, nonassoc → error).')

    header('2. «Висячий else»:  s : IF C s | IF C s ELSE s | X')
    for prec in (False, True):
        lexer, parser, sr, rr, _ = build(IfGrammar(prec), 'if_prec' if prec else 'if_noprec')
        print('\n%s %%prec: shift/reduce = %d' % ('З' if prec else 'БЕЗ', sr))
        print('   if c if c x else x  →  %s' % parser.parse('if c if c x else x', lexer=lexer))
    print('\n  Висновок: в обох випадках else належить внутрішньому if (shift).\n'
          '  %prec IFX лише явно фіксує рішення і прибирає попередження (як у граматиці MiniC).')
    IfGrammar.p_s_if.__doc__ = '''s : IF C s'''

    header('3. Reduce/reduce:  s : a X | b X ;  a : ID ;  b : ID')
    lexer, parser, sr, rr, log = build(RRGrammar(), 'rr')
    print('shift/reduce = %d, reduce/reduce = %d' % (sr, rr))
    for line in log.splitlines():
        if 'reduce/reduce' in line or 'rejected' in line.lower():
            print('   PLY:', line.strip())
    print('   "id x" → %s   (обрано правило a : ID — воно оголошене раніше)' % parser.parse('id x', lexer=lexer))
    print('  Висновок: R/R конфлікт yacc «розв\'язує» на користь правила, що стоїть раніше у\n'
          '  граматиці; правило b : ID стає недосяжним. Такий конфлікт треба усувати переписуванням граматики.')

    header('4. LR(1), але не LALR(1):  s : A x D | A y E | B x E | B y D ;  x : C ;  y : C')
    lexer, parser, sr, rr, log = build(NotLALR(), 'not_lalr')
    print('shift/reduce = %d, reduce/reduce = %d' % (sr, rr))
    print('  У канонічному LR(1) стани [x → c·, d] (після a c) і [y → c·, e] (після a c) та\n'
          '  [x → c·, e], [y → c·, d] (після b c) – різні. LALR зливає стани з однаковим ядром\n'
          '  {x → c·, y → c·}, об\'єднуючи lookahead-и → {d, e} для обох правил → reduce/reduce.')
    for src in ('acd', 'ace', 'bce', 'bcd'):
        print('   "%s" → %s' % (src, parser.parse(src, lexer=lexer)))
    print('   Рядки "ace" та "bcd" належать мові, але LALR(1)-аналізатор їх ВІДКИДАЄ: після злиття\n'
          '   станів R/R конфлікт розв\'язано на користь x → c, тож правило y → c ніколи не застосовується.\n'
          '   Канонічний LR(1) (або GLR, %glr-parser у bison) розібрав би всі чотири рядки.')
    print('\nДетальні описи автоматів: %s' % OUT)


if __name__ == '__main__':
    main()
