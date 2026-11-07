"""Мінімальний препроцесор C.

* #include <...> / "..."  – запам'ятовується і ігнорується (printf, sqrt ... – вбудовані функції);
* #define NAME value      – об'єктні макроси (текстова заміна цілих слів поза рядками/коментарями);
* інші директиви         – ігноруються з попередженням.
Рядки директив замінюються порожніми, тож номери рядків у повідомленнях про помилки зберігаються.
"""
import re

_DEFINE = re.compile(r'^\s*#\s*define\s+([A-Za-z_]\w*)(?:\s+(.*))?$')
_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')
_TOKEN = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|//[^\n]*|/\*[\s\S]*?\*/|[A-Za-z_]\w*')


def preprocess(source):
    macros, includes, warnings = {}, [], []
    out_lines = []
    for lineno, line in enumerate(source.split('\n'), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            m = _DEFINE.match(line)
            if m:
                if '(' in m.group(1):
                    warnings.append((lineno, 'функціональні макроси не підтримуються'))
                macros[m.group(1)] = (m.group(2) or '').split('//')[0].strip()
            elif _INCLUDE.match(line):
                includes.append(_INCLUDE.match(line).group(1))
            else:
                warnings.append((lineno, 'директиву препроцесора проігноровано: ' + stripped))
            out_lines.append('')
        else:
            out_lines.append(line)
    text = '\n'.join(out_lines)
    if macros:
        def repl(m):
            tok = m.group(0)
            return macros.get(tok, tok) if (tok[0].isalpha() or tok[0] == '_') else tok
        for _ in range(8):           # макроси можуть посилатися на інші макроси
            new = _TOKEN.sub(repl, text)
            if new == text:
                break
            text = new
    return text, {'macros': macros, 'includes': includes, 'warnings': warnings}
