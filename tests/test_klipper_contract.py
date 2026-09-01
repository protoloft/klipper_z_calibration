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
                  gcode_macro_source=None, manual_probe_source='default',
                  generic_cartesian_source=None, stepper_source=None,
                  pins_source=None, query_endstops_source=None):
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
        (root / 'klippy' / 'stepper.py').write_text(
            stepper_source or self.valid_stepper_source(),
            encoding='utf-8')
        (root / 'klippy' / 'pins.py').write_text(
            pins_source or self.valid_pins_source(),
            encoding='utf-8')
        (root / 'klippy' / 'extras' / 'query_endstops.py').write_text(
            query_endstops_source or self.valid_query_endstops_source(),
            encoding='utf-8')
        if generic_cartesian_source is not None:
            (root / 'klippy' / 'kinematics').mkdir(parents=True)
            (root / 'klippy' / 'kinematics'
             / 'generic_cartesian.py').write_text(generic_cartesian_source,
                                                  encoding='utf-8')
        return tempdir, root

    def valid_generic_cartesian_source(self):
        """Return source for the supported generic_cartesian kinematics."""
        return (
            "VALID_AXES = ['x', 'y', 'z']\n"
            "class MainCarriage:\n"
            "    def get_axis(self):\n"
            "        return self.axis\n"
            "    def get_rail(self):\n"
            "        return self.rail\n"
            "class GenericCartesianKinematics:\n"
            "    def _load_kinematics(self, config):\n"
            "        primary_carriages = []\n"
            "        self.primary_carriages = primary_carriages\n")

    def valid_pins_source(self):
        """Return source for the pin setup a plugin-owned endstop needs."""
        return (
            "class PrinterPins:\n"
            "    def parse_pin(self, pin_desc, can_invert=False,\n"
            "                  can_pullup=False):\n"
            "        if [c for c in '^~!:' if c in pin_desc]:\n"
            "            raise error('Invalid pin description')\n"
            "        return {}\n"
            "    def setup_pin(self, pin_type, pin_desc):\n"
            "        pass\n"
            "    def allow_multi_use_pin(self, pin_desc):\n"
            "        self.parse_pin(pin_desc)\n")

    def valid_query_endstops_source(self):
        """Return source for the endstop registration of QUERY_ENDSTOPS."""
        return (
            "class QueryEndstops:\n"
            "    def register_endstop(self, mcu_endstop, name):\n"
            "        pass\n")

    def valid_stepper_source(self):
        """Return source for a rail exposing its registered endstops."""
        return (
            "class GenericPrinterRail:\n"
            "    def __init__(self, config):\n"
            "        self.endstops = []\n"
            "        self.lookup_endstop(self.endstop_pin, self.name)\n"
            "    def lookup_endstop(self, endstop_pin, name):\n"
            "        self.endstops.append((mcu_endstop, name))\n"
            "        self.query_endstops.register_endstop(mcu_endstop, name)\n"
            "    def get_endstops(self):\n"
            "        return list(self.endstops)\n"
            + self.mcu_stepper_source())

    def mcu_stepper_source(self):
        """Return source for the stepper axis test used on mcu_identify."""
        return (
            "class MCU_stepper:\n"
            "    def is_active_axis(self, axis):\n"
            "        pass\n")

    def legacy_stepper_source(self):
        """Return source for the rail class of older Klipper and Kalico."""
        return (
            "class PrinterRail:\n"
            "    def add_extra_stepper(self, config):\n"
            "        self.endstops.append((mcu_endstop, name))\n"
            "        query_endstops.register_endstop(mcu_endstop, name)\n"
            "    def get_endstops(self):\n"
            "        return list(self.endstops)\n"
            + self.mcu_stepper_source())

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

    def test_missing_generic_cartesian_passes(self):
        # Older Klipper and Kalico ship no generic_cartesian kinematics.
        tempdir, root = self.make_tree()
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])

    def test_generic_cartesian_carriage_contract_passes(self):
        tempdir, root = self.make_tree(
            generic_cartesian_source=self.valid_generic_cartesian_source())
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])

    def test_missing_carriage_rail_lookup_fails(self):
        source = self.valid_generic_cartesian_source().replace(
            "    def get_rail(self):\n"
            "        return self.rail\n", "")
        tempdir, root = self.make_tree(generic_cartesian_source=source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: MainCarriage.get_rail not found', errors)

    def test_renamed_primary_carriages_attribute_fails(self):
        # The loader keeps a local variable of the same name, so only the
        # renamed attribute may decide the outcome.
        source = self.valid_generic_cartesian_source().replace(
            'self.primary_carriages', 'self.axis_carriages')
        tempdir, root = self.make_tree(generic_cartesian_source=source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: kinematics primary_carriages not found',
            errors)

    def test_reordered_valid_axes_fails(self):
        source = self.valid_generic_cartesian_source().replace(
            "VALID_AXES = ['x', 'y', 'z']", "VALID_AXES = ['z', 'y', 'x']")
        tempdir, root = self.make_tree(generic_cartesian_source=source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: kinematics VALID_AXES order not found',
            errors)

    def test_missing_pin_setup_fails(self):
        # Without setup_pin() the plugin cannot own an endstop on a pin.
        pins_source = self.valid_pins_source().replace(
            "    def setup_pin(self, pin_type, pin_desc):\n"
            "        pass\n", "")
        tempdir, root = self.make_tree(pins_source=pins_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn('Klipper contract failed: pins setup_pin not found',
                      errors)

    def test_missing_multi_use_pin_support_fails(self):
        # Sharing the pin with another consumer depends on this call.
        pins_source = self.valid_pins_source().replace(
            "    def allow_multi_use_pin(self, pin_desc):\n"
            "        self.parse_pin(pin_desc)\n", "")
        tempdir, root = self.make_tree(pins_source=pins_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: pins allow_multi_use_pin not found',
            errors)

    def test_multi_use_pin_taking_modifiers_fails(self):
        # PinEndstop strips '^', '~' and '!' because allow_multi_use_pin()
        # parses without them. If it ever accepted them, the stripping would
        # have to be revisited instead of silently staying in place.
        pins_source = self.valid_pins_source().replace(
            "        self.parse_pin(pin_desc)\n",
            "        self.parse_pin(pin_desc, True, True)\n")
        tempdir, root = self.make_tree(pins_source=pins_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: allow_multi_use_pin no longer parses'
            ' a bare pin name', errors)

    def test_changed_pin_modifier_set_fails(self):
        # A fourth modifier character would have to be added to
        # _PIN_MODIFIERS in klipper_compat.py.
        pins_source = self.valid_pins_source().replace("'^~!:'", "'^~!%:'")
        tempdir, root = self.make_tree(pins_source=pins_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: pin modifier set not found', errors)

    def test_missing_query_endstops_register_endstop_fails(self):
        tempdir, root = self.make_tree(
            query_endstops_source="class QueryEndstops:\n    pass\n")
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: query_endstops register_endstop'
            ' not found', errors)

    def test_missing_stepper_axis_test_fails(self):
        # A plugin-owned endstop selects its Z steppers with this method.
        stepper_source = self.valid_stepper_source().replace(
            self.mcu_stepper_source(),
            "class MCU_stepper:\n"
            "    def get_name(self):\n"
            "        pass\n")
        tempdir, root = self.make_tree(stepper_source=stepper_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: stepper is_active_axis not found',
            errors)

    def test_legacy_rail_class_passes_the_baseline(self):
        # Klipper v0.13.0 and Kalico name the rail class PrinterRail, so
        # the baseline must not require the current class name.
        tempdir, root = self.make_tree(
            stepper_source=self.legacy_stepper_source())
        with tempdir:
            self.assertEqual(check_contract.check_klipper_contract(root), [])

    def test_missing_rail_endstop_list_registration_fails(self):
        # The rail has to keep the object it hands to query_endstops.
        stepper_source = self.valid_stepper_source().replace(
            "        self.endstops.append((mcu_endstop, name))\n", "")
        tempdir, root = self.make_tree(stepper_source=stepper_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: rail endstop list registration'
            ' not found', errors)

    def test_missing_query_endstops_registration_fails(self):
        stepper_source = self.valid_stepper_source().replace(
            "        self.query_endstops.register_endstop(mcu_endstop,"
            " name)\n", "")
        tempdir, root = self.make_tree(stepper_source=stepper_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: query_endstops registration of the'
            ' rail endstop not found', errors)

    def test_missing_rail_get_endstops_fails(self):
        # The Z rail is recognized by the endstop it registered, so this is
        # required for every supported kinematics, not only for carriages.
        stepper_source = self.valid_stepper_source().replace(
            "    def get_endstops(self):\n"
            "        return list(self.endstops)\n", "")
        tempdir, root = self.make_tree(stepper_source=stepper_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: rail get_endstops not found', errors)

    def test_missing_carriage_rail_get_endstops_fails(self):
        stepper_source = self.valid_stepper_source().replace(
            'class GenericPrinterRail:', 'class OtherRail:')
        tempdir, root = self.make_tree(
            generic_cartesian_source=self.valid_generic_cartesian_source(),
            stepper_source=stepper_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: GenericPrinterRail.get_endstops'
            ' not found', errors)

    def test_late_primary_endstop_registration_fails(self):
        # A rail that no longer registers its own endstop first would make
        # the first rail endstop an extra carriage switch.
        stepper_source = self.valid_stepper_source().replace(
            "        self.lookup_endstop(self.endstop_pin, self.name)\n", "")
        tempdir, root = self.make_tree(
            generic_cartesian_source=self.valid_generic_cartesian_source(),
            stepper_source=stepper_source)
        with tempdir:
            errors = check_contract.check_klipper_contract(root)
        self.assertIn(
            'Klipper contract failed: rail primary endstop registration'
            ' not found', errors)

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
