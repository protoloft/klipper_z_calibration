# Unit tests for release validation and Moonraker update config helpers.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib.util
import pathlib
import re
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
            backup = path.with_name(path.name + '.bak')
            self.assertTrue(update_moonraker.update_config_file(path, "/repo"))
            self.assertEqual(backup.read_text(encoding='utf-8'),
                             "[server]\nhost: 0.0.0.0\n")
            self.assertFalse(update_moonraker.update_config_file(path, "/repo"))


class ReleaseWorkflowTest(unittest.TestCase):
    """Covers release workflow safety properties."""

    def workflow_text(self, name='release.yml'):
        """Return the tracked GitHub release workflow text."""
        path = ROOT / '.github' / 'workflows' / name
        return path.read_text(encoding='utf-8')

    def workflow_texts(self):
        """Return all tracked GitHub workflow texts keyed by file name."""
        workflow_dir = ROOT / '.github' / 'workflows'
        return {
            path.name: path.read_text(encoding='utf-8')
            for path in sorted(workflow_dir.glob('*.yml'))
        }

    def test_release_ref_is_validated_before_release_checkout(self):
        text = self.workflow_text()
        self.assertLess(text.index('name: Validate release ref'),
                        text.index('name: Check out release tag'))
        self.assertIn(
            'ref: refs/tags/${{ needs.validate-release-ref.outputs.tag }}',
            text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('permissions:\n  contents: read', text)

    def test_checkout_credentials_are_not_persisted(self):
        for name, text in self.workflow_texts().items():
            for match in re.finditer(r'uses:\s+actions/checkout@', text):
                next_step = text.find('\n      - name:', match.end())
                checkout_block = text[match.end():]
                if next_step != -1:
                    checkout_block = text[match.end():next_step]
                with self.subTest(workflow=name, offset=match.start()):
                    self.assertIn('persist-credentials: false',
                                  checkout_block)

    def test_release_publish_job_does_not_checkout_source(self):
        text = self.workflow_text()
        draft_release = text[text.index('  draft-release:'):]
        self.assertNotIn('actions/checkout', draft_release)
        self.assertIn('uses: actions/download-artifact@', draft_release)
        self.assertIn('uses: actions/upload-artifact@', text)
        self.assertLess(text.index('uses: actions/upload-artifact@'),
                        text.index('  draft-release:'))
        self.assertEqual(text.count('contents: write'), 1)
        self.assertIn('permissions:\n      contents: write', draft_release)

    def test_release_workflow_updates_existing_draft_assets(self):
        text = self.workflow_text()
        self.assertIn('gh release view "$RELEASE_TAG"', text)
        self.assertIn(
            'gh release upload "$RELEASE_TAG" dist/*.tar.gz --clobber',
            text)
        self.assertIn('already exists and is not a draft', text)


if __name__ == '__main__':
    unittest.main()
