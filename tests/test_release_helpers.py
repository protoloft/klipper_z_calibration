# Unit tests for release validation and Moonraker update config helpers.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_script(name):
    """Load a script module from the repository scripts directory."""
    path = ROOT / 'scripts' / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_release = load_script('check_release.py')
update_moonraker = load_script('update_moonraker.py')


class ReleaseValidationTest(unittest.TestCase):
    """Covers release tag metadata validation."""

    def test_classifies_stable_tag(self):
        metadata = check_release.classify_tag('v1.2.3')
        self.assertEqual(metadata['version'], '1.2.3')
        self.assertEqual(metadata['channel'], 'stable')
        self.assertEqual(metadata['prerelease'], 'false')

    def test_classifies_beta_tag(self):
        metadata = check_release.classify_tag('v1.2.3-beta.4')
        self.assertEqual(metadata['version'], '1.2.3-beta.4')
        self.assertEqual(metadata['channel'], 'beta')
        self.assertEqual(metadata['prerelease'], 'true')

    def test_rejects_invalid_tags(self):
        for tag in ['1.2.3', 'v1.2', 'v1.2.3rc1', 'v1.2.3-beta']:
            with self.subTest(tag=tag):
                with self.assertRaises(check_release.ReleaseError):
                    check_release.classify_tag(tag)

    def test_rejects_channel_mismatch(self):
        metadata = check_release.classify_tag('v1.2.3-beta.1')
        with self.assertRaises(check_release.ReleaseError):
            check_release.validate_channel(metadata, 'stable')


class MoonrakerUpdateTest(unittest.TestCase):
    """Covers Moonraker update_manager config migration."""

    def test_adds_new_stable_section(self):
        updated, changed = update_moonraker.update_config_text(
            "[server]\nhost: 0.0.0.0\n", "/repo")
        self.assertTrue(changed)
        self.assertIn("[update_manager z_calibration]", updated)
        self.assertIn("channel: stable", updated)
        self.assertIn("path: /repo", updated)

    def test_migrates_existing_section_without_channel(self):
        text = (
            "[update_manager z_calibration]\n"
            "type: git_repo\n"
            "path: /repo\n"
            "\n"
            "[server]\n"
            "host: 0.0.0.0\n"
        )
        updated, changed = update_moonraker.update_config_text(text, "/repo")
        self.assertTrue(changed)
        self.assertIn("type: git_repo\nchannel: stable\npath:", updated)

    def test_preserves_existing_explicit_channels(self):
        for channel in ['stable', 'beta', 'dev']:
            text = (
                "[update_manager z_calibration]\n"
                "type: git_repo\n"
                "channel: %s\n"
                "path: /repo\n" % (channel,))
            with self.subTest(channel=channel):
                updated, changed = update_moonraker.update_config_text(
                    text, "/other")
                self.assertFalse(changed)
                self.assertEqual(updated, text)

    def test_file_update_reports_changed_once(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / 'moonraker.conf'
            path.write_text("[server]\nhost: 0.0.0.0\n", encoding='utf-8')
            self.assertTrue(update_moonraker.update_config_file(path, "/repo"))
            self.assertFalse(update_moonraker.update_config_file(path, "/repo"))


if __name__ == '__main__':
    unittest.main()
