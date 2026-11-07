"""Автоматичні тести MiniC:  python -m unittest discover -s tests -v"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from minic.compiler import compile_source          # noqa: E402
from minic.lexer import CLexer                     # noqa: E402
from minic import parser as P                      # noqa: E402
from minic import astnodes as A                    # noqa: E402

EXAMPLES = sorted(glob.glob(os.path.join(ROOT, 'examples', '*.c')))
EXPECTED = os.path.join(ROOT, 'tests', 'expected')


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def wrap(body, globals_=''):
    return '%s\nint main() {\n%s\n}\n' % (globals_, body)


def run(src):
    r = compile_source(src)
    assert not r['errors'], r['errors']
    return r


def body_expr(src_expr):
    """AST виразу з `return <expr>;`"""
    ast, errors, _ = P.parse('int main() { int a, b, c; return %s; }' % src_expr)
    assert not errors, errors
    return ast.decls[0].body.items[-1].expr


class TestLexer(unittest.TestCase):
    def toks(self, text):
        return [(t['type'], t['value']) for t in CLexer([]).tokenize(text)]

    def test_keywords_ids_operators(self):
        self.assertEqual(self.toks('int x1 = y<<=2;'),
                         [('INT', 'int'), ('ID', 'x1'), ('=', '='), ('ID', 'y'),
                          ('LEFT_ASSIGN', '<<='), ('INT_CONST', '2'), (';', ';')])

    def test_longest_match(self):
        types = [t for t, _ in self.toks('a+++b && c||d >= e == f != g')]
        self.assertEqual(types, ['ID', 'INC_OP', '+', 'ID', 'AND_OP', 'ID', 'OR_OP', 'ID',
                                 'GE_OP', 'ID', 'EQ_OP', 'ID', 'NE_OP', 'ID'])

    def test_constants(self):
        t = self.toks("42 0x1F 017 3.14 .5 1e3 2.5f 'a' '\\n' \"hi\\n\"")
        self.assertEqual([x[0] for x in t], ['INT_CONST'] * 3 + ['FLOAT_CONST'] * 4 +
                         ['CHAR_CONST'] * 2 + ['STRING_LITERAL'])
        self.assertEqual(t[1][1], '31')
        self.assertEqual(t[2][1], '15')

    def test_comments_and_lines(self):
        toks = CLexer([]).tokenize('/* a\n b */ int // c\n x;')
        self.assertEqual([t['type'] for t in toks], ['INT', 'ID', ';'])
        self.assertEqual(toks[1]['line'], 3)

    def test_lexical_error(self):
        r = compile_source('int main() { int x = 5 @ 3; return 0; }')
        self.assertTrue(any(e['phase'] == 'lexer' for e in r['errors']))


class TestGrammar(unittest.TestCase):
    def test_no_conflicts(self):
        g = P.grammar_info()
        self.assertEqual(g['sr_conflicts'], 0)
        self.assertEqual(g['rr_conflicts'], 0)
        self.assertGreater(g['n_states'], 200)
        self.assertGreater(g['n_productions'], 150)

    def test_precedence(self):
        e = body_expr('2 + 3 * 4')                    # + (2, * (3, 4))
        self.assertEqual((e.op, e.right.op), ('+', '*'))
        e = body_expr('a == b < c')                    # == (a, < (b, c))
        self.assertEqual((e.op, e.right.op), ('==', '<'))
        e = body_expr('a || b && c')
        self.assertEqual((e.op, e.right.op), ('||', '&&'))
        e = body_expr('a & b == c')                    # як у C: & нижче за ==
        self.assertEqual((e.op, e.right.op), ('&', '=='))

    def test_associativity(self):
        e = body_expr('a - b - c')                     # (a - b) - c
        self.assertEqual((e.op, e.left.op), ('-', '-'))
        e = body_expr('a = b = c')                     # a = (b = c)
        self.assertIsInstance(e.value, A.Assign)
        e = body_expr('a ? b : c ? a : b')             # a ? b : (c ? a : b)
        self.assertIsInstance(e.other, A.Ternary)

    def test_unary_and_cast(self):
        e = body_expr('-a * (int)b')
        self.assertEqual(e.op, '*')
        self.assertIsInstance(e.left, A.UnaryOp)
        self.assertIsInstance(e.right, A.Cast)

    def test_dangling_else(self):
        ast, errors, _ = P.parse('int main(){ int x; if (1) if (0) x = 1; else x = 2; return 0; }')
        outer = ast.decls[0].body.items[1]
        self.assertIsNone(outer.other)               # else належить внутрішньому if
        self.assertIsNotNone(outer.then.other)

    def test_error_recovery_reports_several_errors(self):
        r = compile_source(read(os.path.join(ROOT, 'examples', '14_syntax_errors.c')))
        self.assertGreaterEqual(len([e for e in r['errors'] if e['phase'] == 'parser']), 2)

    def test_trace(self):
        _, _, steps = P.parse('int main(){return 1;}', trace=True)
        acts = [s['action'] for s in steps]
        self.assertTrue(any(a.startswith('shift') for a in acts))
        self.assertTrue(any(a.startswith('reduce') for a in acts))
        self.assertEqual(acts[-1], 'accept')


class TestSemantic(unittest.TestCase):
    def errors(self, src):
        return [e['msg'] for e in compile_source(src)['errors']]

    def test_all_semantic_errors(self):
        msgs = ' | '.join(self.errors(read(os.path.join(ROOT, 'examples', '15_semantic_errors.c'))))
        for frag in ('повторне оголошення', 'неоголошений ідентифікатор', 'очікує 1 аргумент',
                     'неоголошеної функції', 'не є lvalue', "'%' вимагає цілих", "'break' поза",
                     'не може повертати значення'):
            self.assertIn(frag, msgs)

    def test_shadowing_is_allowed(self):
        r = run(wrap('int x = 1; { int x = 2; printf("%d", x); } printf("%d", x); return 0;'))
        self.assertEqual(r['output'], '21')

    def test_missing_main(self):
        self.assertTrue(any('main' in m for m in self.errors('int f() { return 1; }')))

    def test_types_annotated(self):
        r = run(wrap('double d = 1; int i = 2; d = d + i; return 0;'))
        self.assertIn('double', str(r['ast']))


class TestInterpreter(unittest.TestCase):
    def out(self, body, globals_=''):
        return run(wrap(body, globals_))['output']

    def test_examples_expected_output(self):
        for path in EXAMPLES:
            name = os.path.basename(path)[:-2]
            exp = os.path.join(EXPECTED, name + '.txt')
            if not os.path.exists(exp):
                continue
            with self.subTest(example=name):
                r = run(read(path))
                with open(exp, encoding='utf-8', newline='') as f:
                    self.assertEqual(r['output'], f.read())

    def test_c_division_semantics(self):
        self.assertEqual(self.out('printf("%d %d %d %d", -7/2, -7%2, 7/-2, 7%-2); return 0;'), '-3 -1 -3 1')

    def test_int_overflow_and_char(self):
        self.assertEqual(self.out('int a = 2147483647; a++; char c = 200; printf("%d %d", a, c); return 0;'),
                         '-2147483648 -56')

    def test_short_circuit(self):
        self.assertEqual(self.out('int n = 0; if (0 && (n = 1)) {} if (1 || (n = 2)) {} printf("%d", n); return 0;'), '0')

    def test_pointers(self):
        src = ('void inc(int *p) { (*p)++; }\n'
               'int main() { int x = 1; int a[3] = {1,2,3}; int *q = a; inc(&x); inc(&x); '
               '*(q + 2) += 10; printf("%d %d %d", x, a[2], *q); return 0; }')
        self.assertEqual(run(src)['output'], '3 13 1')

    def test_runtime_errors(self):
        r = compile_source(wrap('int a[3]; a[5] = 1; return 0;'))
        self.assertIn('поза межами', r['runtime_error']['msg'])
        r = compile_source(wrap('int z = 0; return 5 / z;'))
        self.assertIn('ділення на нуль', r['runtime_error']['msg'])
        r = compile_source(wrap('while (1) {} return 0;'), max_steps=10000)
        self.assertIn('ліміт кроків', r['runtime_error']['msg'])

    def test_recursion(self):
        src = 'int f(int n) { return n == 0 ? 0 : 1 + f(n - 1); }\nint main() { printf("%d", f(300)); return 0; }'
        self.assertEqual(run(src)['output'], '300')

    def test_exit_code(self):
        self.assertEqual(run(wrap('return 3;'))['exit_code'], 3)


def _run_python(code):
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        return subprocess.run([sys.executable, '-I', f.name], capture_output=True, timeout=60,
                              encoding='utf-8', env=dict(os.environ, PYTHONIOENCODING='utf-8')).stdout
    finally:
        os.unlink(f.name)


def _js_runner():
    if shutil.which('node'):
        return ['node']
    if shutil.which('deno'):
        return ['deno', 'run', '--quiet']
    return None


def _run_js(code, runner):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        return subprocess.run(runner + [f.name], capture_output=True, timeout=60, encoding='utf-8').stdout
    finally:
        os.unlink(f.name)


class TestCodegen(unittest.TestCase):
    """Згенерований код має давати той самий вивід, що й інтерпретатор."""

    TRICKY = wrap('''
    int i, s = 0, k = 0;
    for (i = 0; i < 10; i++) {
        if (i % 3 == 0) continue;
        switch (i) { case 4: continue; case 5: s += 100; default: s += i; }
    }
    do { k++; if (k == 2) continue; s += k; } while (k < 5);
    int a[5] = {5, 4};
    a[2] = a[0]++ + ++a[1];
    int x = (s > 100) + (s < 0) * 2 + !s;
    printf("%d %d %d %d %d %d\\n", s, k, a[0], a[1], a[2], x);
    printf("%d %d %.3f %d\\n", -7 / 2, -7 % 3, 7.0 / 2, (int)-3.9);
    int t = 0;
    while ((t += 3) < 10) ;
    printf("%d %d\\n", t, 1 < 2 < 3);
    return 0;''')

    def test_python_and_js_match_interpreter(self):
        runner = _js_runner()
        sources = [('tricky', self.TRICKY)] + [(os.path.basename(p), read(p))
                                               for p in EXAMPLES]
        for name, src in sources:
            r = compile_source(src)
            if r['errors']:
                continue
            with self.subTest(example=name, target='python'):
                if 'python' in r['code']:
                    self.assertEqual(_run_python(r['code']['python']), r['output'])
            if runner and 'js' in r['code']:
                with self.subTest(example=name, target='js'):
                    self.assertEqual(_run_js(r['code']['js'], runner), r['output'])

    def test_tricky_expected(self):
        r = run(self.TRICKY)
        self.assertEqual(r['output'], '136 5 6 5 10 1\n-3 -1 3.500 -3\n12 1\n')

    def test_pointer_codegen_reports_limitation(self):
        r = run(read(os.path.join(ROOT, 'examples', '09_pointers.c')))
        self.assertIn('python', r['codegen_errors'])
        self.assertIn('tac', r['code'])

    def test_tac_shape(self):
        tac = run(wrap('int a[2][3]; int i = 1; a[i][2] = i && 0; return 0;'))['code']['tac']
        self.assertIn('* 12', tac)        # рядок int[3] = 12 байт
        self.assertIn('ifFalse', tac)     # short-circuit &&
        self.assertIn('a[', tac)


if __name__ == '__main__':
    unittest.main()
