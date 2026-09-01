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


class BlankLineTest(unittest.TestCase):
    """Covers the blank line rule for class and function definitions."""

    def check(self, source):
        """Return blank line errors reported for a Python source string."""
        errors = []
        check_whitespace.check_blank_lines(
            pathlib.Path(check_whitespace.ROOT) / 'sample.py', source, errors)
        return errors

    def test_module_level_definitions_need_two_blank_lines(self):
        source = 'def first():\n    pass\n\ndef second():\n    pass\n'
        errors = self.check(source)
        self.assertEqual(len(errors), 1)
        self.assertIn('expected 2 blank line(s) before second, found 1',
                      errors[0])

    def test_methods_need_one_blank_line(self):
        source = ('class Sample:\n'
                  '    """Doc."""\n'
                  '\n'
                  '    def first(self):\n'
                  '        pass\n'
                  '    def second(self):\n'
                  '        pass\n')
        errors = self.check(source)
        self.assertEqual(len(errors), 1)
        self.assertIn('before second', errors[0])

    def test_nested_definition_needs_one_blank_line(self):
        source = ('def outer():\n'
                  '    """Doc."""\n'
                  '    def inner():\n'
                  '        pass\n'
                  '    return inner\n')
        errors = self.check(source)
        self.assertEqual(len(errors), 1)
        self.assertIn('before inner', errors[0])

    def test_first_statement_of_a_block_needs_no_blank_line(self):
        source = ('class Sample:\n'
                  '    def only(self):\n'
                  '        pass\n')
        self.assertEqual(self.check(source), [])

    def test_help_attribute_stays_attached_to_its_command(self):
        # Klipper keeps "cmd_X_help" on the line above its command, so the
        # blank line belongs before the pair and not between its halves.
        source = ('class Sample:\n'
                  '    def first(self):\n'
                  '        pass\n'
                  '\n'
                  '    cmd_SAMPLE_help = "Sample"\n'
                  '    def cmd_SAMPLE(self, gcmd):\n'
                  '        pass\n')
        self.assertEqual(self.check(source), [])

    def test_help_attribute_does_not_hide_a_missing_blank_line(self):
        source = ('class Sample:\n'
                  '    def first(self):\n'
                  '        pass\n'
                  '    cmd_SAMPLE_help = "Sample"\n'
                  '    def cmd_SAMPLE(self, gcmd):\n'
                  '        pass\n')
        errors = self.check(source)
        self.assertEqual(len(errors), 1)
        self.assertIn('before cmd_SAMPLE', errors[0])

    def test_comments_above_a_definition_belong_to_it(self):
        source = ('class Sample:\n'
                  '    def first(self):\n'
                  '        pass\n'
                  '\n'
                  '    # Explains the method below.\n'
                  '    def second(self):\n'
                  '        pass\n')
        self.assertEqual(self.check(source), [])

    def test_decorated_definitions_are_measured_at_the_decorator(self):
        source = ('class Sample:\n'
                  '    def first(self):\n'
                  '        pass\n'
                  '    @property\n'
                  '    def second(self):\n'
                  '        pass\n')
        errors = self.check(source)
        self.assertEqual(len(errors), 1)
        self.assertIn('before second', errors[0])

    def test_definitions_inside_string_literals_are_not_reported(self):
        # tests/test_klipper_contract.py embeds Klipper sources as strings; a
        # text search would report every "def" line inside them.
        source = ('SOURCE = """\n'
                  'class Fake:\n'
                  '    def first(self):\n'
                  '        pass\n'
                  '    def second(self):\n'
                  '        pass\n'
                  '"""\n')
        self.assertEqual(self.check(source), [])

    def test_unparsable_source_is_reported(self):
        errors = self.check('def broken(:\n')
        self.assertEqual(len(errors), 1)
        self.assertIn('cannot parse', errors[0])


if __name__ == '__main__':
    unittest.main()
