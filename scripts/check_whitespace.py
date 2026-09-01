#!/usr/bin/env python3
# Check Klipper-style whitespace and formatting rules.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import ast
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
# Tool output that .gitignore already excludes. It is not part of the
# repository, and a binary artifact such as .coverage would otherwise fail the
# UTF-8 check and block an unrelated task.
EXCLUDED_DIRS = {
    '.compat_repos',
    '.git',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.venv',
    '__pycache__',
    'env',
    'htmlcov',
    'venv',
}
EXCLUDED_NAMES = {
    '.coverage',
}
SKIP_SUFFIXES = {
    '.gif',
    '.ico',
    '.jpg',
    '.jpeg',
    '.pdf',
    '.png',
}
# Blank lines before a definition: two at module level, one inside a class or
# function. This is the layout klipper_compat.py already uses everywhere.
BLANK_LINES_MODULE = 2
BLANK_LINES_NESTED = 1
DEFINITION_NODES = (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)
# A "cmd_X_help" attribute documents the command right below it. Klipper keeps
# that pair on adjacent lines, so the blank line is required before the pair
# and not between its two halves.
HELP_SUFFIX = '_help'
# Unicode line separators above the ASCII control range. The ord() < 32 test
# cannot see them, and splitlines() would hide them as line breaks.
UNICODE_LINE_BREAKS = '\x85\u2028\u2029'


def iter_files():
    """Yield repository files that should be whitespace checked."""
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        relpath = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in relpath.parts):
            continue
        if path.name in EXCLUDED_NAMES:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield path


def is_makefile(path):
    """Return whether tabs are allowed in this file."""
    return path.name == 'Makefile' or path.suffix == '.mk'


def report(errors, path, lineno, msg):
    """Append a formatted whitespace error."""
    relpath = path.relative_to(ROOT)
    if lineno is None:
        errors.append("%s: %s" % (relpath, msg))
    else:
        errors.append("%s:%d: %s" % (relpath, lineno, msg))


def iter_definitions(tree):
    """Yield definitions as (node, siblings, index, at_module_level).

    Only class and function bodies are descended into, which is where the
    definitions this rule is about live.
    """
    pending = [(tree, True)]
    while pending:
        node, at_module_level = pending.pop()
        for index, statement in enumerate(node.body):
            if not isinstance(statement, DEFINITION_NODES):
                continue
            yield statement, node.body, index, at_module_level
            pending.append((statement, False))


def definition_start(node):
    """Return the first line of a definition, decorators included."""
    if node.decorator_list:
        return node.decorator_list[0].lineno
    return node.lineno


def paired_help_assignment(siblings, index, start):
    """Return a "cmd_X_help" assignment that belongs to the definition."""
    if index == 0:
        return None
    previous = siblings[index - 1]
    if not isinstance(previous, ast.Assign):
        return None
    if previous.end_lineno != start - 1:
        return None
    names = [target.id for target in previous.targets
             if isinstance(target, ast.Name)]
    if len(names) != 1 or not names[0].endswith(HELP_SUFFIX):
        return None
    return previous


def leading_blank_lines(lines, start):
    """Count blank lines above a block, skipping the comments attached to it."""
    index = start - 2
    while index >= 0 and lines[index].strip().startswith('#'):
        index -= 1
    count = 0
    while index >= 0 and not lines[index].strip():
        count += 1
        index -= 1
    return count


def check_blank_lines(path, text, errors):
    """Check that every definition is preceded by blank lines.

    The source is parsed instead of scanned line by line: the tests embed
    Klipper sources as string literals, and a text search would report the
    "def" lines inside them.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as err:
        report(errors, path, err.lineno, "cannot parse: %s" % (err.msg,))
        return
    lines = text.splitlines()
    for node, siblings, index, at_module_level in iter_definitions(tree):
        if index == 0:
            # The first statement of a block opens it and needs no separator.
            continue
        start = definition_start(node)
        paired = paired_help_assignment(siblings, index, start)
        if paired is not None:
            start = paired.lineno
        expected = BLANK_LINES_MODULE if at_module_level else BLANK_LINES_NESTED
        found = leading_blank_lines(lines, start)
        if found < expected:
            report(errors, path, node.lineno,
                   "expected %d blank line(s) before %s, found %d"
                   % (expected, node.name, found))


def check_file(path, errors):
    """Check one file for encoding and whitespace violations."""
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
    # Split on '\n' only. splitlines() also breaks on '\r', form feeds and
    # the Unicode separators, so a CRLF file or a stray control character
    # never reached the checks below and passed silently.
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    for lineno, line in enumerate(lines, start=1):
        if line.endswith('\r'):
            report(errors, path, lineno, "carriage return line ending")
            # Keep the remaining checks on the payload of the line.
            line = line[:-1]
        if line.endswith(' ') or line.endswith('\t'):
            report(errors, path, lineno, "trailing whitespace")
        if '\t' in line and not is_makefile(path):
            report(errors, path, lineno, "tab character")
        if path.suffix == '.py' and len(line) > 80:
            report(errors, path, lineno, "line longer than 80 characters")
        for column, char in enumerate(line, start=1):
            if char in UNICODE_LINE_BREAKS or (ord(char) < 32
                                               and char != '\t'):
                msg = "invalid control character at column %d" % (column,)
                report(errors, path, lineno, msg)
    if path.suffix == '.py':
        check_blank_lines(path, text, errors)


def main():
    """CLI entrypoint for whitespace validation."""
    errors = []
    for path in iter_files():
        check_file(path, errors)
    if errors:
        sys.stderr.write('\n'.join(errors) + '\n')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
