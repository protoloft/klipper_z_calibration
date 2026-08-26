# Unit tests for Klipper/Kalico compatibility wrappers and runtime contracts.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib
import sys
import types
import unittest

from fakes import FakeCarriage, FakeConfig, FakeEndstopRail, FakeError
from fakes import FakeForeignEndstopRail, FakeGenericCartesianKinematics
from fakes import FakeInactiveRail, FakeLegacyProbe, FakeMCUEndstop
from fakes import FakeOldDefaultsProbe, FakePrinter, FakeProbe, FakeRail
from fakes import FakeRecordingMCUEndstop, FakeTemplate


sys.modules['mcu'] = types.SimpleNamespace(MCU_endstop=FakeMCUEndstop)
klipper_compat = importlib.import_module('klipper_compat')


def probe_params():
    """Return standard fake probe defaults."""
    return {
        'samples': 1,
        'samples_tolerance': 0.1,
        'samples_tolerance_retries': 0,
        'lift_speed': 5.0,
        'samples_result': 'average',
    }


class FakeOldSessionProbe:
    """Probe exposing the old nested probe_session fallback."""

    def __init__(self):
        self.mcu_probe = FakeMCUEndstop()
        self.probe_session = types.SimpleNamespace(
            start_probe_session=lambda gcmd: None,
            end_probe_session=lambda: None)

    def get_probe_params(self):
        """Return standard fake probe defaults."""
        return probe_params()

    def get_offsets(self):
        """Return fixed probe offsets."""
        return (1.0, 2.0, 1.5)


class FakeProbeEndstopWrapper:
    """Probe endstop wrapper that may nest a usable MCU endstop."""

    def __init__(self, mcu_endstop=None):
        if mcu_endstop is not None:
            self.mcu_endstop = mcu_endstop

    def query_endstop(self, print_time):
        """Expose query support without the full MCU endstop surface."""
        return False


class PrinterObjectCompatTest(unittest.TestCase):
    """Covers object lookup wrapper behavior."""

    def test_lookup_required_objects(self):
        printer = FakePrinter()
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIs(compat.lookup_gcode(), printer.gcode)
        self.assertIs(compat.lookup_gcode_move(), printer.gcode_move)
        self.assertIs(compat.lookup_homing(), printer.homing)
        self.assertIs(compat.lookup_toolhead(), printer.toolhead)
        self.assertIs(compat.lookup_probe(), printer.objects['probe'])

    def test_lookup_optional_objects_returns_none_when_absent(self):
        printer = FakePrinter()
        printer.objects.pop('probe')
        printer.objects.pop('toolhead')
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIsNone(compat.lookup_optional_probe())
        self.assertIsNone(compat.lookup_optional_toolhead())
        self.assertIsNone(compat.lookup_safe_z_home())
        self.assertIsNone(compat.lookup_bed_mesh())

    def test_lookup_optional_toolhead_returns_the_toolhead(self):
        printer = FakePrinter()
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIs(compat.lookup_optional_toolhead(), printer.toolhead)

    def test_lookup_required_probe_keeps_printer_error_behavior(self):
        printer = FakePrinter()
        printer.objects.pop('probe')
        compat = klipper_compat.PrinterObjectCompat(printer)
        with self.assertRaises(KeyError):
            compat.lookup_probe()

    def test_load_startup_objects(self):
        printer = FakePrinter()
        config = FakeConfig(printer)
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIs(compat.load_gcode_macro(config), printer.gcode_macro)
        self.assertIs(compat.load_query_endstops(config),
                      printer.query_endstops)


class RuntimeContractValidatorTest(unittest.TestCase):
    """Covers startup runtime contract validation."""

    def assert_contract_fails(self, printer, probe, topic):
        """Assert that runtime validation fails for a named topic."""
        with self.assertRaisesRegex(FakeError, topic):
            klipper_compat.validate_runtime_contract(
                printer, probe, 'z_calibration')

    def test_modern_probe_runtime_contract_passes(self):
        printer = FakePrinter()
        klipper_compat.validate_runtime_contract(
            printer, printer.objects['probe'], 'z_calibration')

    def test_legacy_multi_probe_runtime_contract_passes(self):
        probe = FakeLegacyProbe()
        probe.mcu_probe = FakeMCUEndstop()
        printer = FakePrinter(probe)
        klipper_compat.validate_runtime_contract(
            printer, probe, 'z_calibration')

    def test_wrapped_legacy_probe_endstop_runtime_contract_passes(self):
        probe = FakeLegacyProbe()
        probe.mcu_probe = FakeProbeEndstopWrapper(FakeMCUEndstop())
        printer = FakePrinter(probe)
        klipper_compat.validate_runtime_contract(
            printer, probe, 'z_calibration')

    def test_old_probe_session_runtime_contract_passes(self):
        probe = FakeOldSessionProbe()
        printer = FakePrinter(probe)
        klipper_compat.validate_runtime_contract(
            printer, probe, 'z_calibration')

    def test_old_probe_default_attributes_pass_runtime_contract(self):
        probe = FakeOldDefaultsProbe()
        printer = FakePrinter(probe)
        # The modern defaults API is absent, so the deprecated attribute
        # shape is the only thing that can satisfy probe_defaults here.
        self.assertFalse(hasattr(probe, 'get_probe_params'))
        self.assertFalse(hasattr(probe, 'get_offsets'))
        klipper_compat.validate_runtime_contract(
            printer, probe, 'z_calibration')

    def test_incomplete_probe_default_attributes_fail_contract(self):
        # Every deprecated attribute is read by ProbeCompat, so a partial
        # legacy shape must not be accepted as the legacy API.
        for attr in ['sample_count', 'samples_tolerance', 'samples_retries',
                     'lift_speed', 'samples_result', 'z_offset']:
            probe = FakeOldDefaultsProbe()
            delattr(probe, attr)
            printer = FakePrinter(probe)
            with self.subTest(attr=attr):
                self.assert_contract_fails(printer, probe, 'probe_defaults')

    def test_failed_object_lookup_fails_runtime_contract(self):
        # A printer without a homing object raises from lookup_object().
        # The validator has to translate that into its named contract
        # instead of leaking the raw lookup error.
        printer = FakePrinter()
        probe = printer.objects['probe']
        printer.objects.pop('homing')
        with self.assertRaises(FakeError) as caught:
            klipper_compat.validate_runtime_contract(
                printer, probe, 'z_calibration')
        message = str(caught.exception)
        self.assertIn('homing_probing_move', message)
        self.assertIn('object lookup failed', message)

    def test_missing_homing_probing_move_fails_runtime_contract(self):
        printer = FakePrinter()
        probe = printer.objects['probe']
        printer.homing.probing_move = None
        self.assert_contract_fails(printer, probe, 'homing_probing_move')

    def test_missing_probe_defaults_fail_runtime_contract(self):
        probe = types.SimpleNamespace(
            start_probe_session=lambda gcmd: None,
            mcu_probe=FakeMCUEndstop())
        printer = FakePrinter(probe)
        self.assert_contract_fails(printer, probe, 'probe_defaults')

    def test_missing_probe_execution_profile_fails_runtime_contract(self):
        probe = types.SimpleNamespace(
            get_probe_params=probe_params,
            get_offsets=lambda: (1.0, 2.0, 1.5),
            mcu_probe=FakeMCUEndstop())
        printer = FakePrinter(probe)
        self.assert_contract_fails(printer, probe,
                                   'probe_execution_profile')

    def test_missing_legacy_probe_endstop_fails_runtime_contract(self):
        probe = FakeLegacyProbe()
        probe.mcu_probe = FakeProbeEndstopWrapper()
        printer = FakePrinter(probe)
        self.assert_contract_fails(printer, probe,
                                   'legacy_probe_mcu_endstop')

    def test_missing_probe_endstop_query_fails_runtime_contract(self):
        probe = FakeProbe()
        probe.mcu_probe = types.SimpleNamespace()
        printer = FakePrinter(probe)
        self.assert_contract_fails(printer, probe, 'probe_endstop_query')

    def test_missing_z_endstop_interface_fails_runtime_contract(self):
        printer = FakePrinter()
        z_endstop = types.SimpleNamespace(get_steppers=lambda: [])
        with self.assertRaisesRegex(FakeError, 'z_endstop_probe_target'):
            klipper_compat.validate_runtime_contract(
                printer, printer.objects['probe'], 'z_calibration',
                z_endstop)

    def test_offset_gcode_runtime_contract_passes(self):
        printer = FakePrinter()
        config = FakeConfig(printer, {'offset_gcode': 'RESPOND MSG=test'})
        offset_gcode = printer.gcode_macro.load_template(config,
                                                         'offset_gcode')
        printer.gcode_move.cmd_SET_GCODE_OFFSET = None
        klipper_compat.validate_runtime_contract(
            printer, printer.objects['probe'], 'z_calibration',
            offset_gcode=offset_gcode)

    def test_error_gcode_runtime_contract_passes(self):
        printer = FakePrinter()
        config = FakeConfig(printer, {'error_gcode': 'RESPOND MSG=test'})
        error_gcode = printer.gcode_macro.load_template(config,
                                                        'error_gcode')
        klipper_compat.validate_runtime_contract(
            printer, printer.objects['probe'], 'z_calibration',
            error_gcode=error_gcode)

    def test_missing_offset_gcode_template_fails_runtime_contract(self):
        printer = FakePrinter()
        offset_gcode = types.SimpleNamespace(
            run_gcode_from_command=lambda context: None)
        with self.assertRaisesRegex(FakeError, 'offset_gcode_template'):
            klipper_compat.validate_runtime_contract(
                printer, printer.objects['probe'], 'z_calibration',
                offset_gcode=offset_gcode)

    def test_missing_error_gcode_template_fails_runtime_contract(self):
        printer = FakePrinter()
        error_gcode = types.SimpleNamespace(
            run_gcode_from_command=lambda context: None)
        with self.assertRaisesRegex(FakeError, 'error_gcode_template'):
            klipper_compat.validate_runtime_contract(
                printer, printer.objects['probe'], 'z_calibration',
                error_gcode=error_gcode)


class EndstopWrapperTest(unittest.TestCase):
    """Covers MCU endstop forwarding used by homing.probing_move()."""

    # The wrapper is what z_calibration hands to homing.probing_move(), so
    # Klipper calls get_steppers(), home_start(), home_wait(), and
    # query_endstop() on it during a real probing move.
    def setUp(self):
        self.endstop = FakeRecordingMCUEndstop()
        self.wrapper = klipper_compat.EndstopWrapper(self.endstop)

    def test_wrapper_keeps_the_wrapped_mcu_endstop(self):
        self.assertIs(self.wrapper.mcu_endstop, self.endstop)

    def test_get_mcu_is_forwarded(self):
        self.assertIs(self.wrapper.get_mcu(), self.endstop.mcu)
        self.assertEqual(self.endstop.calls, [('get_mcu', (), {})])

    def test_add_stepper_is_forwarded(self):
        stepper = object()
        self.assertIs(self.wrapper.add_stepper(stepper),
                      self.endstop.add_stepper_result)
        self.assertEqual(self.endstop.calls,
                         [('add_stepper', (stepper,), {})])

    def test_get_steppers_is_forwarded(self):
        self.assertIs(self.wrapper.get_steppers(), self.endstop.steppers)
        self.assertEqual(self.endstop.calls, [('get_steppers', (), {})])

    def test_home_start_forwards_args_and_kwargs(self):
        result = self.wrapper.home_start(1.0, 2.0, 3.0, triggered=False,
                                         rest_time=0.25)
        self.assertIs(result, self.endstop.home_start_result)
        self.assertEqual(self.endstop.calls,
                         [('home_start', (1.0, 2.0, 3.0),
                           {'triggered': False, 'rest_time': 0.25})])

    def test_home_wait_forwards_args_and_kwargs(self):
        result = self.wrapper.home_wait(4.5, home_end_time=6.5)
        self.assertIs(result, self.endstop.home_wait_result)
        self.assertEqual(self.endstop.calls,
                         [('home_wait', (4.5,),
                           {'home_end_time': 6.5})])

    def test_query_endstop_is_forwarded(self):
        self.assertTrue(self.wrapper.query_endstop(12.5))
        self.assertEqual(self.endstop.calls,
                         [('query_endstop', (12.5,), {})])

    def test_wrapped_z_endstop_forwards_to_the_found_endstop(self):
        printer = FakePrinter()
        endstop = FakeRecordingMCUEndstop()
        printer.query_endstops.endstops = [(endstop, 'z')]
        compat = klipper_compat.HomingCompat(printer)
        z_endstop = compat.get_z_endstop(printer.query_endstops,
                                         'z_calibration')
        self.assertIs(z_endstop.get_steppers(), endstop.steppers)


class HomingCompatZEndstopTest(unittest.TestCase):
    """Covers Z calibration endstop discovery across kinematics."""

    # Klipper registers the Z endstop under the section name of the rail
    # that homes Z. Classic kinematics use '[stepper_z]', generic_cartesian
    # uses a '[carriage z]' section that may also be named freely.
    def setup_carriages(self, printer, z_endstops, z_axis=2):
        """Give the fake toolhead a generic_cartesian Z carriage."""
        x_rail = FakeEndstopRail([(FakeMCUEndstop(), 'carriage x')])
        z_rail = FakeEndstopRail(z_endstops)
        printer.toolhead.kinematics = FakeGenericCartesianKinematics(
            [FakeCarriage(0, x_rail), FakeCarriage(z_axis, z_rail)])
        return z_rail

    def get_z_endstop(self, printer):
        """Run the endstop lookup the way handle_connect() does."""
        compat = klipper_compat.HomingCompat(printer)
        return compat.get_z_endstop(printer.query_endstops, 'z_calibration')

    def test_carriage_z_endstop_is_found(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        self.setup_carriages(printer, [(endstop, 'carriage z')])
        printer.query_endstops.endstops = [(endstop, 'carriage z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_freely_named_z_carriage_is_found(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        self.setup_carriages(printer, [(endstop, 'carriage my_z')])
        printer.query_endstops.endstops = [(endstop, 'carriage my_z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_carriage_endstop_wins_over_a_matching_name(self):
        # An extra carriage can register the name 'z' without being the
        # endstop that homes the Z carriage.
        printer = FakePrinter()
        carriage_endstop = FakeMCUEndstop()
        extra_endstop = FakeMCUEndstop()
        self.setup_carriages(printer, [(carriage_endstop, 'carriage my_z')])
        printer.query_endstops.endstops = [
            (carriage_endstop, 'carriage my_z'),
            (extra_endstop, 'z'),
        ]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop,
                      carriage_endstop)

    def test_first_carriage_endstop_is_used(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        extra_endstop = FakeMCUEndstop()
        self.setup_carriages(printer, [(endstop, 'carriage z'),
                                       (extra_endstop, 'z1')])
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_virtual_carriage_endstop_is_rejected(self):
        printer = FakePrinter()
        self.setup_carriages(printer, [(object(), 'carriage z')])
        with self.assertRaisesRegex(FakeError, 'virtual endstop'):
            self.get_z_endstop(printer)

    def test_carriage_without_endstops_falls_back_to_the_name(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        self.setup_carriages(printer, [])
        printer.query_endstops.endstops = [(endstop, 'stepper_z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_kinematics_without_carriages_uses_the_name(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        printer.query_endstops.endstops = [(endstop, 'stepper_z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_toolhead_without_kinematics_uses_the_name(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        printer.objects['toolhead'] = types.SimpleNamespace()
        printer.query_endstops.endstops = [(endstop, 'z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_missing_toolhead_uses_the_name(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        printer.objects.pop('toolhead')
        printer.query_endstops.endstops = [(endstop, 'z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_carriage_without_the_axis_api_uses_the_name(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        printer.toolhead.kinematics = FakeGenericCartesianKinematics(
            [object()])
        printer.query_endstops.endstops = [(endstop, 'stepper_z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_rail_without_the_endstop_api_uses_the_name(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        printer.toolhead.kinematics = FakeGenericCartesianKinematics(
            [FakeCarriage(2, object())])
        printer.query_endstops.endstops = [(endstop, 'stepper_z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_empty_primary_carriages_uses_the_name(self):
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        printer.toolhead.kinematics = types.SimpleNamespace(
            primary_carriages=None)
        printer.query_endstops.endstops = [(endstop, 'stepper_z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_only_primary_carriages_are_used(self):
        # Extra and dual carriages are not primary carriages, and reading
        # the carriage mapping instead would iterate carriage names.
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        rail = FakeEndstopRail([(FakeMCUEndstop(), 'carriage z')])
        printer.toolhead.kinematics = types.SimpleNamespace(
            carriages={'z': FakeCarriage(2, rail)})
        printer.query_endstops.endstops = [(endstop, 'stepper_z')]
        self.assertIs(self.get_z_endstop(printer).mcu_endstop, endstop)

    def test_missing_z_endstop_reports_the_registered_names(self):
        printer = FakePrinter()
        self.setup_carriages(printer, [(FakeMCUEndstop(), 'carriage x')],
                             z_axis=1)
        printer.query_endstops.endstops = [(FakeMCUEndstop(), 'carriage x'),
                                           (FakeMCUEndstop(), 'carriage y')]
        with self.assertRaisesRegex(
                FakeError,
                r'No z-endstop found for z_calibration'
                r' \(registered endstops: carriage x, carriage y\)'):
            self.get_z_endstop(printer)

    def test_missing_z_endstop_without_any_endstop(self):
        printer = FakePrinter()
        printer.query_endstops.endstops = []
        with self.assertRaisesRegex(FakeError, 'registered endstops: none'):
            self.get_z_endstop(printer)


class HomingCompatRailSettingsTest(unittest.TestCase):
    """Covers Z rail settings read during the home_rails_end event."""

    Z_SETTINGS = {
        'position_endstop': 0.0,
        'homing_speed': 6.0,
        'second_homing_speed': 2.0,
        'homing_retract_dist': 1.0,
        'position_min': -2.0,
    }

    def setUp(self):
        self.compat = klipper_compat.HomingCompat(FakePrinter())
        self.endstop = FakeMCUEndstop()
        self.z_endstop = klipper_compat.EndstopWrapper(self.endstop)

    def test_rail_of_the_calibration_endstop_is_used(self):
        # generic_cartesian homes carriage rails, so the same settings the
        # classic Z rail provides have to be readable from them.
        rail = FakeEndstopRail([(self.endstop, 'carriage z')])
        self.assertEqual(self.compat.get_z_rail_settings(rail,
                                                         self.z_endstop),
                         self.Z_SETTINGS)

    def test_additional_rail_endstops_do_not_hide_the_rail(self):
        # Extra Z steppers and extra carriages register further endstops
        # on the same rail.
        rail = FakeEndstopRail([(FakeMCUEndstop(), 'stepper_z'),
                                (self.endstop, 'z1')])
        self.assertEqual(self.compat.get_z_rail_settings(rail,
                                                         self.z_endstop),
                         self.Z_SETTINGS)

    def test_rail_with_a_foreign_endstop_is_ignored(self):
        # The corexz X rail would answer for Z on the axis test alone and
        # latch the X homing speed and X position_min for probing.
        rail = FakeForeignEndstopRail()
        self.assertTrue(rail.get_steppers()[0].is_active_axis('z'))
        self.assertIsNone(self.compat.get_z_rail_settings(rail,
                                                          self.z_endstop))

    def test_rail_without_endstops_falls_back_to_the_axis_test(self):
        self.assertEqual(
            self.compat.get_z_rail_settings(FakeRail(), self.z_endstop),
            self.Z_SETTINGS)
        self.assertIsNone(
            self.compat.get_z_rail_settings(FakeInactiveRail(),
                                            self.z_endstop))

    def test_without_a_calibration_endstop_the_axis_test_decides(self):
        self.assertIsNotNone(
            self.compat.get_z_rail_settings(FakeForeignEndstopRail()))
        self.assertIsNone(
            self.compat.get_z_rail_settings(FakeInactiveRail()))


class RunGcodeTemplateTest(unittest.TestCase):
    """Covers parameter stringification of G-Code template runs."""

    def test_multiline_value_stays_on_one_line(self):
        template = FakeTemplate()
        klipper_compat.run_gcode_template(template,
                                          {'ERROR': 'first\nsecond\r\nthird'})
        context = template.contexts[0]
        self.assertEqual(context['params']['ERROR'],
                         'first second  third')
        self.assertEqual(context['rawparams'],
                         'ERROR=first second  third')

    def test_single_line_value_is_unchanged(self):
        template = FakeTemplate()
        klipper_compat.run_gcode_template(template, {'Z': 3.5})
        context = template.contexts[0]
        self.assertEqual(context['params']['Z'], '3.5')
        self.assertEqual(context['rawparams'], 'Z=3.5')


if __name__ == '__main__':
    unittest.main()
