#!/usr/bin/env python3
# Check formatting rules used by Klipper-style Python modules.
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    '.compat_repos',
    '.git',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '__pycache__',
}
SKIP_SUFFIXES = {
    '.gif',
    '.ico',
    '.jpg',
    '.jpeg',
    '.pdf',
    '.png',
}


def iter_files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        relpath = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in relpath.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield path


def is_makefile(path):
    return path.name == 'Makefile' or path.suffix == '.mk'


def report(errors, path, lineno, msg):
    relpath = path.relative_to(ROOT)
    if lineno is None:
        errors.append("%s: %s" % (relpath, msg))
    else:
        errors.append("%s:%d: %s" % (relpath, lineno, msg))


def check_file(path, errors):
    data = path.read_bytes()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        report(errors, path, None, "not utf-8 encoded")
        return
    if data and not data.endswith(b'\n'):
        report(errors, path, None, "missing newline at end of file")
    if text.endswith('\n\n'):
        report(errors, path, None, "extra blank line at end of file")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.endswith(' ') or line.endswith('\t'):
            report(errors, path, lineno, "trailing whitespace")
        if '\t' in line and not is_makefile(path):
            report(errors, path, lineno, "tab character")
        if path.suffix == '.py' and len(line) > 80:
            report(errors, path, lineno, "line longer than 80 characters")
        for column, char in enumerate(line, start=1):
            if ord(char) < 32 and char != '\t':
                msg = "invalid control character at column %d" % (column,)
                report(errors, path, lineno, msg)


def main():
    errors = []
    for path in iter_files():
        check_file(path, errors)
    if errors:
        sys.stderr.write('\n'.join(errors) + '\n')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
