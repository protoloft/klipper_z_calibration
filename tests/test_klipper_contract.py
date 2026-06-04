# Unit tests for Klipper source contract validation.
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


check_contract = load_script('check_klipper_contract.py')


class KlipperContractTest(unittest.TestCase):
    """Covers synthetic Klipper source contract profiles."""

    def make_tree(self, probe_source=None, homing_source=None,
                  bed_mesh_source=None, mcu_source=None,
                  gcode_macro_source=None, manual_probe_source='default'):
        """Create a temporary synthetic Klipper source tree."""
        tempdir = tempfile.TemporaryDirectory()
        root = pathlib.Path(tempdir.name)
        (root / 'klippy' / 'extras').mkdir(parents=True)
        (root / 'klippy' / 'mcu.py').write_text(
            mcu_source or "class MCU_endstop:\n    pass\n",
            encoding='utf-8')
        (root / 'klippy' / 'extras' / 'probe.py').write_text(
            probe_source or self.valid_probe_source(),
            encoding='utf-8')
        if manual_probe_source == 'default':
            manual_probe_source = self.valid_manual_probe_source()
        if manual_probe_source is not None:
            (root / 'klippy' / 'extras' / 'manual_probe.py').write_text(
                manual_probe_source,
                encoding='utf-8')
        (root / 'klippy' / 'extras' / 'homing.py').write_text(
            homing_source or (
                "class PrinterHoming:\n"
                "    def probing_move(self, endstop, pos, speed):\n"
                "        pass\n"),
            encoding='utf-8')
        (root / 'klippy' / 'extras' / 'bed_mesh.py').write_text(
            bed_mesh_source or "zero_reference_position = None\n",
            encoding='utf-8')
        (root / 'klippy' / 'extras' / 'gcode_macro.py').write_text(
            gcode_macro_source or self.valid_gcode_macro_source(),
            encoding='utf-8')
        return tempdir, root

    def valid_probe_source(self):
        """Return source for a modern supported probe profile."""
        return (
            "class PrinterProbe:\n"
            "    def start_probe_session(self, gcmd):\n"
            "        pass\n"
            "class ProbeSession:\n"
            "    def run_probe(self, gcmd):\n"
            "        pass\n"
            "    def pull_probed_results(self):\n"
            "        pass\n"
            "    def end_probe_session(self):\n"
            "        pass\n")

    def valid_manual_probe_source(self):
        """Return source containing a ProbeResult definition."""
        return (
            "class ProbeResult:\n"
            "    def __init__(self):\n"
            "        self.bed_z = 0\n"
            "        self.test_x = 0\n"
            "        self.test_y = 0\n"
            "        self.test_z = 0\n")

    def valid_legacy_probe_source(self):
        """Return source for a legacy MCU endstop probe profile."""
        return (
            "class ProbeEndstopWrapper:\n"
            "    def __init__(self):\n"
            "        self.mcu_probe = None\n"
            "        self.get_steppers = self.mcu_probe.get_steppers\n"
            "        self.home_start = self.mcu_probe.home_start\n"
            "        self.home_wait = self.mcu_probe.home_wait\n"
            "        self.query_endstop = self.mcu_probe.query_endstop\n"
            "class PrinterProbe:\n"
            "    def __init__(self):\n"
            "        self.mcu_probe = ProbeEndstopWrapper()\n"
            "        self.sample_count = 1\n"
            "        self.samples_tolerance = 0.1\n"
            "        self.samples_retries = 0\n"
            "        self.lift_speed = 5.0\n"
            "        self.samples_result = 'average'\n"
            "        self.z_offset = 1.0\n"
            "    def multi_probe_begin(self):\n"
            "        pass\n"
            "    def multi_probe_end(self):\n"
            "        pass\n"
            "    def get_offsets(self):\n"
            "        pass\n"
            "    def run_probe(self, gcmd):\n"
            "        pass\n"
            "    def query_probe(self):\n"
            "        return self.mcu_probe.query_endstop(0.0)\n")

    def valid_gcode_macro_source(self):
        """Return source containing the template wrapper contract."""
        return (
            "class TemplateWrapper:\n"
            "    def __init__(self):\n"
            "        self.create_template_context = None\n"
            "    def run_gcode_from_command(self, context=None):\n"
            "        pass\n"
            "class PrinterGCodeMacro:\n"
            "    def load_template(self, config, option, default=None):\n"
            "        return TemplateWrapper()\n")

    def valid_kalico_gcode_macro_source(self):
        """Return source for Kalico's template wrapper layout."""
        return (
            "class TemplateWrapperJinja:\n"
            "    def __init__(self):\n"
            "        self.create_template_context = None\n"
            "    def run_gcode_from_command(self, context=None):\n"
            "        pass\n"
            "class Template:\n"
            "    def __getattr__(self, name):\n"
            "        return getattr(self.function, name)\n"
            "class PrinterGCodeMacro:\n"
            "    def load_template(self, config, option, default=None):\n"
            "        return Template()\n")

    def test_valid_synthetic_tree_passes(self):
        tempdir, root = self.make_tree()
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])
            self.assertEqual(check_contract.get_contract_profiles(root), [
                'modern_probe_result_session',
                'probe_session_xyz_list',
            ])

    def test_legacy_probe_result_location_passes(self):
        probe_source = self.valid_manual_probe_source()
        probe_source += self.valid_probe_source()
        tempdir, root = self.make_tree(probe_source=probe_source,
                                       manual_probe_source=None)
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])

    def test_probe_result_falls_back_when_manual_probe_has_no_result(self):
        probe_source = self.valid_manual_probe_source()
        probe_source += self.valid_probe_source()
        tempdir, root = self.make_tree(probe_source=probe_source,
                                       manual_probe_source="VALUE = 1\n")
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])
            self.assertIn('modern_probe_result_session',
                          check_contract.get_contract_profiles(root))

    def test_missing_probe_test_z_uses_session_list_profile(self):
        manual_probe_source = self.valid_manual_probe_source().replace(
            "        self.test_z = 0\n", "")
        tempdir, root = self.make_tree(
            manual_probe_source=manual_probe_source)
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])
            self.assertEqual(check_contract.get_contract_profiles(root),
                             ['probe_session_xyz_list'])

    def test_legacy_mcu_endstop_profile_passes(self):
        tempdir, root = self.make_tree(
            probe_source=self.valid_legacy_probe_source(),
            manual_probe_source=None)
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])
            self.assertEqual(check_contract.get_contract_profiles(root),
                             ['legacy_mcu_endstop_probe'])

    def test_missing_start_probe_session_fails(self):
        probe_source = self.valid_probe_source().replace(
            "    def start_probe_session(self, gcmd):\n"
            "        pass\n",
            "    pass\n")
        tempdir, root = self.make_tree(probe_source=probe_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: no supported probe compatibility profile '
            'found', errors)
        self.assertTrue(any('modern_probe_result_session missing' in error
                            for error in errors))
        self.assertTrue(any('PrinterProbe.start_probe_session not found'
                            in error for error in errors))

    def test_missing_homing_probing_move_fails(self):
        tempdir, root = self.make_tree(homing_source="class PrinterHoming:\n"
                                                     "    pass\n")
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: homing.probing_move not found', errors)

    def test_missing_mcu_endstop_fails(self):
        tempdir, root = self.make_tree(mcu_source="class Other:\n    pass\n")
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn('Klipper contract failed: MCU_endstop not found', errors)

    def test_kalico_template_layout_passes(self):
        tempdir, root = self.make_tree(
            gcode_macro_source=self.valid_kalico_gcode_macro_source())
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])

    def test_missing_template_wrapper_fails(self):
        tempdir, root = self.make_tree(gcode_macro_source="VALUE = 1\n")
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: PrinterGCodeMacro.load_template '
            'not found',
            errors)


if __name__ == '__main__':
    unittest.main()
