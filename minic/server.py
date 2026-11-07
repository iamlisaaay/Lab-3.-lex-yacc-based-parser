"""Локальний веб-сервер для інтерфейсу MiniC (лише стандартна бібліотека Python).

GET  /                  – web/index.html
GET  /api/examples      – список прикладів
GET  /api/grammar       – продукції, статистика LALR-автомата
GET  /api/parser_out    – вміст parser.out (опис усіх станів)
POST /api/compile       – {code, trace} → токени, AST (JSON для d3), помилки, код, вивід
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from .compiler import compile_source
from .parser import grammar_info, GEN_DIR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')
EXAMPLES = os.path.join(ROOT, 'examples')


def run_generated_python(code, timeout=10):
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
    try:
        r = subprocess.run([sys.executable, '-I', f.name], capture_output=True, timeout=timeout,
                           encoding='utf-8', env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        err = r.stderr.strip().splitlines()[-1] if r.returncode not in (0,) and r.stderr.strip() else ''
        return {'output': r.stdout, 'exit_code': r.returncode, 'error': err}
    except subprocess.TimeoutExpired:
        return {'output': '', 'exit_code': None, 'error': 'timeout (%ds)' % timeout}
    finally:
        os.unlink(f.name)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        if '/api/' in (args[0] if args else ''):
            sys.stderr.write('[minic] %s\n' % (fmt % args))

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/api/examples':
            items = []
            for p in sorted(glob.glob(os.path.join(EXAMPLES, '*.c'))):
                with open(p, encoding='utf-8') as f:
                    code = f.read()
                first = code.split('\n', 1)[0].strip('/* ').strip()
                items.append({'name': os.path.basename(p), 'title': first, 'code': code})
            return self.send_json(items)
        if self.path == '/api/grammar':
            return self.send_json(grammar_info())
        if self.path == '/api/parser_out':
            with open(os.path.join(GEN_DIR, 'parser.out'), encoding='utf-8') as f:
                text = f.read()
            body = text.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        if self.path != '/api/compile':
            return self.send_json({'error': 'not found'}, 404)
        n = int(self.headers.get('Content-Length', 0))
        try:
            req = json.loads(self.rfile.read(n).decode('utf-8'))
        except ValueError:
            return self.send_json({'error': 'bad json'}, 400)
        res = compile_source(req.get('code', ''), run=True, trace=bool(req.get('trace', True)))
        res.pop('_ast_obj', None)
        if res['ok'] and 'python' in res['code'] and req.get('run_python', True):
            res['python_run'] = run_generated_python(res['code']['python'])
        self.send_json(res)


def serve(port=8765, open_browser=True):
    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d/' % port
    print('MiniC web UI: %s   (Ctrl+C – зупинити)' % url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nзупинено')
