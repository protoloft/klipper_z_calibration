# Unit tests for Klipper/Kalico compatibility wrappers and runtime contracts.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib
import sys
import types
import unittest

from fakes import FakeConfig, FakeError, FakeLegacyProbe, FakeMCUEndstop
from fakes import FakePrinter, FakeProbe


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
        compat = klipper_compat.PrinterObjectCompat(printer)
        self.assertIsNone(compat.lookup_optional_probe())
        self.assertIsNone(compat.lookup_safe_z_home())
        self.assertIsNone(compat.lookup_bed_mesh())

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


if __name__ == '__main__':
    unittest.main()
