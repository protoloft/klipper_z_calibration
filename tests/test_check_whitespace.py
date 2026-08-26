# Unit tests for whitespace validation file selection.
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


check_whitespace = load_script('check_whitespace.py')


class IterFilesTest(unittest.TestCase):
    """Covers which files whitespace validation looks at."""

    def collect(self, build):
        """Return checked file names for a temporary repository tree."""
        with tempfile.TemporaryDirectory() as tempdir:
            root = pathlib.Path(tempdir)
            build(root)
            original = check_whitespace.ROOT
            check_whitespace.ROOT = root
            try:
                return sorted([path.name
                               for path in check_whitespace.iter_files()])
            finally:
                check_whitespace.ROOT = original

    def test_repository_files_are_checked(self):
        def build(root):
            (root / 'z_calibration.py').write_text('x = 1\n')
        self.assertEqual(self.collect(build), ['z_calibration.py'])

    def test_ignored_tool_output_is_not_checked(self):
        # These are gitignored build artifacts. .coverage in particular is a
        # binary file, so checking it would fail the UTF-8 rule and block an
        # unrelated task after any local coverage run.
        def build(root):
            (root / 'z_calibration.py').write_text('x = 1\n')
            (root / '.coverage').write_bytes(b'\x00\x01binary')
            for name in ['htmlcov', 'venv', '.venv', 'env', '.ruff_cache']:
                (root / name).mkdir()
                (root / name / 'junk.py').write_bytes(b'\xff\xfe')
        self.assertEqual(self.collect(build), ['z_calibration.py'])

    def test_binary_assets_are_still_skipped_by_suffix(self):
        def build(root):
            (root / 'banner.png').write_bytes(b'\x89PNG')
            (root / 'README.md').write_text('hi\n')
        self.assertEqual(self.collect(build), ['README.md'])


if __name__ == '__main__':
    unittest.main()
