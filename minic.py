#!/usr/bin/env python3
"""MiniC – компілятор підмножини мови C на базі PLY (Python Lex-Yacc).

Приклади:
    python minic.py examples/02_factorial.c                 # розбір + семантика + виконання
    python minic.py examples/02_factorial.c --ast --tokens  # дерево та токени
    python minic.py examples/02_factorial.c --py out.py     # трансляція у Python
    python minic.py examples/02_factorial.c --js out.js     # трансляція у JavaScript
    python minic.py examples/02_factorial.c --tac -         # триадресний код у консоль
    python minic.py examples/02_factorial.c --trace         # протокол роботи LALR-автомата
    python minic.py --grammar                               # статистика граматики та LALR-таблиць
    python minic.py --serve                                 # веб-інтерфейс з візуалізацією AST (d3.js)
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def write_out(dest, text):
    if dest == '-':
        print(text)
    else:
        with open(dest, 'w', encoding='utf-8') as f:
            f.write(text)
        print('  записано: %s' % dest)


def print_diag(items, title):
    for e in items:
        where = 'рядок %d' % e['line'] if e.get('line') else '      '
        print('  %s [%s] %s: %s' % (title, e['phase'], where, e['msg']))


def main():
    ap = argparse.ArgumentParser(description='MiniC: Lex/Yacc (PLY) компілятор підмножини C')
    ap.add_argument('file', nargs='?', help='вихідний файл .c')
    ap.add_argument('--tokens', action='store_true', help='вивести потік токенів')
    ap.add_argument('--ast', action='store_true', help='вивести AST у вигляді дерева')
    ap.add_argument('--symbols', action='store_true', help='вивести таблицю символів')
    ap.add_argument('--trace', action='store_true', help='протокол shift/reduce LALR-автомата')
    ap.add_argument('--py', metavar='OUT', help='згенерувати Python (OUT або - для консолі)')
    ap.add_argument('--js', metavar='OUT', help='згенерувати JavaScript (OUT або -)')
    ap.add_argument('--tac', metavar='OUT', help='згенерувати триадресний код (OUT або -)')
    ap.add_argument('--json', metavar='OUT', help='зберегти AST у JSON (для d3.js)')
    ap.add_argument('--no-run', action='store_true', help='не виконувати програму')
    ap.add_argument('--grammar', action='store_true', help='статистика граматики/автомата')
    ap.add_argument('--serve', action='store_true', help='запустити веб-інтерфейс')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--no-browser', action='store_true', help='не відкривати браузер автоматично')
    args = ap.parse_args()

    if args.serve:
        from minic.server import serve
        serve(args.port, open_browser=not args.no_browser)
        return

    if args.grammar:
        from minic.parser import grammar_info, GEN_DIR
        g = grammar_info()
        print('Метод розбору      : %s (PLY.yacc, алгоритм DeRemer-Pennello)' % g['method'])
        print('Терміналів         : %d' % len(g['terminals']))
        print('Нетерміналів       : %d' % len(g['nonterminals']))
        print('Продукцій          : %d' % g['n_productions'])
        print('Станів автомата    : %d' % g['n_states'])
        print('Конфліктів S/R     : %d' % g['sr_conflicts'])
        print('Конфліктів R/R     : %d' % g['rr_conflicts'])
        print('Таблиця пріоритетів: %s' % g['precedence'])
        print('Повний опис станів : %s' % os.path.join(GEN_DIR, 'parser.out'))
        print()
        for i, p in enumerate(g['productions'], 1):
            print('  %3d  %s' % (i, p))
        return

    if not args.file:
        ap.print_help()
        return

    from minic.compiler import compile_source
    src = open(args.file, encoding='utf-8').read()
    res = compile_source(src, run=not args.no_run, trace=args.trace)

    if args.tokens:
        print('=== Токени (%d) ===' % len(res['tokens']))
        for t in res['tokens']:
            print('  %4d:%-3d %-16s %s' % (t['line'], t['col'], t['type'], t['value']))
    if args.trace:
        print('=== Протокол LALR(1)-розбору (%d кроків) ===' % len(res['trace']))
        for i, s in enumerate(res['trace'], 1):
            print('  %4d  state %-4s %-40.40s | %-14.14s | %s' % (
                i, s.get('state', ''), s.get('stack', ''), s.get('lookahead', ''), s.get('action', '')))
    if args.ast and res.get('ast_text'):
        print('=== AST ===')
        print(res['ast_text'])
    if args.symbols and res['symbols']:
        print('=== Таблиця символів ===')
        for s in res['symbols']:
            print('  %-10s %-8s %-12s %-14s рядок %d' % (s['scope'], s['kind'], s['type'], s['name'], s['line']))
    if args.json and res.get('ast'):
        write_out(args.json, json.dumps(res['ast'], ensure_ascii=False, indent=1))

    if res['warnings']:
        print_diag(res['warnings'], 'попередження')
    if res['errors']:
        print('Знайдено помилок: %d' % len(res['errors']))
        print_diag(res['errors'], 'ПОМИЛКА')
        sys.exit(1)

    for key, dest in (('python', args.py), ('js', args.js), ('tac', args.tac)):
        if dest:
            if key in res['codegen_errors']:
                ce = res['codegen_errors'][key]
                print('  %s: трансляція неможлива (рядок %s): %s' % (key, ce['line'], ce['msg']))
            else:
                write_out(dest, res['code'][key])

    if not args.no_run:
        print('=== Виконання (інтерпретатор AST) ===')
        sys.stdout.write(res['output'] or '')
        if res.get('runtime_error'):
            e = res['runtime_error']
            print('\nПОМИЛКА ВИКОНАННЯ (рядок %s): %s' % (e['line'], e['msg']))
        print('=== Код завершення: %s; кроків: %s ===' % (res['exit_code'], res['stats'].get('steps')))


if __name__ == '__main__':
    main()
