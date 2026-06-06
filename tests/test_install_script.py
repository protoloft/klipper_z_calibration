# Unit tests for installer behavior and cleanup.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os
import pathlib
import shlex
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / 'install.sh'


def q(value):
    """Shell-quote a value for bash snippets."""
    return shlex.quote(str(value))


def run_bash(script):
    """Source install.sh and run a bash snippet in the repo root."""
    command = ". %s\n%s" % (q(INSTALL_SH), script)
    return subprocess.run(
        ['bash', '-c', command],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False)


def make_klipper_tree(tempdir, kalico=False):
    """Create a minimal fake Klipper/Kalico tree for installer tests."""
    root = pathlib.Path(tempdir) / 'klipper'
    (root / 'klippy' / 'extras').mkdir(parents=True)
    if kalico:
        (root / 'klippy' / 'plugins').mkdir(parents=True)
    return root


class InstallScriptTest(unittest.TestCase):
    """Covers installer link creation and cleanup behavior."""

    def test_links_stock_klipper_extra_only(self):
        with tempfile.TemporaryDirectory() as tempdir:
            klipper = make_klipper_tree(tempdir)
            result = run_bash(
                "KLIPPER_PATH=%s\n"
                "set_install_paths\n"
                "link_extension\n" % (q(klipper),))
            self.assertEqual(result.returncode, 0, result.stderr)
            link = klipper / 'klippy' / 'extras' / 'z_calibration.py'
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), ROOT / 'z_calibration.py')
            self.assertFalse(
                (klipper / 'klippy' / 'extras' / 'klipper_compat.py').exists())

    def test_links_kalico_plugin_and_cleans_old_repo_links(self):
        with tempfile.TemporaryDirectory() as tempdir:
            klipper = make_klipper_tree(tempdir, kalico=True)
            extras = klipper / 'klippy' / 'extras'
            plugins = klipper / 'klippy' / 'plugins'
            os.symlink(ROOT / 'z_calibration.py',
                       extras / 'z_calibration.py')
            os.symlink(ROOT / 'klipper_compat.py',
                       extras / 'klipper_compat.py')
            os.symlink(ROOT / 'klipper_compat.py',
                       plugins / 'klipper_compat.py')
            result = run_bash(
                "KLIPPER_PATH=%s\n"
                "set_install_paths\n"
                "link_extension\n" % (q(klipper),))
            self.assertEqual(result.returncode, 0, result.stderr)
            link = plugins / 'z_calibration.py'
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), ROOT / 'z_calibration.py')
            self.assertFalse((extras / 'z_calibration.py').exists())
            self.assertFalse((extras / 'klipper_compat.py').exists())
            self.assertFalse((plugins / 'klipper_compat.py').exists())

    def test_uninstall_removes_only_repo_owned_python_links(self):
        with tempfile.TemporaryDirectory() as tempdir:
            klipper = make_klipper_tree(tempdir)
            extras = klipper / 'klippy' / 'extras'
            os.symlink(ROOT / 'z_calibration.py',
                       extras / 'z_calibration.py')
            regular = extras / 'klipper_compat.py'
            regular.write_text("do not remove\n", encoding='utf-8')
            (extras / 'z_calibration.pyc').write_text("bytecode\n",
                                                      encoding='utf-8')
            result = run_bash(
                "KLIPPER_PATH=%s\n"
                "set_install_paths\n"
                "uinstall\n" % (q(klipper),))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((extras / 'z_calibration.py').exists())
            self.assertFalse((extras / 'z_calibration.pyc').exists())
            self.assertTrue(regular.exists())
            self.assertEqual(regular.read_text(encoding='utf-8'),
                             "do not remove\n")

    def test_uninstall_main_does_not_require_moonraker_config(self):
        result = run_bash(
            "verify_ready(){ echo verify; }\n"
            "check_klipper(){ echo check_klipper; }\n"
            "check_klipper_path(){ echo check_path; }\n"
            "check_requirements(){ echo bad_requirements; return 42; }\n"
            "uinstall(){ echo uninstall; }\n"
            "restart_klipper(){ echo restart; }\n"
            "main -u\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('bad_requirements', result.stdout)
        self.assertIn('uninstall', result.stdout)

    def test_main_rejects_invalid_num_installs_before_service_checks(self):
        for value in ['0', '-1', 'abc']:
            with self.subTest(value=value):
                result = run_bash(
                    "check_klipper(){ echo bad_service_check; }\n"
                    "main -n %s\n" % (q(value),))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("-n must be a positive integer", result.stdout)
                self.assertNotIn("bad_service_check", result.stdout)

    def test_default_moonraker_config_falls_back_to_old_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            default = pathlib.Path(tempdir) / 'printer_data' / 'moonraker.conf'
            fallback = pathlib.Path(tempdir) / 'klipper_config'
            fallback.mkdir()
            fallback_config = fallback / 'moonraker.conf'
            fallback_config.write_text("[server]\n", encoding='utf-8')
            result = run_bash(
                "MOONRAKER_CONFIG=%s\n"
                "MOONRAKER_FALLBACK=%s\n"
                "MOONRAKER_CONFIG_CUSTOM=0\n"
                "resolve_moonraker_config\n"
                "printf 'selected=%%s\\n' \"$MOONRAKER_CONFIG\"\n"
                % (q(default), q(fallback_config)))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("selected=%s" % (fallback_config,), result.stdout)


if __name__ == '__main__':
    unittest.main()
