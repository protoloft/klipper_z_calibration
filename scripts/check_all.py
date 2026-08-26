#!/usr/bin/env python3
# Run the local validation suite used by contributors and CI.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib.metadata
import importlib.util
import os
import subprocess
import sys


PYTHON = sys.executable or 'python3'
PYTHON_TARGETS = (
    'z_calibration.py',
    'klipper_compat.py',
    'scripts',
    'tests',
)
PYCACHE_ENV = {
    'PYTHONPYCACHEPREFIX': '/tmp/klipper_z_calibration-pycache',
}
TEST_ENV = {
    'PYTHONDONTWRITEBYTECODE': '1',
    'PYTHONPYCACHEPREFIX': PYCACHE_ENV['PYTHONPYCACHEPREFIX'],
}
# Ruff is the only optional tool here. The repository ships no dependencies,
# so a missing ruff must not fail a local run - but it must not pass silently
# either, because CI installs the pinned version and enforces the lint step.
RUFF_MODULE = 'ruff'
RUFF_VERSION = '0.16.4'
RUFF_COMMAND = (PYTHON, '-m', RUFF_MODULE, 'check', '.')
RUFF_SKIP_NOTICE = (
    "!! SKIPPED lint step: %s is not installed in this interpreter.\n"
    "!! Install it with: %s -m pip install %s==%s\n"
    "!! CI installs ruff and enforces this step regardless."
    % (RUFF_MODULE, PYTHON, RUFF_MODULE, RUFF_VERSION)
)
COMMANDS = (
    ((PYTHON, 'scripts/check_whitespace.py'), None),
    (('bash', '-n', 'install.sh'), None),
    (RUFF_COMMAND, None),
    ((PYTHON, '-m', 'compileall') + PYTHON_TARGETS, PYCACHE_ENV),
    ((PYTHON, '-m', 'unittest', 'discover', '-s', 'tests', '-v'), TEST_ENV),
    (('git', 'diff', '--check'), None),
)


def module_available(name):
    """Return whether this interpreter can import the named module."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def ruff_installed_version():
    """Return the ruff version this interpreter runs, or None if unknown.

    Version detection is a convenience for the notice below, so every
    failure mode ends up as an unknown version instead of a failed run.
    """
    try:
        return importlib.metadata.version(RUFF_MODULE)
    except Exception:
        pass
    try:
        output = subprocess.check_output(
            (PYTHON, '-m', RUFF_MODULE, '--version'),
            stderr=subprocess.DEVNULL)
    except Exception:
        return None
    parts = output.decode('utf-8', 'replace').split()
    if not parts:
        return None
    return parts[-1]


def ruff_version_notice(version):
    """Return the notice text for a ruff version CI does not pin."""
    return (
        "!! WARNING: %s %s is installed, but CI pins %s %s.\n"
        "!! Lint findings can differ from CI. Install the pinned version"
        " with:\n"
        "!! %s -m pip install %s==%s"
        % (RUFF_MODULE, version, RUFF_MODULE, RUFF_VERSION,
           PYTHON, RUFF_MODULE, RUFF_VERSION))


def ruff_notices():
    """Return whether to skip the lint step, plus notices to report."""
    if not module_available(RUFF_MODULE):
        return True, [RUFF_SKIP_NOTICE]
    version = ruff_installed_version()
    if version is not None and version != RUFF_VERSION:
        return False, [ruff_version_notice(version)]
    return False, []


def write_notice(text):
    """Report a notice on stderr, where a passing run cannot bury it."""
    sys.stderr.write("%s\n" % (text,))
    sys.stderr.flush()


def command_text(command, env_updates=None):
    """Render a command line with any environment overrides."""
    text = ' '.join(command)
    if not env_updates:
        return text
    env_text = ' '.join(['%s=%s' % item
                         for item in sorted(env_updates.items())])
    return 'env %s %s' % (env_text, text)


def run_command(command, env_updates=None):
    """Run one validation command and return its exit status."""
    sys.stdout.write("+ %s\n" % (command_text(command, env_updates),))
    sys.stdout.flush()
    env = os.environ.copy()
    if env_updates:
        env.update(env_updates)
    return subprocess.call(command, env=env)


def run_all(commands=COMMANDS):
    """Run validation commands until the first failure."""
    notices = []
    ret = 0
    for command, env_updates in commands:
        if command == RUFF_COMMAND:
            skip, step_notices = ruff_notices()
            for notice in step_notices:
                write_notice(notice)
                notices.append(notice)
            if skip:
                continue
        ret = run_command(command, env_updates)
        if ret:
            break
    # Repeat the notices last so that a run ending in "OK" still names the
    # step that did not run the way CI runs it.
    for notice in notices:
        write_notice(notice)
    return ret


def main():
    """CLI entrypoint for the aggregate validation runner."""
    return run_all()


if __name__ == '__main__':
    sys.exit(main())
