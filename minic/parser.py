"""Синтаксичний аналізатор MiniC на базі PLY.yacc – аналог YACC/Bison.

Граматика побудована за зразком класичної ANSI C Yacc-граматики (Jutta Degener, 1985/1995):
ієрархія нетерміналів primary -> postfix -> unary -> cast -> multiplicative -> ... -> assignment
кодує пріоритети та асоціативність операторів *без* таблиці %left/%right.

PLY генерує LALR(1)-таблиці (ACTION / GOTO) за алгоритмом DeRemer–Pennello, так само як yacc.
Опис усіх станів автомата записується у файл minic/generated/parser.out.

Єдиний класичний конфлікт C-граматики – «висячий else» (shift/reduce) – розв'язаний явно через
таблицю пріоритетів: правило `IF ( e ) stmt` отримує пріоритет IFX, що нижчий за ELSE,
тому yacc обирає shift (else прив'язується до найближчого if). У результаті: 0 конфліктів.
"""
import io
import os

import ply.yacc as yacc

from . import astnodes as A
from .ctype import CType
from .lexer import CLexer, tokens  # noqa: F401  (yacc шукає змінну `tokens` у модулі)

GEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generated')

start = 'translation_unit'

# Таблиця пріоритетів (аналог %nonassoc у yacc). Чим нижче в списку – тим вищий пріоритет.
precedence = (
    ('nonassoc', 'IFX'),     # фіктивний токен для правила if без else  (%prec IFX)
    ('nonassoc', 'ELSE'),
)

_errors = []        # помилки поточного розбору


def _err(line, msg):
    _errors.append({'phase': 'parser', 'line': line, 'col': 0, 'msg': msg})


# ======================================================================
#  Допоміжні структури для декларатора C
# ======================================================================
class Declarator:
    """Проміжне представлення декларатора: *name[10] або name(int a, int b)."""

    def __init__(self, name, line):
        self.name, self.line = name, line
        self.ptr, self.dims, self.params = 0, [], None
        self.paren_ptr = False

    def make_type(self, spec):
        return CType(spec.base, spec.ptr + self.ptr, self.dims, spec.unsigned, spec.const)


def make_specifiers(specs, line):
    """Перетворює список специфікаторів ['unsigned','long','int'] у базовий CType."""
    words = [s for s in specs if s not in ('static', 'extern', 'const')]
    const = 'const' in specs
    unsigned = 'unsigned' in words
    if 'double' in words:
        base = 'double'
    elif 'float' in words:
        base = 'float'
    elif 'char' in words:
        base = 'char'
    elif 'void' in words:
        base = 'void'
    elif 'short' in words:
        base = 'short'
    elif 'long' in words:
        base = 'long'
    else:
        base = 'int'
    bases = [w for w in words if w in ('void', 'char', 'int', 'float', 'double')]
    if len(bases) > 1:
        _err(line, 'некоректна комбінація типів: ' + ' '.join(words))
    return CType(base, 0, (), unsigned, const)


def const_eval(e):
    """Обчислення константного виразу на етапі розбору (розмір масиву, case-мітки)."""
    if isinstance(e, A.Const):
        return e.value
    if isinstance(e, A.UnaryOp) and e.op in '-+~!':
        v = const_eval(e.operand)
        return {'-': -v, '+': v, '~': ~v, '!': int(not v)}[e.op]
    if isinstance(e, A.BinOp):
        a, b = const_eval(e.left), const_eval(e.right)
        ops = {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b,
               '/': lambda: int(a / b) if isinstance(a, int) and isinstance(b, int) else a / b,
               '%': lambda: a % b, '<<': lambda: a << b, '>>': lambda: a >> b,
               '&': lambda: a & b, '|': lambda: a | b, '^': lambda: a ^ b}
        if e.op in ops:
            return ops[e.op]()
    if isinstance(e, A.SizeOf) and e.of_type is not None:
        return e.of_type.size()
    raise ValueError('not constant')


# ======================================================================
#  Зовнішні оголошення
# ======================================================================
def p_translation_unit(p):
    '''translation_unit : external_declaration
                        | translation_unit external_declaration'''
    if len(p) == 2:
        p[0] = A.Program(list(p[1]), line=1)
    else:
        p[1].decls.extend(p[2])
        p[0] = p[1]


def p_external_declaration(p):
    '''external_declaration : function_definition
                            | declaration'''
    p[0] = p[1].decls if isinstance(p[1], A.DeclList) else [p[1]]


def p_external_declaration_error(p):
    '''external_declaration : error ';' '''
    p[0] = []


def p_function_definition(p):
    '''function_definition : declaration_specifiers declarator compound_statement'''
    spec, d = make_specifiers(p[1], p.lineno(1)), p[2]
    if d.params is None:
        _err(d.line, "очікувалось оголошення функції перед '{'")
        d.params = []
    ret = CType(spec.base, spec.ptr + d.ptr, (), spec.unsigned)
    p[0] = A.FuncDef(ret, d.name, d.params, p[3], line=d.line)


# ======================================================================
#  Оголошення
# ======================================================================
def p_declaration(p):
    '''declaration : declaration_specifiers ';'
                   | declaration_specifiers init_declarator_list ';' '''
    spec = make_specifiers(p[1], p.lineno(1))
    decls = []
    if len(p) == 4:
        for d, init in p[2]:
            if d.params is not None:
                ret = CType(spec.base, spec.ptr + d.ptr, (), spec.unsigned)
                decls.append(A.FuncDecl(ret, d.name, d.params, line=d.line))
            else:
                decls.append(A.VarDecl(d.make_type(spec), d.name, init, line=d.line))
    p[0] = A.DeclList(decls, line=p.lineno(len(p) - 1))


def p_declaration_specifiers(p):
    '''declaration_specifiers : storage_class_specifier
                              | storage_class_specifier declaration_specifiers
                              | type_specifier
                              | type_specifier declaration_specifiers
                              | type_qualifier
                              | type_qualifier declaration_specifiers'''
    # повертаємо список слів; у CType їх перетворює make_specifiers()
    p[0] = [p[1]] + (p[2] if len(p) == 3 else [])


def p_storage_class_specifier(p):
    '''storage_class_specifier : STATIC
                               | EXTERN'''
    p[0] = p[1]


def p_type_specifier(p):
    '''type_specifier : VOID
                      | CHAR
                      | SHORT
                      | INT
                      | LONG
                      | FLOAT
                      | DOUBLE
                      | SIGNED
                      | UNSIGNED'''
    p[0] = p[1]


def p_type_qualifier(p):
    '''type_qualifier : CONST'''
    p[0] = p[1]


def p_init_declarator_list(p):
    '''init_declarator_list : init_declarator
                            | init_declarator_list ',' init_declarator'''
    p[0] = [p[1]] if len(p) == 2 else p[1] + [p[3]]


def p_init_declarator(p):
    '''init_declarator : declarator
                       | declarator '=' initializer'''
    p[0] = (p[1], p[3] if len(p) == 4 else None)


def p_declarator(p):
    '''declarator : pointer direct_declarator
                  | direct_declarator'''
    if len(p) == 3:
        p[2].ptr += p[1]
        p[0] = p[2]
    else:
        p[0] = p[1]


def p_pointer(p):
    '''pointer : '*'
               | '*' CONST
               | '*' pointer
               | '*' CONST pointer'''
    rest = p[len(p) - 1] if isinstance(p[len(p) - 1], int) else 0
    p[0] = 1 + rest


def p_direct_declarator_id(p):
    '''direct_declarator : ID'''
    p[0] = Declarator(p[1], p.lineno(1))


def p_direct_declarator_paren(p):
    '''direct_declarator : '(' declarator ')' '''
    p[2].paren_ptr = p[2].ptr > 0
    p[0] = p[2]


def p_direct_declarator_array(p):
    '''direct_declarator : direct_declarator '[' constant_expression ']'
                         | direct_declarator '[' ']' '''
    d = p[1]
    if d.paren_ptr:
        _err(d.line, 'вказівники на масиви не підтримуються')
    size = None
    if len(p) == 5:
        try:
            size = int(const_eval(p[3]))
            if size <= 0:
                _err(d.line, "розмір масиву '%s' має бути додатним" % d.name)
                size = 1
        except (ValueError, ZeroDivisionError, TypeError):
            _err(d.line, "розмір масиву '%s' має бути константою" % d.name)
            size = 1
    d.dims.append(size)
    p[0] = d


def p_direct_declarator_func(p):
    '''direct_declarator : direct_declarator '(' parameter_list ')'
                         | direct_declarator '(' ')' '''
    d = p[1]
    params = p[3] if len(p) == 5 else []
    # f(void) – порожній список параметрів
    if len(params) == 1 and params[0].ptype.is_void and not params[0].name:
        params = []
    d.params = params
    p[0] = d


def p_parameter_list(p):
    '''parameter_list : parameter_declaration
                      | parameter_list ',' parameter_declaration'''
    p[0] = [p[1]] if len(p) == 2 else p[1] + [p[3]]


def p_parameter_declaration(p):
    '''parameter_declaration : declaration_specifiers declarator
                             | declaration_specifiers abstract_declarator
                             | declaration_specifiers'''
    spec = make_specifiers(p[1], p.lineno(1))
    if len(p) == 2:
        p[0] = A.Param(CType(spec.base, 0, (), spec.unsigned), None, line=p.lineno(1))
    elif isinstance(p[2], Declarator):
        d = p[2]
        p[0] = A.Param(d.make_type(spec), d.name, line=d.line)
    else:
        ptr, dims = p[2]
        p[0] = A.Param(CType(spec.base, spec.ptr + ptr, dims, spec.unsigned), None,
                       line=p.lineno(1))


def p_abstract_declarator(p):
    '''abstract_declarator : pointer
                           | pointer direct_abstract_declarator
                           | direct_abstract_declarator'''
    if len(p) == 3:
        p[0] = (p[1], p[2])
    elif isinstance(p[1], int):
        p[0] = (p[1], [])
    else:
        p[0] = (0, p[1])


def p_direct_abstract_declarator(p):
    '''direct_abstract_declarator : '[' ']'
                                  | direct_abstract_declarator '[' ']' '''
    p[0] = [None] if len(p) == 3 else p[1] + [None]


def p_type_name(p):
    '''type_name : specifier_qualifier_list
                 | specifier_qualifier_list pointer'''
    spec = make_specifiers(p[1], p.lineno(1))
    if len(p) == 3:
        spec.ptr = p[2]
    p[0] = spec


def p_specifier_qualifier_list(p):
    '''specifier_qualifier_list : type_specifier
                                | type_specifier specifier_qualifier_list
                                | type_qualifier
                                | type_qualifier specifier_qualifier_list'''
    p[0] = [p[1]] + (p[2] if len(p) == 3 else [])


def p_initializer(p):
    '''initializer : assignment_expression
                   | '{' initializer_list '}'
                   | '{' initializer_list ',' '}' '''
    if len(p) == 2:
        p[0] = p[1]
    else:
        p[0] = A.InitList(p[2], line=p.lineno(1))


def p_initializer_list(p):
    '''initializer_list : initializer
                        | initializer_list ',' initializer'''
    p[0] = [p[1]] if len(p) == 2 else p[1] + [p[3]]


# ======================================================================
#  Оператори (statements)
# ======================================================================
def p_statement(p):
    '''statement : labeled_statement
                 | compound_statement
                 | expression_statement
                 | selection_statement
                 | iteration_statement
                 | jump_statement'''
    p[0] = p[1]


def p_statement_error(p):
    '''statement : error ';' '''
    p[0] = A.EmptyStmt(line=p.lineno(2))


def p_labeled_statement(p):
    '''labeled_statement : CASE constant_expression ':' statement
                         | DEFAULT ':' statement'''
    if len(p) == 5:
        p[0] = A.Case(p[2], p[4], line=p.lineno(1))
    else:
        p[0] = A.Default(p[3], line=p.lineno(1))


def p_compound_statement(p):
    '''compound_statement : '{' '}'
                          | '{' block_item_list '}' '''
    p[0] = A.Compound(p[2] if len(p) == 4 else [], line=p.lineno(1))


def p_block_item_list(p):
    '''block_item_list : block_item
                       | block_item_list block_item'''
    p[0] = [p[1]] if len(p) == 2 else p[1] + [p[2]]


def p_block_item(p):
    '''block_item : declaration
                  | statement'''
    p[0] = p[1]


def p_expression_statement(p):
    '''expression_statement : ';'
                            | expression ';' '''
    if len(p) == 2:
        p[0] = A.EmptyStmt(line=p.lineno(1))
    else:
        p[0] = A.ExprStmt(p[1], line=p[1].line)


def p_selection_if(p):
    '''selection_statement : IF '(' expression ')' statement %prec IFX
                           | IF '(' expression ')' statement ELSE statement'''
    p[0] = A.If(p[3], p[5], p[7] if len(p) == 8 else None, line=p.lineno(1))


def p_selection_switch(p):
    '''selection_statement : SWITCH '(' expression ')' statement'''
    p[0] = A.Switch(p[3], p[5], line=p.lineno(1))


def p_iteration_while(p):
    '''iteration_statement : WHILE '(' expression ')' statement'''
    p[0] = A.While(p[3], p[5], line=p.lineno(1))


def p_iteration_do(p):
    '''iteration_statement : DO statement WHILE '(' expression ')' ';' '''
    p[0] = A.DoWhile(p[2], p[5], line=p.lineno(1))


def p_iteration_for(p):
    '''iteration_statement : FOR '(' expression_statement expression_statement ')' statement
                           | FOR '(' expression_statement expression_statement expression ')' statement
                           | FOR '(' declaration expression_statement ')' statement
                           | FOR '(' declaration expression_statement expression ')' statement'''
    init = p[3]
    if isinstance(init, A.ExprStmt):
        init = init.expr
    elif isinstance(init, A.EmptyStmt):
        init = None
    cond = p[4].expr if isinstance(p[4], A.ExprStmt) else None
    step = p[5] if len(p) == 8 else None
    p[0] = A.For(init, cond, step, p[len(p) - 1], line=p.lineno(1))


def p_jump(p):
    '''jump_statement : CONTINUE ';'
                      | BREAK ';'
                      | RETURN ';'
                      | RETURN expression ';' '''
    kw = p[1]
    if kw == 'continue':
        p[0] = A.Continue(line=p.lineno(1))
    elif kw == 'break':
        p[0] = A.Break(line=p.lineno(1))
    else:
        p[0] = A.Return(p[2] if len(p) == 4 else None, line=p.lineno(1))


# ======================================================================
#  Вирази (ієрархія за пріоритетом, від найнижчого до найвищого)
# ======================================================================
def p_expression(p):
    '''expression : assignment_expression
                  | expression ',' assignment_expression'''
    if len(p) == 2:
        p[0] = p[1]
    elif isinstance(p[1], A.Comma):
        p[1].exprs.append(p[3])
        p[0] = p[1]
    else:
        p[0] = A.Comma([p[1], p[3]], line=p[1].line)


def p_assignment_expression(p):
    '''assignment_expression : conditional_expression
                             | unary_expression assignment_operator assignment_expression'''
    # Права рекурсія => правоасоціативність: a = b = c  ==  a = (b = c)
    if len(p) == 2:
        p[0] = p[1]
    else:
        p[0] = A.Assign(p[2], p[1], p[3], line=p[1].line)


def p_assignment_operator(p):
    '''assignment_operator : '='
                           | MUL_ASSIGN
                           | DIV_ASSIGN
                           | MOD_ASSIGN
                           | ADD_ASSIGN
                           | SUB_ASSIGN
                           | LEFT_ASSIGN
                           | RIGHT_ASSIGN
                           | AND_ASSIGN
                           | XOR_ASSIGN
                           | OR_ASSIGN'''
    p[0] = p[1]


def p_conditional_expression(p):
    '''conditional_expression : logical_or_expression
                              | logical_or_expression '?' expression ':' conditional_expression'''
    if len(p) == 2:
        p[0] = p[1]
    else:
        p[0] = A.Ternary(p[1], p[3], p[5], line=p[1].line)


def p_constant_expression(p):
    '''constant_expression : conditional_expression'''
    p[0] = p[1]


def p_binary_expression(p):
    '''logical_or_expression : logical_or_expression OR_OP logical_and_expression
       logical_and_expression : logical_and_expression AND_OP inclusive_or_expression
       inclusive_or_expression : inclusive_or_expression '|' exclusive_or_expression
       exclusive_or_expression : exclusive_or_expression '^' and_expression
       and_expression : and_expression '&' equality_expression
       equality_expression : equality_expression EQ_OP relational_expression
                           | equality_expression NE_OP relational_expression
       relational_expression : relational_expression '<' shift_expression
                             | relational_expression '>' shift_expression
                             | relational_expression LE_OP shift_expression
                             | relational_expression GE_OP shift_expression
       shift_expression : shift_expression LEFT_OP additive_expression
                        | shift_expression RIGHT_OP additive_expression
       additive_expression : additive_expression '+' multiplicative_expression
                           | additive_expression '-' multiplicative_expression
       multiplicative_expression : multiplicative_expression '*' cast_expression
                                 | multiplicative_expression '/' cast_expression
                                 | multiplicative_expression '%' cast_expression'''
    # Ліва рекурсія => лівоасоціативність: a - b - c == (a - b) - c
    p[0] = A.BinOp(p[2], p[1], p[3], line=p.lineno(2))


def p_binary_passthrough(p):
    '''logical_or_expression : logical_and_expression
       logical_and_expression : inclusive_or_expression
       inclusive_or_expression : exclusive_or_expression
       exclusive_or_expression : and_expression
       and_expression : equality_expression
       equality_expression : relational_expression
       relational_expression : shift_expression
       shift_expression : additive_expression
       additive_expression : multiplicative_expression
       multiplicative_expression : cast_expression
       cast_expression : unary_expression
       unary_expression : postfix_expression
       postfix_expression : primary_expression'''
    p[0] = p[1]


def p_cast_expression(p):
    '''cast_expression : '(' type_name ')' cast_expression'''
    p[0] = A.Cast(p[2], p[4], line=p.lineno(1))


def p_unary_incdec(p):
    '''unary_expression : INC_OP unary_expression
                        | DEC_OP unary_expression'''
    p[0] = A.IncDec(p[1], True, p[2], line=p.lineno(1))


def p_unary_operator_expr(p):
    '''unary_expression : unary_operator cast_expression'''
    op, line = p[1]
    if op == '&':
        p[0] = A.AddrOf(p[2], line=line)
    elif op == '*':
        p[0] = A.Deref(p[2], line=line)
    else:
        p[0] = A.UnaryOp(op, p[2], line=line)


def p_unary_operator(p):
    '''unary_operator : '&'
                      | '*'
                      | '+'
                      | '-'
                      | '~'
                      | '!' '''
    p[0] = (p[1], p.lineno(1))


def p_unary_sizeof(p):
    '''unary_expression : SIZEOF unary_expression
                        | SIZEOF '(' type_name ')' '''
    if len(p) == 3:
        p[0] = A.SizeOf(None, p[2], line=p.lineno(1))
    else:
        p[0] = A.SizeOf(p[3], None, line=p.lineno(1))


def p_postfix_index(p):
    '''postfix_expression : postfix_expression '[' expression ']' '''
    p[0] = A.Index(p[1], p[3], line=p.lineno(2))


def p_postfix_call(p):
    '''postfix_expression : postfix_expression '(' ')'
                          | postfix_expression '(' argument_expression_list ')' '''
    if not isinstance(p[1], A.Id):
        _err(p.lineno(2), 'викликати можна лише функцію за іменем')
        name = '?'
    else:
        name = p[1].name
    p[0] = A.Call(name, p[3] if len(p) == 5 else [], line=p.lineno(2))


def p_postfix_incdec(p):
    '''postfix_expression : postfix_expression INC_OP
                          | postfix_expression DEC_OP'''
    p[0] = A.IncDec(p[2], False, p[1], line=p.lineno(2))


def p_argument_expression_list(p):
    '''argument_expression_list : assignment_expression
                                | argument_expression_list ',' assignment_expression'''
    p[0] = [p[1]] if len(p) == 2 else p[1] + [p[3]]


def p_primary_id(p):
    '''primary_expression : ID'''
    p[0] = A.Id(p[1], line=p.lineno(1))


def p_primary_int(p):
    '''primary_expression : INT_CONST'''
    p[0] = A.Const(p[1], 'int', line=p.lineno(1))


def p_primary_float(p):
    '''primary_expression : FLOAT_CONST'''
    p[0] = A.Const(p[1], 'float', line=p.lineno(1))


def p_primary_char(p):
    '''primary_expression : CHAR_CONST'''
    p[0] = A.Const(p[1], 'char', line=p.lineno(1))


def p_primary_string(p):
    '''primary_expression : string_literal'''
    p[0] = p[1]


def p_string_literal(p):
    '''string_literal : STRING_LITERAL
                      | string_literal STRING_LITERAL'''
    # сусідні рядкові літерали склеюються: "ab" "cd" -> "abcd"
    if len(p) == 2:
        p[0] = A.StringLit(p[1], line=p.lineno(1))
    else:
        p[1].value += p[2]
        p[0] = p[1]


def p_primary_paren(p):
    '''primary_expression : '(' expression ')' '''
    p[0] = p[2]


def p_error(p):
    if p is None:
        _err(0, 'Неочікуваний кінець файлу (можливо, бракує "}" або ";")')
        return
    value = p.value if p.type != 'STRING_LITERAL' else '"%s"' % p.value
    _err(p.lineno, "Синтаксична помилка біля '%s' (токен %s)" % (value, p.type))


# ======================================================================
#  Побудова LALR(1)-таблиць
# ======================================================================
os.makedirs(GEN_DIR, exist_ok=True)
_build_log = io.StringIO()
parser = yacc.yacc(start=start, debug=True, debugfile='parser.out', outputdir=GEN_DIR,
                   write_tables=False, errorlog=yacc.PlyLogger(_build_log))
BUILD_LOG = _build_log.getvalue()


def grammar_info():
    """Статистика граматики та автомата (для вкладки Grammar і для захисту)."""
    log = BUILD_LOG
    import re
    sr = re.search(r'(\d+) shift/reduce conflict', log)
    rr = re.search(r'(\d+) reduce/reduce conflict', log)
    prods = [pr.str for pr in parser.productions[1:]]
    nonterms = sorted({pr.name for pr in parser.productions[1:]})
    return {
        'productions': prods,
        'n_productions': len(prods),
        'terminals': sorted(set(tokens) | set(literals_list())),
        'nonterminals': nonterms,
        'n_states': len(parser.action),
        'sr_conflicts': int(sr.group(1)) if sr else 0,
        'rr_conflicts': int(rr.group(1)) if rr else 0,
        'precedence': [list(x) for x in precedence],
        'build_log': log,
        'method': 'LALR(1)',
    }


def literals_list():
    from .lexer import literals
    return ["'%s'" % c for c in literals]


_LEXTOK = __import__('re').compile(r"LexToken\(([^,]+),(.*),\d+,\d+\)$")


class TraceLogger:
    """Перехоплює налагоджувальний вивід PLY (аналог yydebug) – протокол роботи LR-автомата."""

    def __init__(self, limit=3000):
        self.steps, self.limit, self._cur = [], limit, {}
        self.truncated = False

    def _log(self, msg, *args):
        if len(self.steps) >= self.limit:
            self.truncated = True
            return
        text = (msg % args) if args else msg
        if text.startswith('State  :'):
            self._cur = {'state': text[8:].strip()}
        elif text.startswith('Stack  :'):
            stack, _, la = text[8:].strip().rpartition('. ')
            if not _ and stack == '':
                stack, la = '', text[8:].strip().lstrip('. ')
            m = _LEXTOK.match(la)
            if m:
                la = m.group(1) if m.group(1) in ('ID', 'INT_CONST', 'FLOAT_CONST', 'CHAR_CONST',
                                                  'STRING_LITERAL') else m.group(2).strip("'")
                if m.group(1) in ('ID', 'INT_CONST', 'FLOAT_CONST'):
                    la += ' ' + m.group(2).strip("'")
            self._cur['stack'] = stack.strip()
            self._cur['lookahead'] = la
        elif text.startswith('Action :'):
            act = text[8:].strip()
            if act.startswith('Reduce rule'):
                act = act.split(' with ')[0] + ' →' + act.split('goto state')[-1]
                act = act.replace('Reduce rule ', 'reduce ')
            elif act.startswith('Shift and goto state'):
                act = 'shift → ' + act.split()[-1]
            self._cur['action'] = act
            self.steps.append(self._cur)
            self._cur = {'state': self._cur.get('state', '')}
        elif text.startswith('Done'):
            self.steps.append({'state': self._cur.get('state', ''), 'stack': '', 'action': 'accept'})
        elif text.startswith('Error'):
            self.steps.append({'state': '', 'stack': '', 'action': text})

    debug = info = warning = error = critical = _log


def parse(text, trace=False):
    """Повертає (AST | None, список помилок, протокол розбору)."""
    global _errors
    _errors = []
    A.reset_seq()
    lex_errors = []
    lx = CLexer(lex_errors)
    lx.lexer.lineno = 1
    logger = TraceLogger() if trace else None
    try:
        ast = parser.parse(text, lexer=lx.lexer, tracking=True, debug=logger or False)
    except Exception as ex:          # захист від аварій у семантичних діях
        _errors.append({'phase': 'parser', 'line': 0, 'col': 0, 'msg': 'Внутрішня помилка: %s' % ex})
        ast = None
    errors = lex_errors + _errors
    return ast, errors, (logger.steps if logger else [])
