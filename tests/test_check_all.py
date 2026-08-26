# Unit tests for the aggregate validation runner.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import contextlib
import importlib.util
import io
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

    def run_all_with_ruff(self, ruff_installed, ruff_status=0,
                          ruff_version=check_all.RUFF_VERSION):
        """Run the ruff command with a faked ruff installation."""
        calls = []
        old_run_command = check_all.run_command
        old_module_available = check_all.module_available
        old_installed_version = check_all.ruff_installed_version

        def fake_run_command(command, env_updates=None):
            calls.append(command)
            if command == check_all.RUFF_COMMAND:
                return ruff_status
            return 0

        def fake_module_available(name):
            self.assertEqual(name, check_all.RUFF_MODULE)
            return ruff_installed

        output = io.StringIO()
        errors = io.StringIO()
        try:
            check_all.run_command = fake_run_command
            check_all.module_available = fake_module_available
            check_all.ruff_installed_version = lambda: ruff_version
            with contextlib.redirect_stdout(output):
                with contextlib.redirect_stderr(errors):
                    ret = check_all.run_all((
                        (check_all.RUFF_COMMAND, None),
                        (('after',), None),
                    ))
        finally:
            check_all.run_command = old_run_command
            check_all.module_available = old_module_available
            check_all.ruff_installed_version = old_installed_version
        return ret, calls, output.getvalue(), errors.getvalue()

    def test_commands_include_ruff_before_compileall(self):
        commands = [command for command, _env in check_all.COMMANDS]
        self.assertIn(check_all.RUFF_COMMAND, commands)
        compile_index = [
            index for index, command in enumerate(commands)
            if '-m' in command and 'compileall' in command
        ][0]
        whitespace_index = [
            index for index, command in enumerate(commands)
            if 'scripts/check_whitespace.py' in command
        ][0]
        ruff_index = commands.index(check_all.RUFF_COMMAND)
        self.assertLess(whitespace_index, ruff_index)
        self.assertLess(ruff_index, compile_index)

    def test_ruff_runs_through_the_current_interpreter(self):
        self.assertEqual(
            check_all.RUFF_COMMAND,
            (check_all.PYTHON, '-m', 'ruff', 'check', '.'))

    def test_missing_ruff_skips_lint_without_failing(self):
        ret, calls, output, errors = self.run_all_with_ruff(False)
        self.assertEqual(ret, 0)
        self.assertNotIn(check_all.RUFF_COMMAND, calls)
        self.assertIn(('after',), calls)
        self.assertIn('SKIPPED', errors)
        self.assertIn('pip install ruff==%s' % (check_all.RUFF_VERSION,),
                      errors)
        self.assertIn('CI', errors)
        # The notice belongs on stderr, next to the failures, and not in
        # the middle of the command output on stdout.
        self.assertNotIn('SKIPPED', output)

    def test_skip_notice_is_repeated_at_the_end_of_the_run(self):
        _ret, _calls, _output, errors = self.run_all_with_ruff(False)
        self.assertEqual(errors.count('SKIPPED'), 2)
        # A run that ends in "OK" must still end by naming the step that
        # was skipped.
        self.assertTrue(errors.rstrip('\n').endswith(
            check_all.RUFF_SKIP_NOTICE))

    def test_installed_ruff_runs_and_findings_fail_the_run(self):
        ret, calls, output, errors = self.run_all_with_ruff(
            True, ruff_status=1)
        self.assertEqual(ret, 1)
        self.assertEqual(calls, [check_all.RUFF_COMMAND])
        self.assertNotIn('SKIPPED', output)
        self.assertNotIn('SKIPPED', errors)

    def test_installed_ruff_without_findings_continues(self):
        ret, calls, _output, errors = self.run_all_with_ruff(True)
        self.assertEqual(ret, 0)
        self.assertEqual(calls, [check_all.RUFF_COMMAND, ('after',)])
        self.assertEqual(errors, '')

    def test_unpinned_ruff_version_warns_but_still_lints(self):
        ret, calls, output, errors = self.run_all_with_ruff(
            True, ruff_version='0.0.1')
        self.assertEqual(ret, 0)
        self.assertEqual(calls, [check_all.RUFF_COMMAND, ('after',)])
        self.assertNotIn('SKIPPED', errors)
        self.assertIn('WARNING', errors)
        self.assertIn('0.0.1', errors)
        self.assertIn('pip install ruff==%s' % (check_all.RUFF_VERSION,),
                      errors)
        self.assertNotIn('WARNING', output)
        # Reported while the step runs and again as the last word of the
        # run, like the skip notice.
        self.assertEqual(errors.count('WARNING'), 2)
        self.assertTrue(errors.rstrip('\n').endswith(
            check_all.ruff_version_notice('0.0.1')))

    def test_unknown_ruff_version_does_not_warn(self):
        ret, calls, _output, errors = self.run_all_with_ruff(
            True, ruff_version=None)
        self.assertEqual(ret, 0)
        self.assertEqual(calls, [check_all.RUFF_COMMAND, ('after',)])
        self.assertEqual(errors, '')

    def test_ruff_notices_reports_the_skip_and_the_version(self):
        old_module_available = check_all.module_available
        old_installed_version = check_all.ruff_installed_version
        try:
            check_all.module_available = lambda name: False
            check_all.ruff_installed_version = lambda: check_all.RUFF_VERSION
            self.assertEqual(check_all.ruff_notices(),
                             (True, [check_all.RUFF_SKIP_NOTICE]))
            check_all.module_available = lambda name: True
            self.assertEqual(check_all.ruff_notices(), (False, []))
            check_all.ruff_installed_version = lambda: '9.9.9'
            self.assertEqual(
                check_all.ruff_notices(),
                (False, [check_all.ruff_version_notice('9.9.9')]))
        finally:
            check_all.module_available = old_module_available
            check_all.ruff_installed_version = old_installed_version

    def test_installed_ruff_version_never_raises(self):
        old_python = check_all.PYTHON
        old_module = check_all.RUFF_MODULE
        try:
            # Neither distribution metadata nor a module to run exists.
            check_all.RUFF_MODULE = 'klipper_z_calibration_missing'
            self.assertIsNone(check_all.ruff_installed_version())
            check_all.PYTHON = 'klipper_z_calibration_missing_binary'
            self.assertIsNone(check_all.ruff_installed_version())
        finally:
            check_all.PYTHON = old_python
            check_all.RUFF_MODULE = old_module

    def test_module_available_detects_missing_module(self):
        self.assertTrue(check_all.module_available('unittest'))
        self.assertFalse(
            check_all.module_available('klipper_z_calibration_missing'))

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
