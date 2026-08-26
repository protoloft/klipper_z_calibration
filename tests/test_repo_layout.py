# Unit tests for repository root layout and sys.path shadowing safety.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

# Top-level names that exist in the repository root today. z_calibration and
# klipper_compat are the only runtime modules; the rest are support
# directories. New entries need a deliberate decision, not an entry here.
ALLOWED_ROOT_NAMES = frozenset([
    'z_calibration',
    'klipper_compat',
    'scripts',
    'tests',
    'docs',
    'pictures',
])

# klippy modules that this plugin imports or that Klipper loads while the
# plugin is active. A repository root entry with one of these names would
# take over the corresponding klippy import for the whole Klipper process.
KLIPPY_MODULE_NAMES = frozenset([
    'probe',
    'configfile',
    'toolhead',
    'homing',
    'mcu',
    'gcode',
    'gcode_move',
    'bed_mesh',
    'query_endstops',
    'gcode_macro',
    'stepper',
    'pins',
    'klippy',
    'extras',
    'safe_z_home',
])

SHADOWING_REASON = (
    "z_calibration.py runs sys.path.insert(0, MODULE_PATH) inside the live"
    " Klipper process, so every import in klippy resolves against this"
    " repository checkout first - including the standard library. A"
    " root-level module or package with a colliding name silently replaces"
    " the real module process-wide and breaks Klipper far away from this"
    " plugin. Rename or move the offending entry; do not extend"
    " ALLOWED_ROOT_NAMES to make this test pass.")


def root_top_level_names():
    """Return importable top-level names in the repository root."""
    names = set()
    for entry in ROOT.iterdir():
        if entry.name.startswith('.') or entry.name == '__pycache__':
            continue
        if entry.is_dir():
            # Directories are importable as namespace packages.
            names.add(entry.name)
        elif entry.suffix == '.py':
            names.add(entry.stem)
    return names


class RepoLayoutTest(unittest.TestCase):
    """Covers the root naming discipline required by the install model."""

    def assert_no_collision(self, reserved, kind):
        """Assert that no unexpected root name shadows a reserved module."""
        collisions = sorted((root_top_level_names() - ALLOWED_ROOT_NAMES)
                            & set(reserved))
        self.assertEqual(collisions, [],
                         "repository root shadows %s: %s. %s"
                         % (kind, ', '.join(collisions), SHADOWING_REASON))

    @unittest.skipUnless(hasattr(sys, 'stdlib_module_names'),
                         'sys.stdlib_module_names needs Python 3.10+')
    def test_root_names_do_not_shadow_stdlib_modules(self):
        self.assert_no_collision(sys.stdlib_module_names,
                                 'standard library modules')

    def test_root_names_do_not_shadow_klippy_modules(self):
        self.assert_no_collision(KLIPPY_MODULE_NAMES, 'klippy modules')

    def test_allowed_root_names_still_exist(self):
        missing = sorted(ALLOWED_ROOT_NAMES - root_top_level_names())
        self.assertEqual(missing, [],
                         "ALLOWED_ROOT_NAMES lists entries that no longer"
                         " exist: %s" % (', '.join(missing),))

    def test_no_unexpected_root_python_modules(self):
        modules = set([path.stem for path in ROOT.glob('*.py')])
        unexpected = sorted(modules - ALLOWED_ROOT_NAMES)
        self.assertEqual(unexpected, [],
                         "unexpected root-level Python modules: %s. %s"
                         % (', '.join(unexpected), SHADOWING_REASON))


if __name__ == '__main__':
    unittest.main()
