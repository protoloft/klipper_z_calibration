#!/usr/bin/env python3
# Run the local validation suite used by contributors and CI.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
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
COMMANDS = (
    ((PYTHON, 'scripts/check_whitespace.py'), None),
    (('bash', '-n', 'install.sh'), None),
    ((PYTHON, '-m', 'compileall') + PYTHON_TARGETS, PYCACHE_ENV),
    ((PYTHON, '-m', 'unittest', 'discover', '-s', 'tests', '-v'), TEST_ENV),
    (('git', 'diff', '--check'), None),
)


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
    for command, env_updates in commands:
        ret = run_command(command, env_updates)
        if ret:
            return ret
    return 0


def main():
    """CLI entrypoint for the aggregate validation runner."""
    return run_all()


if __name__ == '__main__':
    sys.exit(main())
