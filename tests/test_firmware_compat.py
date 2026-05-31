import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / 'scripts' / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


firmware_compat = load_script('check_firmware_compat.py')


class FirmwareCompatTest(unittest.TestCase):
    def test_version_key_sorts_semver_tags(self):
        tags = ['v1.10.0', 'v1.2.9', 'v1.2.10']
        self.assertEqual(
            sorted(tags, key=firmware_compat.version_key),
            ['v1.2.9', 'v1.2.10', 'v1.10.0'])

    def test_latest_klipper_tag_parses_remote_refs(self):
        old_run = firmware_compat.run

        class Result:
            stdout = (
                "aaaaaaaa\trefs/tags/v0.12.0\n"
                "bbbbbbbb\trefs/tags/v0.13.1\n"
                "cccccccc\trefs/tags/not-a-release\n"
            )

        try:
            firmware_compat.run = lambda *args, **kwargs: Result()
            self.assertEqual(firmware_compat.latest_klipper_tag(), 'v0.13.1')
        finally:
            firmware_compat.run = old_run

    def test_run_checks_clones_expected_targets(self):
        calls = []
        checks = []
        old_latest = firmware_compat.latest_klipper_tag
        old_clone = firmware_compat.clone_or_update
        old_check = firmware_compat.check_contract
        try:
            firmware_compat.latest_klipper_tag = lambda: 'v0.13.1'

            def fake_clone(path, url, ref, update=True):
                calls.append((path.name, url, ref, update))

            def fake_check(name, path):
                checks.append((name, path.name))
                return 0

            firmware_compat.clone_or_update = fake_clone
            firmware_compat.check_contract = fake_check
            with tempfile.TemporaryDirectory() as tempdir:
                ret = firmware_compat.run_checks(tempdir, update=True)
        finally:
            firmware_compat.latest_klipper_tag = old_latest
            firmware_compat.clone_or_update = old_clone
            firmware_compat.check_contract = old_check
        self.assertEqual(ret, 0)
        self.assertEqual(calls, [
            ('klipper-release', firmware_compat.KLIPPER_URL,
             'v0.13.1', True),
            ('klipper-master', firmware_compat.KLIPPER_URL,
             'master', True),
            ('kalico-main', firmware_compat.KALICO_URL,
             'main', True),
        ])
        self.assertEqual(checks, [
            ('klipper-release', 'klipper-release'),
            ('klipper-master', 'klipper-master'),
            ('kalico-main', 'kalico-main'),
        ])

    def test_no_update_uses_existing_checkouts_without_remote_lookup(self):
        calls = []
        checks = []
        old_latest = firmware_compat.latest_klipper_tag
        old_clone = firmware_compat.clone_or_update
        old_check = firmware_compat.check_contract
        try:
            def fail_latest():
                raise AssertionError("latest_klipper_tag should not run")

            def fake_clone(path, url, ref, update=True):
                calls.append((path.name, url, ref, update))

            def fake_check(name, path):
                checks.append((name, path.name))
                return 0

            firmware_compat.latest_klipper_tag = fail_latest
            firmware_compat.clone_or_update = fake_clone
            firmware_compat.check_contract = fake_check
            with tempfile.TemporaryDirectory() as tempdir:
                tempdir = pathlib.Path(tempdir)
                for name in ['klipper-release', 'klipper-master',
                             'kalico-main']:
                    (tempdir / name).mkdir()
                ret = firmware_compat.run_checks(tempdir, update=False)
        finally:
            firmware_compat.latest_klipper_tag = old_latest
            firmware_compat.clone_or_update = old_clone
            firmware_compat.check_contract = old_check
        self.assertEqual(ret, 0)
        self.assertEqual(calls, [
            ('klipper-release', firmware_compat.KLIPPER_URL, None, False),
            ('klipper-master', firmware_compat.KLIPPER_URL, None, False),
            ('kalico-main', firmware_compat.KALICO_URL, None, False),
        ])
        self.assertEqual(checks, [
            ('klipper-release', 'klipper-release'),
            ('klipper-master', 'klipper-master'),
            ('kalico-main', 'kalico-main'),
        ])

    def test_no_update_requires_existing_checkouts(self):
        old_latest = firmware_compat.latest_klipper_tag
        try:
            def fail_latest():
                raise AssertionError("latest_klipper_tag should not run")

            firmware_compat.latest_klipper_tag = fail_latest
            with tempfile.TemporaryDirectory() as tempdir:
                with self.assertRaises(RuntimeError) as err:
                    firmware_compat.run_checks(tempdir, update=False)
        finally:
            firmware_compat.latest_klipper_tag = old_latest
        self.assertIn('run without --no-update first', str(err.exception))


if __name__ == '__main__':
    unittest.main()
