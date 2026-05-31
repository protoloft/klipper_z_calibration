import importlib.util
import os
import pathlib
import sys
import tempfile
import types
import unittest

from fakes import FakeMCUEndstop


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ImportBootstrapTest(unittest.TestCase):
    def test_symlinked_main_module_imports_repo_local_compat(self):
        old_path = list(sys.path)
        old_mcu = sys.modules.get('mcu')
        old_compat = sys.modules.get('klipper_compat')
        old_module = sys.modules.get('z_calibration_symlink_test')
        try:
            sys.path[:] = [
                path for path in sys.path
                if pathlib.Path(path or os.curdir).resolve() != ROOT
            ]
            sys.modules['mcu'] = types.SimpleNamespace(
                MCU_endstop=FakeMCUEndstop)
            sys.modules.pop('klipper_compat', None)
            sys.modules.pop('z_calibration_symlink_test', None)

            with tempfile.TemporaryDirectory() as tempdir:
                extras = pathlib.Path(tempdir) / 'klippy' / 'extras'
                extras.mkdir(parents=True)
                link_path = extras / 'z_calibration.py'
                os.symlink(ROOT / 'z_calibration.py', link_path)

                spec = importlib.util.spec_from_file_location(
                    'z_calibration_symlink_test', link_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)

            self.assertEqual(pathlib.Path(module.MODULE_PATH), ROOT)
            compat_file = pathlib.Path(sys.modules['klipper_compat'].__file__)
            self.assertEqual(compat_file.resolve(), ROOT / 'klipper_compat.py')
        finally:
            sys.path[:] = old_path
            if old_mcu is None:
                sys.modules.pop('mcu', None)
            else:
                sys.modules['mcu'] = old_mcu
            if old_compat is None:
                sys.modules.pop('klipper_compat', None)
            else:
                sys.modules['klipper_compat'] = old_compat
            if old_module is None:
                sys.modules.pop('z_calibration_symlink_test', None)
            else:
                sys.modules['z_calibration_symlink_test'] = old_module


if __name__ == '__main__':
    unittest.main()
