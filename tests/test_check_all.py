# Unit tests for the aggregate validation runner.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_script(name):
    """Load a script module from the repository scripts directory."""
    path = ROOT / 'scripts' / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_all = load_script('check_all.py')


class CheckAllTest(unittest.TestCase):
    """Covers the aggregate validation command runner."""

    def test_command_text_includes_env_prefix(self):
        text = check_all.command_text(
            ('python3', '-m', 'unittest'),
            {'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(
            text,
            'env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest')

    def test_run_all_stops_at_first_failure(self):
        calls = []
        old_run_command = check_all.run_command

        def fake_run_command(command, env_updates=None):
            calls.append((command, env_updates))
            if command == ('second',):
                return 7
            return 0

        try:
            check_all.run_command = fake_run_command
            ret = check_all.run_all((
                (('first',), None),
                (('second',), {'A': 'B'}),
                (('third',), None),
            ))
        finally:
            check_all.run_command = old_run_command
        self.assertEqual(ret, 7)
        self.assertEqual(calls, [
            (('first',), None),
            (('second',), {'A': 'B'}),
        ])

    def test_compileall_targets_project_python_paths(self):
        compile_commands = [
            command for command, _env in check_all.COMMANDS
            if '-m' in command and 'compileall' in command
        ]
        self.assertEqual(len(compile_commands), 1)
        self.assertNotIn('.', compile_commands[0])
        for path in ['z_calibration.py', 'klipper_compat.py',
                     'scripts', 'tests']:
            self.assertIn(path, compile_commands[0])

    def test_compileall_redirects_pycache_outside_repo(self):
        compile_envs = [
            env for command, env in check_all.COMMANDS
            if '-m' in command and 'compileall' in command
        ]
        self.assertEqual(len(compile_envs), 1)
        self.assertEqual(
            compile_envs[0]['PYTHONPYCACHEPREFIX'],
            '/tmp/klipper_z_calibration-pycache')


if __name__ == '__main__':
    unittest.main()
