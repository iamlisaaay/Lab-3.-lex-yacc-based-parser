"""Конвеєр компіляції MiniC:

    вихідний код C
      └─► препроцесор (#define/#include)
           └─► лексер (PLY.lex)          → потік токенів
                └─► парсер (PLY.yacc, LALR(1)) → AST
                     └─► семантичний аналіз  → анотоване AST + таблиця символів
                          ├─► інтерпретатор AST   → результат виконання
                          ├─► генератор Python    → .py
                          ├─► генератор JavaScript→ .js
                          └─► генератор TAC       → триадресний код
"""
import threading
import time

from .preprocess import preprocess
from .lexer import CLexer
from . import parser as P
from .semantic import analyze
from . import interpreter
from .codegen_common import CodegenError
from . import codegen_python, codegen_js, codegen_tac

_lock = threading.Lock()   # PLY-парсер має глобальний стан – серіалізуємо доступ

GENERATORS = {
    'python': codegen_python.generate,
    'js': codegen_js.generate,
    'tac': codegen_tac.generate,
}


def compile_source(code, run=True, trace=False, targets=('python', 'js', 'tac'), max_steps=None):
    t0 = time.perf_counter()
    res = {'ok': False, 'errors': [], 'warnings': [], 'tokens': [], 'ast': None, 'trace': [],
           'symbols': [], 'output': None, 'exit_code': None, 'code': {}, 'codegen_errors': {},
           'timings': {}, 'stats': {}}
    text, pp = preprocess(code)
    res['preprocess'] = {'macros': pp['macros'], 'includes': pp['includes']}
    res['warnings'] += [{'phase': 'preprocessor', 'line': ln, 'col': 0, 'msg': m}
                        for ln, m in pp['warnings']]

    with _lock:
        t = time.perf_counter()
        res['tokens'] = CLexer([]).tokenize(text)
        res['timings']['lexer_ms'] = round((time.perf_counter() - t) * 1000, 2)

        t = time.perf_counter()
        ast, errors, steps = P.parse(text, trace=trace)
        res['timings']['parser_ms'] = round((time.perf_counter() - t) * 1000, 2)
    res['errors'] += errors
    res['trace'] = steps

    if ast is None:
        if not res['errors']:
            res['errors'].append({'phase': 'parser', 'line': 0, 'col': 0, 'msg': 'порожня програма'})
        return _finish(res, t0)

    t = time.perf_counter()
    if not errors:
        sem_errors, sem_warnings, symbols = analyze(ast)
        res['errors'] += sem_errors
        res['warnings'] += sem_warnings
        res['symbols'] = symbols
    res['timings']['semantic_ms'] = round((time.perf_counter() - t) * 1000, 2)
    res['ast'] = ast.to_dict()
    res['ast_text'] = ast.pretty()
    res['stats']['ast_nodes'] = _count(res['ast'])
    res['stats']['tokens'] = len(res['tokens'])

    if res['errors']:
        return _finish(res, t0)

    for name in targets:
        t = time.perf_counter()
        try:
            res['code'][name] = GENERATORS[name](ast)
        except CodegenError as ex:
            res['codegen_errors'][name] = {'line': ex.line, 'msg': str(ex)}
        res['timings'][name + '_ms'] = round((time.perf_counter() - t) * 1000, 2)

    if run:
        t = time.perf_counter()
        out, code, err, info = interpreter.run(ast, max_steps)
        res['timings']['run_ms'] = round((time.perf_counter() - t) * 1000, 2)
        res['output'], res['exit_code'] = out, code
        res['stats'].update(info)
        if err:
            res['runtime_error'] = err
    res['ok'] = True
    res['_ast_obj'] = ast
    return _finish(res, t0)


def _count(d):
    return 1 + sum(_count(c) for c in d.get('children', []))


def _finish(res, t0):
    res['errors'].sort(key=lambda e: e['line'])
    res['timings']['total_ms'] = round((time.perf_counter() - t0) * 1000, 2)
    return res
