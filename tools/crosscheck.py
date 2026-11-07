"""Крос-перевірка: для кожного прикладу порівнює вивід інтерпретатора AST,
згенерованого Python-коду та згенерованого JavaScript-коду (через node або deno).

    python tools/crosscheck.py            # усі приклади
    python tools/crosscheck.py -v 07      # детально для прикладів, що містять '07'
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from minic.compiler import compile_source  # noqa: E402


def js_runner():
    if shutil.which('node'):
        return ['node']
    if shutil.which('deno'):
        return ['deno', 'run', '--quiet']
    return None


def run_python(code):
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        r = subprocess.run([sys.executable, '-I', f.name], capture_output=True, timeout=30,
                           encoding='utf-8', env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        return r.stdout, r.returncode, r.stderr
    finally:
        os.unlink(f.name)


def run_js(code, runner):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        r = subprocess.run(runner + [f.name], capture_output=True, timeout=30, encoding='utf-8')
        return r.stdout, r.returncode, r.stderr
    finally:
        os.unlink(f.name)


def main():
    verbose = '-v' in sys.argv
    filt = [a for a in sys.argv[1:] if not a.startswith('-')]
    runner = js_runner()
    ok_all = True
    for path in sorted(glob.glob(os.path.join(ROOT, 'examples', '*.c'))):
        name = os.path.basename(path)
        if filt and not any(x in name for x in filt):
            continue
        src = open(path, encoding='utf-8').read()
        res = compile_source(src)
        if res['errors']:
            print('%-24s compile errors: %d (expected for *_errors.c)' % (name, len(res['errors'])))
            if verbose:
                for e in res['errors']:
                    print('    [%s] line %s: %s' % (e['phase'], e['line'], e['msg']))
            continue
        status = []
        out = res['output']
        if res.get('runtime_error'):
            status.append('RUNTIME ERROR ' + res['runtime_error']['msg'])
        for target in ('python', 'js'):
            if target in res['codegen_errors']:
                status.append('%s: n/a (%s)' % (target, res['codegen_errors'][target]['msg'][:50]))
                continue
            if target == 'python':
                o, rc, err = run_python(res['code']['python'])
            elif runner:
                o, rc, err = run_js(res['code']['js'], runner)
            else:
                status.append('js: no runtime')
                continue
            if o == out:
                status.append('%s: OK' % target)
            else:
                ok_all = False
                status.append('%s: MISMATCH' % target)
                if verbose or True:
                    print('---- %s %s output differs ----\n%s\n---- interpreter ----\n%s\n%s'
                          % (name, target, o, out, err))
        print('%-24s %s' % (name, ' | '.join(status)))
        if verbose:
            print(out)
    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
