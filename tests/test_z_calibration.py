# Unit tests for z_calibration command behavior and calibration flow.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib
import sys
import types
import unittest

from fakes import FakeCarriage, FakeConfig, FakeEmptyProbeSession
from fakes import FakeEndstopRail, FakeError, FakeForeignEndstopRail
from fakes import FakeGcmd, FakeGenericCartesianKinematics
from fakes import FakeKinematics
from fakes import FakeInactiveRail, FakeInactiveStepper, FakeLegacyProbe
from fakes import FakeMCUEndstop, FakeOldProbe, FakePrinter, FakeProbe
from fakes import FakeProbeSession, FakeProbeWithProbeSession, FakeRail
from fakes import FakeStepper, FakeStepperlessMCUEndstop, ProbeResult


sys.modules['mcu'] = types.SimpleNamespace(MCU_endstop=FakeMCUEndstop)
klipper_compat = importlib.import_module('klipper_compat')
z_calibration = importlib.import_module('z_calibration')


def make_helper(values=None, probe=None):
    """Create a connected helper with Z rail settings initialized."""
    printer = FakePrinter(probe)
    helper = make_connected_helper(printer, values)
    helper.handle_home_rails_end(None, [z_rail(printer)])
    return helper, printer


def make_connected_helper(printer, values=None):
    """Create a connected helper that has not homed yet."""
    config = FakeConfig(printer, values)
    helper = z_calibration.ZCalibrationHelper(config)
    helper.handle_connect()
    return helper


def z_rail(printer):
    """Return the rail that registered the fake Z calibration endstop."""
    return FakeEndstopRail(printer.query_endstops.endstops)


def calibration_values(**overrides):
    """Return a complete CALIBRATE_Z configuration with overrides."""
    values = {
        'switch_offset': '0.5',
        'offset_margins': '-10,10',
        'samples': '1',
        'samples_tolerance': '0.5',
        'samples_tolerance_retries': '0',
        'lift_speed': '10',
        'safe_z_height': '5',
        'probing_speed': '6',
        'probing_second_speed': '2',
        'probing_retract_dist': '1',
        'nozzle_xy_position': '10,10',
        'switch_xy_position': '20,20',
        'bed_xy_position': '30,30',
    }
    values.update(overrides)
    return values


class ZCalibrationEndstopPinTest(unittest.TestCase):
    """Covers the plugin-owned calibration endstop on a configured pin."""

    # With 'probe:z_virtual_endstop' the Z rail registers the probe's
    # helper object, which cannot be probed. The plugin then sets up its
    # own endstop on the configured pin and keeps using the rail of the
    # virtual endstop for the homing settings.
    def setUp(self):
        self.printer = FakePrinter()
        # The probe's HomingViaProbeHelper is not an MCU_endstop, which is
        # exactly what makes it unusable as a probing target.
        self.virtual = object()
        self.printer.query_endstops.endstops = [(self.virtual, 'stepper_z')]

    def make_helper(self, pin='PA1', connect=True):
        """Build a helper with endstop_pin configured."""
        config = FakeConfig(self.printer, {'endstop_pin': pin})
        helper = z_calibration.ZCalibrationHelper(config)
        self.printer.run_event_handlers('klippy:mcu_identify')
        if connect:
            helper.handle_connect()
        return helper

    def test_endstop_pin_creates_an_own_endstop(self):
        helper = self.make_helper()
        self.assertEqual(self.printer.pins.setup_calls,
                         [('endstop', 'PA1')])
        self.assertIsNot(helper.z_endstop.mcu_endstop, self.virtual)
        self.assertIs(helper.z_homing_endstop, self.virtual)

    def test_endstop_pin_allows_sharing_the_bare_pin(self):
        # tools_calibrate may already own the same pin. Only the bare name
        # can be passed, because allow_multi_use_pin() parses without
        # invert or pullup support.
        self.make_helper(pin='^!PA1')
        self.assertEqual(self.printer.pins.allowed_multi_use, ['PA1'])
        self.assertEqual(self.printer.pins.setup_calls,
                         [('endstop', '^!PA1')])

    def test_endstop_pin_strips_every_modifier(self):
        # '~' selects the other pullup direction and is as valid as '^'.
        # Leaving it in place made Klipper reject the descriptor with
        # "Invalid pin description" before the endstop was even created.
        for pin in ['~PA1', '~!PA1', '^ !PA1', ' !PA1 ']:
            with self.subTest(pin=pin):
                self.setUp()
                self.make_helper(pin=pin)
                self.assertEqual(self.printer.pins.allowed_multi_use,
                                 ['PA1'])
                self.assertEqual(self.printer.pins.setup_calls,
                                 [('endstop', pin)])

    def test_safe_z_home_is_not_a_nozzle_position_fallback(self):
        # With an endstop_pin the probe homes Z, so home_xy_position is a
        # position over the bed picked for the probe. Probing there finds no
        # trigger and runs down to position_min with the nozzle.
        helper = self.make_helper()
        self.printer.objects['safe_z_home'] = types.SimpleNamespace(
            home_x_pos=7.0, home_y_pos=8.0)
        with self.assertRaisesRegex(FakeError, 'cannot find a nozzle'):
            helper._get_nozzle_site(FakeGcmd())

    def test_nozzle_position_parameter_still_works_with_an_endstop_pin(self):
        helper = self.make_helper()
        gcmd = FakeGcmd(params={'NOZZLE_POSITION': '1,2'})
        self.assertEqual(helper._get_nozzle_site(gcmd), [1.0, 2.0, None])

    def test_endstop_is_registered_under_the_section_name(self):
        # Registering it as 'z' or 'stepper_z' would make the homing
        # endstop lookup find the calibration endstop instead.
        helper = self.make_helper()
        names = [name for _endstop, name
                 in self.printer.query_endstops.endstops]
        self.assertIn('z_calibration', names)
        self.assertIs(helper.z_homing_endstop, self.virtual)

    def test_mcu_identify_attaches_the_z_steppers(self):
        z_stepper = FakeStepper()
        self.printer.toolhead.kinematics = FakeKinematics(
            steppers=[z_stepper, FakeInactiveStepper()])
        helper = self.make_helper()
        self.assertEqual(helper.z_endstop.get_steppers(), [z_stepper])

    def test_startup_fails_without_attached_z_steppers(self):
        # Klipper drops a stepper-less endstop from the homing move, so the
        # probing move would run to position_min without a trigger.
        self.printer.toolhead.kinematics = FakeKinematics(
            steppers=[FakeInactiveStepper()])
        with self.assertRaisesRegex(FakeError, 'z_endstop_steppers'):
            self.make_helper()

    def test_homing_settings_come_from_the_virtual_endstop_rail(self):
        # The rail that homes Z is found by identity against the probe's
        # helper object, so the homing settings still latch and
        # _require_z_homed() keeps working.
        helper = self.make_helper()
        helper.handle_home_rails_end(
            None, [FakeEndstopRail([(self.virtual, 'stepper_z')])])
        self.assertEqual(helper.position_z_endstop, 0.0)
        self.assertEqual(helper.probing_speed, 6.0)
        self.assertEqual(helper.second_speed, 2.0)
        self.assertEqual(helper.retract_dist, 1.0)
        self.assertEqual(helper.position_min, -2.0)
        helper._require_z_homed(FakeGcmd())

    def test_suggestion_names_the_probe_z_offset(self):
        # With a virtual endstop Klipper takes the rail position_endstop
        # from the probe, so the number is right but the knob is the probe
        # z_offset, not a z axis position_endstop that does not exist.
        helper = self.make_helper()
        helper.position_z_endstop = 1.5
        gcmd = FakeGcmd()
        run = z_calibration.CalibrationRun(helper, gcmd)
        run._suggest_endstop_position(0.5)
        self.assertIn('current probe z_offset=1.500', gcmd.responses[0])
        self.assertIn('new probe z_offset=1.000', gcmd.responses[0])

    def test_suggestion_names_no_knob_for_a_routed_probe(self):
        # klipper-toolchanger routes per-tool probes and reports 0.0 as the
        # position_endstop until a tool is picked, so the rail reference is
        # not the probe z_offset and must not be suggested as one.
        helper = self.make_helper()
        helper.position_z_endstop = 0.0
        gcmd = FakeGcmd()
        run = z_calibration.CalibrationRun(helper, gcmd)
        run._suggest_endstop_position(0.5)
        self.assertIn('z homing reference is off by 0.500000',
                      gcmd.responses[0])
        self.assertNotIn('z_offset=', gcmd.responses[0])

    def test_suggestion_survives_a_probe_without_offsets(self):
        helper = self.make_helper()
        helper.position_z_endstop = 1.5
        gcmd = FakeGcmd()
        run = z_calibration.CalibrationRun(helper, gcmd)
        run.probe_compat.probe = object()
        run._suggest_endstop_position(0.5)
        self.assertIn('z homing reference is off by', gcmd.responses[0])

    def test_without_endstop_pin_a_virtual_endstop_is_still_rejected(self):
        config = FakeConfig(self.printer)
        helper = z_calibration.ZCalibrationHelper(config)
        with self.assertRaisesRegex(FakeError, 'virtual endstop'):
            helper.handle_connect()


class ZCalibrationTest(unittest.TestCase):
    """Covers plugin startup, commands, and calibration behavior."""

    def test_load_config_returns_helper(self):
        printer = FakePrinter()
        config = FakeConfig(printer)
        self.assertIsInstance(
            z_calibration.load_config(config),
            z_calibration.ZCalibrationHelper)

    def test_startup_registers_lifecycle_events_and_commands(self):
        # Event names and command names are the public wiring: a typo in
        # either leaves the plugin dead on a real printer while every
        # direct-call test still passes.
        printer = FakePrinter()
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        self.assertIn(helper.handle_connect,
                      printer.handlers.get('klippy:connect', []))
        self.assertIn(helper.handle_home_rails_end,
                      printer.handlers.get('homing:home_rails_end', []))
        for name in ['CALIBRATE_Z', 'PROBE_Z_ACCURACY',
                     'CALCULATE_SWITCH_OFFSET']:
            with self.subTest(command=name):
                command, desc = printer.gcode.commands[name]
                self.assertTrue(callable(command))
                self.assertTrue(desc)

    def test_calibration_runs_through_registered_handlers(self):
        # End to end through the registered events and the registered
        # command, the way klippy drives the plugin.
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        printer = FakePrinter(probe)
        config = FakeConfig(printer, calibration_values())
        helper = z_calibration.ZCalibrationHelper(config)
        printer.run_event_handlers('klippy:connect')
        printer.run_event_handlers('homing:home_rails_end', None,
                                   [z_rail(printer)])
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        command, _desc = printer.gcode.commands['CALIBRATE_Z']
        command(FakeGcmd())
        self.assertAlmostEqual(helper.last_z_offset, 3.5)

    def test_status_reports_last_state(self):
        helper, _printer = make_helper()
        helper.last_state = True
        helper.last_z_offset = 0.123
        self.assertEqual(helper.get_status(0.0),
                         {'last_query': True, 'last_z_offset': 0.123})

    def test_offset_margins_single_value_is_symmetric(self):
        helper, _printer = make_helper({'offset_margins': '0.25'})
        self.assertEqual(helper.offset_margins, [-0.25, 0.25])

    def test_offset_margins_reject_invalid_values(self):
        invalid_values = [
            '-1,0,1', '1,-1', '', 'bad', 'nan,1', '-inf,1', '1,inf']
        for raw in invalid_values:
            with self.subTest(raw=raw):
                printer = FakePrinter()
                config = FakeConfig(printer, {'offset_margins': raw})
                with self.assertRaises(FakeError):
                    z_calibration.ZCalibrationHelper(config)

    def test_float_options_reject_non_finite_values(self):
        # Klipper's own bounds let 'inf' through: it is above every minimum,
        # so it would reach a probing speed, a safe Z height or the depth a
        # probing move drives to. 'position_min' has no bound at all.
        options = ['switch_offset', 'speed', 'safe_z_height',
                   'samples_tolerance', 'lift_speed', 'probing_speed',
                   'probing_second_speed', 'probing_retract_dist',
                   'position_min']
        for option in options:
            for raw in ['inf', '-inf', 'nan']:
                with self.subTest(option=option, raw=raw):
                    printer = FakePrinter()
                    config = FakeConfig(printer, {option: raw})
                    with self.assertRaises(FakeError):
                        z_calibration.ZCalibrationHelper(config)

    def test_float_options_still_accept_finite_values(self):
        printer = FakePrinter()
        config = FakeConfig(printer, {'speed': '42.5', 'position_min': '-2.0'})
        helper = z_calibration.ZCalibrationHelper(config)
        self.assertAlmostEqual(helper.speed, 42.5)
        self.assertAlmostEqual(helper.position_min, -2.0)

    def test_optional_gcode_rejects_blank_value(self):
        for raw in ['', '   ']:
            for option in ['offset_gcode', 'error_gcode']:
                with self.subTest(option=option, raw=raw):
                    printer = FakePrinter()
                    config = FakeConfig(printer, {option: raw})
                    pattern = '%s .* cannot be blank' % (option,)
                    with self.assertRaisesRegex(FakeError, pattern):
                        z_calibration.ZCalibrationHelper(config)

    def test_error_gcode_runs_for_early_calibration_errors(self):
        helper, printer = make_helper({
            'error_gcode': 'RESPOND MSG={params.ERROR}',
        })
        printer.toolhead.homed_axes = 'xy'
        with self.assertRaisesRegex(FakeError, 'must home axes first'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        error_template = printer.gcode_macro.templates['error_gcode']
        self.assertEqual(error_template.calls, 1)
        self.assertIn('must home axes first',
                      error_template.contexts[0]['params']['ERROR'])
        self.assertEqual(printer.gcode_macro.templates['end_gcode'].calls, 0)

    def test_error_gcode_failure_preserves_original_error(self):
        helper, printer = make_helper({
            'error_gcode': 'RESPOND MSG={params.ERROR}',
        })
        error_template = printer.gcode_macro.templates['error_gcode']
        error_template.exception = FakeError('error hook failed')
        printer.toolhead.homed_axes = 'xy'
        with self.assertLogs(level='ERROR') as logs:
            with self.assertRaisesRegex(FakeError, 'must home axes first'):
                helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertEqual(error_template.calls, 1)
        self.assertIn('error_gcode failed', '\n'.join(logs.output))

    def test_gcode_options_load_through_shared_templates(self):
        helper, printer = make_helper({
            'offset_gcode': 'RESPOND MSG=test',
            'error_gcode': 'RESPOND MSG=error',
        })
        self.assertIs(helper.start_gcode,
                      printer.gcode_macro.templates['start_gcode'])
        self.assertIs(helper.switch_gcode,
                      printer.gcode_macro.templates['before_switch_gcode'])
        self.assertIs(helper.end_gcode,
                      printer.gcode_macro.templates['end_gcode'])
        self.assertIs(helper.offset_gcode,
                      printer.gcode_macro.templates['offset_gcode'])
        self.assertIs(helper.error_gcode,
                      printer.gcode_macro.templates['error_gcode'])

    def test_error_gcode_does_not_run_on_calibration_success(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        values = calibration_values(
            error_gcode='RESPOND MSG={params.ERROR}')
        helper, printer = make_helper(values, probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertEqual(
            printer.gcode_macro.templates['error_gcode'].calls, 0)

    def test_error_gcode_runs_after_end_gcode_for_calibration_errors(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(
            offset_margins='-1,1',
            error_gcode='RESPOND MSG={params.ERROR}'), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        with self.assertRaisesRegex(FakeError, 'outside the configured range'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        error_template = printer.gcode_macro.templates['error_gcode']
        self.assertEqual(error_template.calls, 1)
        self.assertIn('outside the configured range',
                      error_template.contexts[0]['params']['ERROR'])
        self.assertEqual(printer.gcode_macro.executions, [
            'start_gcode',
            'before_switch_gcode',
            'end_gcode',
            'error_gcode',
        ])

    def test_end_gcode_runs_when_start_gcode_fails(self):
        # An attach macro can move the toolhead and then abort. Docking is
        # the recovery for that, so end_gcode has to run - the same reason
        # v0.9.2 added it for errors later in the run.
        probe = FakeProbe(offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper({
            'switch_offset': '0.5',
            'nozzle_xy_position': '10,10',
            'switch_xy_position': '20,20',
            'bed_xy_position': '30,30',
            'error_gcode': 'RESPOND MSG={params.ERROR}',
        }, probe)
        start_template = printer.gcode_macro.templates['start_gcode']
        start_template.exception = FakeError("attach failed")
        with self.assertRaisesRegex(FakeError, 'attach failed'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertEqual(printer.gcode_macro.executions, [
            'start_gcode',
            'end_gcode',
            'error_gcode',
        ])
        self.assertFalse(helper.last_state)
        self.assertIsNone(helper.last_z_offset)

    def test_error_gcode_rawparams_contains_error_message(self):
        helper, printer = make_helper({
            'error_gcode': 'RESPOND MSG={rawparams}',
        })
        printer.toolhead.homed_axes = 'xy'
        with self.assertRaisesRegex(FakeError, 'must home axes first'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        error_template = printer.gcode_macro.templates['error_gcode']
        self.assertIn('ERROR=', error_template.contexts[0]['rawparams'])
        self.assertIn('must home axes first',
                      error_template.contexts[0]['rawparams'])

    def test_parse_xy_rejects_malformed_gcode_parameter(self):
        helper, _printer = make_helper()
        gcmd = FakeGcmd(params={'NOZZLE_POSITION': '1,2,3'})
        with self.assertRaisesRegex(FakeError,
                                    'unable to parse NOZZLE_POSITION'):
            helper._parse_xy('NOZZLE_POSITION', '1,2,3', gcmd)

    def test_parse_xy_rejects_non_finite_gcode_parameter(self):
        helper, _printer = make_helper()
        gcmd = FakeGcmd()
        for raw in ['nan,1', '1,inf', '-inf,1']:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(FakeError,
                                            'unable to parse NOZZLE_POSITION'):
                    helper._parse_xy('NOZZLE_POSITION', raw, gcmd)

    def test_parse_xy_rejects_malformed_config_value(self):
        printer = FakePrinter()
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        with self.assertRaisesRegex(FakeError,
                                    'Unable to parse bad_xy_position'):
            helper._parse_xy('bad_xy_position', '1,2,3', config=config)

    def test_parse_xy_without_context_uses_printer_config_error(self):
        helper, _printer = make_helper()
        with self.assertRaisesRegex(FakeError, 'Unable to parse POSITION'):
            helper._parse_xy('POSITION', None)

    def test_handle_connect_requires_probe(self):
        printer = FakePrinter()
        printer.objects.pop('probe')
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        with self.assertRaisesRegex(FakeError, 'A probe is needed'):
            helper.handle_connect()

    def test_handle_connect_requires_z_endstop(self):
        printer = FakePrinter()
        printer.query_endstops.endstops = []
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        with self.assertRaisesRegex(FakeError, 'No z-endstop found'):
            helper.handle_connect()

    def test_handle_connect_finds_generic_cartesian_z_endstop(self):
        # generic_cartesian registers the endstop of the '[carriage z]'
        # section, so startup must not depend on a 'stepper_z' name.
        printer = FakePrinter()
        endstop = FakeMCUEndstop()
        printer.toolhead.kinematics = FakeGenericCartesianKinematics(
            [FakeCarriage(2, FakeEndstopRail([(endstop, 'carriage z')]))])
        printer.query_endstops.endstops = [(endstop, 'carriage z')]
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        helper.handle_connect()
        self.assertIs(helper.z_endstop.mcu_endstop, endstop)

    def test_suggestion_names_the_z_axis_position_endstop(self):
        helper, printer = make_helper()
        helper.position_z_endstop = 2.0
        gcmd = FakeGcmd()
        run = z_calibration.CalibrationRun(helper, gcmd)
        run._suggest_endstop_position(0.5)
        self.assertIn('current z axis position_endstop=2.000',
                      gcmd.responses[0])
        self.assertIn('new z axis position_endstop=1.500', gcmd.responses[0])

    def test_startup_fails_when_the_rail_endstop_has_no_steppers(self):
        # The guard is not specific to a plugin-owned endstop. A rail
        # endstop without steppers would be dropped from the homing move
        # just the same, so the classic path is checked as well.
        printer = FakePrinter()
        printer.query_endstops.endstops = [
            (FakeStepperlessMCUEndstop(), 'stepper_z')]
        with self.assertRaisesRegex(FakeError, 'z_endstop_steppers'):
            make_connected_helper(printer)

    def test_handle_connect_resolves_both_endstop_roles(self):
        # The calibration endstop is wrapped for probing_move(); the homing
        # endstop stays raw because the rail lookup compares it by identity
        # against the objects the rail registered.
        printer = FakePrinter()
        helper = make_connected_helper(printer)
        raw_endstop = printer.query_endstops.endstops[0][0]
        self.assertIs(helper.z_homing_endstop, raw_endstop)
        self.assertIs(helper.z_endstop.mcu_endstop, raw_endstop)

    def test_handle_home_rails_end_reads_the_homing_endstop_rail(self):
        printer = FakePrinter()
        helper = make_connected_helper(printer)
        helper.handle_home_rails_end(None, [z_rail(printer)])
        self.assertEqual(helper.position_z_endstop, 0.0)
        self.assertEqual(helper.probing_speed, 6.0)
        self.assertEqual(helper.second_speed, 2.0)
        self.assertEqual(helper.retract_dist, 1.0)
        self.assertEqual(helper.position_min, -2.0)

    def test_handle_home_rails_end_ignores_a_foreign_endstop_rail(self):
        # A corexz X rail reports its steppers as active on Z. Taking its
        # settings would probe at the X homing speed down to X position_min.
        printer = FakePrinter()
        helper = make_connected_helper(printer)
        helper.handle_home_rails_end(None, [FakeForeignEndstopRail()])
        self.assertIsNone(helper.position_z_endstop)
        self.assertIsNone(helper.probing_speed)
        self.assertIsNone(helper.second_speed)
        self.assertIsNone(helper.retract_dist)
        self.assertIsNone(helper.position_min)

    def test_handle_home_rails_end_keeps_z_settings_across_axes(self):
        # G28 homes X first and the settings latch on first use, so the X
        # rail must not decide them, and homing X again must not overwrite
        # the cached Z endstop position either.
        printer = FakePrinter()
        helper = make_connected_helper(printer)
        helper.handle_home_rails_end(None, [FakeForeignEndstopRail()])
        helper.handle_home_rails_end(None, [z_rail(printer)])
        helper.handle_home_rails_end(None, [FakeForeignEndstopRail()])
        self.assertEqual(helper.probing_speed, 6.0)
        self.assertEqual(helper.second_speed, 2.0)
        self.assertEqual(helper.retract_dist, 1.0)
        self.assertEqual(helper.position_min, -2.0)
        self.assertEqual(helper.position_z_endstop, 0.0)

    def test_handle_connect_rejects_virtual_z_endstop(self):
        printer = FakePrinter()
        printer.query_endstops.endstops = [(object(), 'stepper_z')]
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        with self.assertRaisesRegex(FakeError, 'virtual endstop'):
            helper.handle_connect()

    def test_handle_connect_fails_on_runtime_contract_error(self):
        probe = FakeProbe()
        probe.mcu_probe = types.SimpleNamespace()
        printer = FakePrinter(probe)
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        with self.assertRaisesRegex(FakeError, 'probe_endstop_query'):
            helper.handle_connect()

    def test_handle_connect_enforces_minimum_safe_z_height(self):
        probe = FakeProbe(offsets=(0.0, 0.0, 1.0))
        helper, _printer = make_helper(probe=probe)
        self.assertEqual(helper.safe_z_height, 20)

    def test_handle_connect_warns_about_safe_z_height_override(self):
        printer = FakePrinter()
        config = FakeConfig(printer, {'safe_z_height': '2'})
        helper = z_calibration.ZCalibrationHelper(config)
        with self.assertLogs(level='WARNING') as logs:
            helper.handle_connect()
        self.assertEqual(helper.safe_z_height, 20)
        message = '\n'.join(logs.output)
        self.assertIn(helper.name, message)
        self.assertIn('2.000', message)
        self.assertIn('20.000', message)

    def test_handle_connect_prefers_configured_sampling_values(self):
        # FakeProbe reports samples=1, tolerance=0.1, retries=0,
        # lift_speed=5.0 and samples_result='average'; none of them may
        # overwrite an explicitly configured value.
        helper, _printer = make_helper({
            'samples': '7',
            'samples_tolerance': '0.25',
            'samples_tolerance_retries': '3',
            'lift_speed': '11',
            'samples_result': 'median',
        })
        self.assertEqual(helper.samples, 7)
        self.assertAlmostEqual(helper.tolerance, 0.25)
        self.assertEqual(helper.retries, 3)
        self.assertAlmostEqual(helper.lift_speed, 11.0)
        self.assertEqual(helper.samples_result, 'median')

    def test_handle_connect_reads_missing_sampling_values_from_probe(self):
        helper, _printer = make_helper()
        self.assertEqual(helper.samples, 1)
        self.assertAlmostEqual(helper.tolerance, 0.1)
        self.assertEqual(helper.retries, 0)
        self.assertAlmostEqual(helper.lift_speed, 5.0)
        # 'samples_result: none' means "no explicit choice", which
        # inherits the probe's configured result type.
        self.assertEqual(helper.samples_result, 'average')

    def test_handle_home_rails_end_ignores_non_z_rails(self):
        printer = FakePrinter()
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        helper.handle_home_rails_end(None, [FakeInactiveRail()])
        self.assertIsNone(helper.position_z_endstop)

    def test_handle_home_rails_end_accepts_rails_without_endstops(self):
        # A rail that does not report its endstops keeps the axis test.
        printer = FakePrinter()
        helper = make_connected_helper(printer)
        helper.handle_home_rails_end(None, [FakeRail()])
        self.assertEqual(helper.position_z_endstop, 0.0)
        self.assertEqual(helper.probing_speed, 6.0)

    def test_calculate_switch_offset_requires_calibration_first(self):
        helper, _printer = make_helper({'switch_offset': '0.5'})
        gcmd = FakeGcmd('CALCULATE_SWITCH_OFFSET')
        with self.assertRaisesRegex(FakeError, 'must run CALIBRATE_Z first'):
            helper.cmd_CALCULATE_SWITCH_OFFSET(gcmd)

    def test_calculate_switch_offset_reports_positive_value(self):
        helper, printer = make_helper({'switch_offset': '0.5'})
        helper.last_z_offset = 0.2
        printer.toolhead.position[2] = 0.25
        gcmd = FakeGcmd('CALCULATE_SWITCH_OFFSET')
        helper.cmd_CALCULATE_SWITCH_OFFSET(gcmd)
        self.assertIn('new switch_offset=0.450', gcmd.responses[-1])

    def test_calculate_switch_offset_reports_negative_value(self):
        helper, printer = make_helper({'switch_offset': '0.1'})
        helper.last_z_offset = 0.0
        printer.toolhead.position[2] = 1.0
        gcmd = FakeGcmd('CALCULATE_SWITCH_OFFSET')
        helper.cmd_CALCULATE_SWITCH_OFFSET(gcmd)
        self.assertIn('resulting switch offset is negative', gcmd.responses[-1])

    def test_require_z_homed_checks_current_toolhead_state(self):
        helper, printer = make_helper()
        gcmd = FakeGcmd()
        printer.toolhead.homed_axes = 'xy'
        with self.assertRaisesRegex(FakeError, 'must home axes first'):
            helper._require_z_homed(gcmd)
        printer.toolhead.homed_axes = 'xyz'
        helper._require_z_homed(gcmd)

    def test_require_z_homed_checks_cached_homing_state(self):
        helper, _printer = make_helper()
        helper.position_z_endstop = None
        with self.assertRaisesRegex(FakeError, 'must home axes first'):
            helper._require_z_homed(FakeGcmd())

    def test_safe_z_height_uses_absolute_move(self):
        helper, printer = make_helper({'safe_z_height': '8'})
        printer.toolhead.position = [0.0, 0.0, 3.0, 0.0]
        helper.move_safe_z(4.0)
        self.assertEqual(printer.toolhead.moves[-1], ([None, None, 8.0], 4.0))

    def test_safe_z_height_skips_the_move_when_already_above(self):
        helper, printer = make_helper({'safe_z_height': '8'})
        printer.toolhead.position = [0.0, 0.0, 9.0, 0.0]
        helper.move_safe_z(4.0)
        self.assertEqual(printer.toolhead.moves, [])

    def test_safe_z_height_skips_the_move_at_the_boundary(self):
        helper, printer = make_helper({'safe_z_height': '8'})
        printer.toolhead.position = [0.0, 0.0, 8.0, 0.0]
        helper.move_safe_z(4.0)
        self.assertEqual(printer.toolhead.moves, [])

    def test_position_resolution_paths(self):
        helper, printer = make_helper({
            'switch_xy_offsets': '3,4',
            'switch_offset': '0.5',
        })
        helper.nozzle_site = None
        helper.switch_site = None
        helper.bed_site = None
        printer.objects['safe_z_home'] = types.SimpleNamespace(
            home_x_pos=7.0, home_y_pos=8.0)
        printer.objects['bed_mesh'] = types.SimpleNamespace(
            bmc=types.SimpleNamespace(
                probe_mgr=types.SimpleNamespace(zero_ref_pos=[9.0, 10.0])))
        gcmd = FakeGcmd(params={
            'NOZZLE_POSITION': '1,2',
            'SWITCH_POSITION': '3,4',
            'BED_POSITION': '5,6',
            'SWITCH_OFFSET': '0.75',
        })
        self.assertEqual(helper._get_nozzle_site(gcmd), [1.0, 2.0, None])
        self.assertEqual(helper._get_switch_site(gcmd, [1.0, 2.0, None]),
                         [3.0, 4.0, None])
        self.assertEqual(helper._get_bed_site(gcmd), [5.0, 6.0, None])
        self.assertEqual(helper._get_switch_offset(gcmd), 0.75)

        empty_gcmd = FakeGcmd()
        self.assertEqual(helper._get_nozzle_site(empty_gcmd),
                         [7.0, 8.0, None])
        self.assertEqual(helper._get_switch_site(empty_gcmd,
                                                 [1.0, 2.0, None]),
                         [4.0, 6.0, None])
        self.assertEqual(helper._get_bed_site(empty_gcmd), [9.0, 10.0])

    def test_position_resolution_reports_missing_values(self):
        helper, printer = make_helper()
        helper.nozzle_site = None
        helper.switch_site = None
        helper.switch_xy_offsets = None
        helper.bed_site = None
        helper.switch_offset = None
        printer.objects.pop('bed_mesh', None)
        gcmd = FakeGcmd()
        with self.assertRaisesRegex(FakeError, 'cannot find a nozzle'):
            helper._get_nozzle_site(gcmd)
        with self.assertRaisesRegex(FakeError, 'cannot find a switch position'):
            helper._get_switch_site(gcmd, [0.0, 0.0, None])
        with self.assertRaisesRegex(FakeError, 'cannot find a bed position'):
            helper._get_bed_site(gcmd)
        with self.assertRaises(FakeError) as caught:
            helper._get_bed_site(gcmd)
        self.assertIn('BED_POSITION', str(caught.exception))
        self.assertNotIn('NOZZLE_POSITION', str(caught.exception))
        with self.assertRaisesRegex(FakeError, 'cannot find a switch offset'):
            helper._get_switch_offset(gcmd)

    def test_probe_moves_retracts_and_wiggles(self):
        helper, printer = make_helper({
            'wiggle_xy_offsets': '0.5,-0.5',
            'probing_retract_dist': '1',
            'lift_speed': '4',
            'speed': '20',
        })
        printer.homing.results = [[5.0, 6.0, 1.0]]
        pos = helper.probe_endstop(FakeGcmd(), helper.z_endstop, -2.0, 3.0,
                            wiggle=True)
        self.assertEqual(pos, [5.0, 6.0, 1.0])
        self.assertEqual(printer.toolhead.moves[-3:],
                         [([None, None, 2.0], 4.0),
                          ([5.5, 5.5, None], 20.0),
                          ([5.0, 6.0, None], 20.0)])

    def test_probe_z_accuracy_reports_statistics(self):
        helper, printer = make_helper({
            'nozzle_xy_position': '1,2',
            'samples': '3',
            'safe_z_height': '12',
            'probing_retract_dist': '0.5',
            'lift_speed': '4',
            'probing_second_speed': '2',
        })
        printer.homing.results = [
            [1.0, 2.0, 0.1],
            [1.0, 2.0, 0.3],
            [1.0, 2.0, 0.2],
        ]
        gcmd = FakeGcmd('PROBE_Z_ACCURACY')
        helper.cmd_PROBE_Z_ACCURACY(gcmd)
        self.assertIn('maximum 0.300000', gcmd.responses[-1])
        self.assertIn('minimum 0.100000', gcmd.responses[-1])
        self.assertIn('range 0.200000', gcmd.responses[-1])
        self.assertIn('average 0.200000', gcmd.responses[-1])
        self.assertIn('median 0.200000', gcmd.responses[-1])
        self.assertIn('standard deviation 0.081650', gcmd.responses[-1])

    def test_probe_z_accuracy_accepts_parameter_overrides(self):
        helper, printer = make_helper({
            'nozzle_xy_position': '1,2',
            'samples': '3',
            'safe_z_height': '12',
            'probing_retract_dist': '0.5',
            'lift_speed': '4',
            'probing_second_speed': '2',
        })
        printer.homing.results = [
            [1.0, 2.0, 0.1],
            [1.0, 2.0, 0.2],
        ]
        gcmd = FakeGcmd('PROBE_Z_ACCURACY', params={
            'PROBE_SPEED': '9',
            'LIFT_SPEED': '6',
            'SAMPLES': '2',
            'SAMPLE_RETRACT_DIST': '1.5',
        })
        helper.cmd_PROBE_Z_ACCURACY(gcmd)
        self.assertEqual([call[2] for call in printer.homing.calls],
                         [9.0, 9.0])
        # Retracts between the samples: trigger z plus the override.
        self.assertIn(([None, None, 1.6], 6.0), printer.toolhead.moves)
        self.assertIn(([None, None, 1.7], 6.0), printer.toolhead.moves)

    def test_probe_z_accuracy_rejects_non_positive_parameters(self):
        helper, _printer = make_helper({'nozzle_xy_position': '1,2'})
        for name in ['PROBE_SPEED', 'LIFT_SPEED', 'SAMPLE_RETRACT_DIST',
                     'SAMPLES']:
            with self.subTest(param=name):
                gcmd = FakeGcmd('PROBE_Z_ACCURACY', params={name: '0'})
                with self.assertRaises(FakeError):
                    helper.cmd_PROBE_Z_ACCURACY(gcmd)

    def test_calc_median_handles_even_and_odd_samples(self):
        helper, _printer = make_helper()
        self.assertEqual(helper.calc_median([[0, 0, 1], [0, 0, 3]])[2], 2.0)
        self.assertEqual(
            helper.calc_median([[0, 0, 3], [0, 0, 1], [0, 0, 2]])[2],
            2)

    def test_calibration_uses_probe_session_test_z_not_bed_z(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        values = calibration_values()
        helper, printer = make_helper(values, probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertAlmostEqual(helper.last_z_offset, 3.5)
        self.assertEqual(printer.gcode_move.offset_commands[0], {'Z': 0.0})
        self.assertAlmostEqual(
            printer.gcode_move.offset_commands[1]['Z_ADJUST'], 3.5)
        self.assertEqual(session.run_gcmds[0].params['PROBE_SPEED'], '2.0')
        self.assertTrue(session.ended)

    def test_calibration_runs_offset_gcode_when_configured(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        values = calibration_values(
            offset_gcode='SET_GCODE_OFFSET Z_ADJUST={params.Z|float}')
        helper, printer = make_helper(values, probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        offset_template = printer.gcode_macro.templates['offset_gcode']
        self.assertAlmostEqual(helper.last_z_offset, 3.5)
        self.assertEqual(printer.gcode_move.offset_commands, [])
        self.assertEqual(offset_template.calls, 1)
        self.assertEqual(offset_template.contexts[0]['params']['Z'], '3.5')
        self.assertEqual(offset_template.contexts[0]['rawparams'], 'Z=3.5')
        self.assertEqual(offset_template.contexts[0]['printer'], 'fake')

    def test_calibration_probes_the_bed_at_the_probe_offset_site(self):
        # The bed is probed with the probe, not the nozzle, so the XY site
        # must be shifted against the probe offsets: bed_site - offsets.
        # With offsets (1, 2) and bed_xy_position 30,30 that is 29,28.
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertIn(([29.0, 28.0, None], helper.speed),
                      printer.toolhead.moves)
        self.assertNotIn(([31.0, 32.0, None], helper.speed),
                         printer.toolhead.moves)

    def test_calibration_checks_probe_attachment_at_the_switch(self):
        # The nozzle probes without the probe attached, so the trigger
        # state is ignored there; the switch probe is the first point
        # where a missing probe has to stop the run.
        probe = FakeProbe(session=FakeProbeSession([]))
        probe.mcu_probe.triggered = True
        helper, printer = make_helper(calibration_values(), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
        ]
        with self.assertRaisesRegex(FakeError, 'probe switch not closed'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        # Only the nozzle sample ran; the switch was never probed.
        self.assertEqual(len(printer.homing.calls), 1)
        self.assertTrue(probe.session.ended)
        self.assertEqual(printer.gcode_macro.executions[-1], 'end_gcode')

    def test_calibration_approaches_the_nozzle_site_x_first(self):
        # The nozzle approach moves X alone first: a diagonal move could
        # drag the toolhead through the dock on the way to the endstop.
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(), probe)
        printer.toolhead.position = [3.0, 4.0, 10.0, 0.0]
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertEqual(printer.toolhead.moves[0],
                         ([10.0, 4.0, None], 50.0))
        self.assertEqual(printer.toolhead.moves[1],
                         ([10.0, 10.0, None], 50.0))

    def test_calibration_wiggles_after_the_nozzle_probe(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(
            calibration_values(wiggle_xy_offsets='0.5,-0.5'), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        moves = printer.toolhead.moves
        # One wiggle around the nozzle probe, none at the switch probe.
        self.assertEqual(moves.count(([10.5, 9.5, None], 50.0)), 1)
        self.assertEqual(moves.count(([20.5, 19.5, None], 50.0)), 0)

    def test_failed_calibration_resets_last_query(self):
        # Mainsail/Fluidd read last_query through get_status, so a failed
        # run has to reset it even after an earlier success.
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertTrue(helper.last_state)
        printer.toolhead.homed_axes = 'xy'
        with self.assertRaisesRegex(FakeError, 'must home axes first'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertEqual(helper.get_status(0.0),
                         {'last_query': False, 'last_z_offset': 3.5})

    def test_calibration_falls_back_when_the_session_cannot_probe(self):
        # A modern probe can open a session whose object does not run
        # probes itself; the bed is then probed through the legacy MCU
        # endstop path while the session stays open around it.

        class SessionWithoutRunProbe:

            def __init__(self):
                self.ended = False

            def end_probe_session(self):
                self.ended = True

        session = SessionWithoutRunProbe()
        probe = FakeProbe(session=session)
        probe.mcu_probe = FakeMCUEndstop()
        helper, printer = make_helper(calibration_values(), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
            [29.0, 28.0, 5.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertAlmostEqual(helper.last_z_offset, 3.5)
        self.assertTrue(session.ended)

    def test_calibration_uses_legacy_probe_endstop_path(self):
        probe = FakeLegacyProbe()
        probe.mcu_probe = FakeMCUEndstop()
        values = calibration_values()
        helper, printer = make_helper(values, probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
            [29.0, 28.0, 5.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertAlmostEqual(helper.last_z_offset, 3.5)
        self.assertEqual(probe.begin_calls, 1)
        self.assertEqual(probe.end_calls, 1)

    def test_calibration_unwraps_legacy_probe_endstop_wrapper(self):
        raw_endstop = FakeMCUEndstop()
        wrapper = types.SimpleNamespace(
            query_endstop=lambda print_time: False,
            mcu_endstop=raw_endstop)
        probe = FakeLegacyProbe()
        probe.mcu_probe = wrapper
        values = calibration_values()
        helper, printer = make_helper(values, probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
            [29.0, 28.0, 5.0],
        ]
        helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertIs(printer.homing.calls[-1][0], raw_endstop)
        self.assertAlmostEqual(helper.last_z_offset, 3.5)

    def test_calibration_rejects_missing_legacy_probe_endstop(self):
        probe = FakeLegacyProbe()
        probe.mcu_probe = None
        with self.assertRaisesRegex(FakeError, 'legacy_probe_mcu_endstop'):
            make_helper(calibration_values(), probe)

    def test_calibration_requires_legacy_probe_mcu_endstop(self):
        probe = FakeLegacyProbe()
        probe.mcu_probe = FakeMCUEndstop()
        helper, printer = make_helper(calibration_values(), probe)
        # A probe endstop wrapper that only survives startup validation:
        # it exposes neither the MCU endstop surface nor a nested one, so
        # the legacy probing_move() fallback has nothing to probe with.
        probe.mcu_probe = types.SimpleNamespace(
            query_endstop=lambda print_time: False)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        with self.assertRaisesRegex(FakeError,
                                    'does not expose an MCU endstop'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertFalse(helper.last_state)
        self.assertIsNone(helper.last_z_offset)
        # The probe session is still ended for the failed run.
        self.assertEqual(probe.end_calls, 1)

    def test_probe_session_end_failure_is_logged_but_not_fatal(self):
        session = FakeProbeSession(
            [ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0)],
            end_exception=FakeError('probe session end failed'))
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        with self.assertLogs(level='ERROR') as logs:
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        message = '\n'.join(logs.output)
        self.assertIn('Multi-probe end', message)
        self.assertIn('probe session end failed', message)
        self.assertTrue(session.ended)
        self.assertTrue(helper.last_state)
        self.assertAlmostEqual(helper.last_z_offset, 3.5)
        self.assertAlmostEqual(
            printer.gcode_move.offset_commands[1]['Z_ADJUST'], 3.5)

    def test_probe_session_end_failure_preserves_original_error(self):
        session = FakeProbeSession(
            [ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0)],
            end_exception=FakeError('probe session end failed'))
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(
            samples='2', samples_tolerance='0.01'), probe)
        # The switch samples exceed the tolerance, so the calibration fails
        # inside the probe session and the session end fails on top of it.
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
            [20.0, 20.0, 3.0],
        ]
        with self.assertLogs(level='ERROR') as logs:
            with self.assertRaises(FakeError) as caught:
                helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertIn('probe samples exceed tolerance', str(caught.exception))
        self.assertNotIn('probe session end failed', str(caught.exception))
        self.assertIn('Multi-probe end', '\n'.join(logs.output))
        self.assertTrue(session.ended)
        self.assertFalse(helper.last_state)
        self.assertIsNone(helper.last_z_offset)

    def test_calibration_rejects_offset_outside_margins(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(
            offset_margins='-1,1'), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        with self.assertRaisesRegex(FakeError, 'outside the configured range'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        self.assertFalse(printer.gcode_move.offset_commands)

    def test_calibration_rejects_offset_before_running_offset_gcode(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper(calibration_values(
            offset_margins='-1,1',
            offset_gcode='SET_GCODE_OFFSET Z_ADJUST={params.Z|float}'), probe)
        printer.homing.results = [
            [10.0, 10.0, 1.0],
            [20.0, 20.0, 2.0],
        ]
        with self.assertRaisesRegex(FakeError, 'outside the configured range'):
            helper.cmd_CALIBRATE_Z(FakeGcmd())
        offset_template = printer.gcode_macro.templates['offset_gcode']
        self.assertFalse(printer.gcode_move.offset_commands)
        self.assertEqual(offset_template.calls, 0)

    def test_probe_on_site_retries_and_uses_median(self):
        helper, printer = make_helper({
            'samples': '2',
            'samples_result': 'median',
            'samples_tolerance': '0.1',
            'samples_tolerance_retries': '1',
            'probing_second_speed': '2',
            'probing_retract_dist': '0.5',
        })
        printer.homing.results = [
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.5],
            [0.0, 0.0, 2.0],
            [0.0, 0.0, 2.05],
        ]
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        result = run._probe_on_site(helper.z_endstop, [0.0, 0.0, None])
        self.assertAlmostEqual(result, 2.025)

    def test_probe_on_site_rejects_samples_outside_tolerance(self):
        helper, printer = make_helper({
            'samples': '2',
            'samples_tolerance': '0.1',
            'samples_tolerance_retries': '0',
            'probing_second_speed': '2',
        })
        printer.homing.results = [
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.5],
        ]
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        with self.assertRaisesRegex(FakeError, 'samples exceed tolerance'):
            run._probe_on_site(helper.z_endstop, [0.0, 0.0, None])

    def test_probe_on_site_first_fast_probes_before_the_samples(self):
        helper, printer = make_helper({
            'probing_first_fast': 'true',
            'probing_speed': '10',
            'probing_second_speed': '2',
            'samples': '2',
            'samples_tolerance': '0.5',
            'samples_tolerance_retries': '0',
            'probing_retract_dist': '0.5',
        })
        printer.homing.results = [
            [0.0, 0.0, 5.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.2],
        ]
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        result = run._probe_on_site(helper.z_endstop, [0.0, 0.0, None])
        # The fast probe comes first and only gets the nozzle down quickly;
        # the tolerance samples follow with the second probing speed.
        self.assertEqual([call[2] for call in printer.homing.calls],
                         [10.0, 2.0, 2.0])
        for call in printer.homing.calls:
            self.assertIs(call[0], helper.z_endstop)
            self.assertEqual(call[1][2], helper.position_min)
        # The fast sample must not contribute to the calculated result.
        self.assertAlmostEqual(result, 1.1)

    def test_probe_on_site_without_first_fast_skips_the_fast_probe(self):
        helper, printer = make_helper({
            'probing_speed': '10',
            'probing_second_speed': '2',
            'samples': '2',
            'samples_tolerance': '0.5',
            'samples_tolerance_retries': '0',
            'probing_retract_dist': '0.5',
        })
        printer.homing.results = [
            [0.0, 0.0, 1.0],
            [0.0, 0.0, 1.2],
        ]
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        result = run._probe_on_site(helper.z_endstop, [0.0, 0.0, None])
        self.assertEqual([call[2] for call in printer.homing.calls],
                         [2.0, 2.0])
        self.assertAlmostEqual(result, 1.1)

    def test_probe_bed_first_fast_runs_single_sample_probe(self):
        session = FakeProbeSession([
            ProbeResult(0.0, 0.0, 0.0, 1.0, 2.0, 3.0),
            ProbeResult(0.0, 0.0, 0.0, 1.0, 2.0, 4.0),
        ])
        probe = FakeProbe(session=session)
        helper, _printer = make_helper({
            'probing_first_fast': 'true',
            'probing_speed': '10',
            'probing_second_speed': '2',
        }, probe)
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        run.probe_compat.start()
        self.assertEqual(run._probe_bed_on_site([1.0, 2.0, None]), 4.0)
        self.assertEqual(session.run_gcmds[0].params['SAMPLES'], '1')
        self.assertEqual(session.run_gcmds[1].params['PROBE_SPEED'], '2.0')

    BED_RETRACT_VALUES = {
        'switch_offset': '0.5',
        'samples': '1',
        'samples_tolerance': '0.5',
        'samples_tolerance_retries': '0',
        'probing_second_speed': '2',
        'probing_retract_dist': '1.5',
        'lift_speed': '9',
        'safe_z_height': '5',
    }

    def test_both_bed_probing_paths_end_at_the_same_height(self):
        # The session path and the legacy fallback have to leave the toolhead
        # in the same place, or end_gcode starts from a different height
        # depending on the firmware.
        session_printer = FakePrinter()
        session = FakeProbeSession(
            [ProbeResult(0.0, 0.0, 0.0, 1.0, 2.0, 4.0)],
            toolhead=session_printer.toolhead)
        session_printer.objects['probe'] = FakeProbe(session=session)
        helper = make_connected_helper(session_printer,
                                       self.BED_RETRACT_VALUES)
        helper.handle_home_rails_end(None, [z_rail(session_printer)])
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        run.probe_compat.start()
        run._probe_bed_on_site([1.0, 2.0, None])
        session_z = session_printer.toolhead.position[2]

        legacy_probe = FakeLegacyProbe()
        legacy_probe.mcu_probe = FakeMCUEndstop()
        legacy_printer = FakePrinter(legacy_probe)
        helper = make_connected_helper(legacy_printer,
                                       self.BED_RETRACT_VALUES)
        helper.handle_home_rails_end(None, [z_rail(legacy_printer)])
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        run.probe_compat.start()
        legacy_printer.homing.results = [[1.0, 2.0, 4.0]]
        run._probe_on_site(run.probe_compat.get_legacy_probe_endstop(),
                           [1.0, 2.0, None], check_probe=True)
        legacy_z = legacy_printer.toolhead.position[2]

        # Trigger at 4.0 plus probing_retract_dist on both paths.
        self.assertEqual(session_z, 5.5)
        self.assertEqual(legacy_z, session_z)

    def test_probe_bed_first_fast_retracts_before_the_samples(self):
        # Klipper's session retracts between its own samples but not after
        # the last one. Without a retract here the slow probe would start on
        # the trigger point of the fast one, with the probe still pressed.
        printer = FakePrinter()
        session = FakeProbeSession([
            ProbeResult(0.0, 0.0, 0.0, 1.0, 2.0, 3.0),
            ProbeResult(0.0, 0.0, 0.0, 1.0, 2.0, 4.0),
        ], toolhead=printer.toolhead)
        printer.objects['probe'] = FakeProbe(session=session)
        helper = make_connected_helper(printer, {
            'probing_first_fast': 'true',
            'probing_speed': '10',
            'probing_second_speed': '2',
            'probing_retract_dist': '1.5',
            'lift_speed': '9',
        })
        helper.handle_home_rails_end(None, [z_rail(printer)])
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        run.probe_compat.start()
        run._probe_bed_on_site([1.0, 2.0, None])
        # The fast probe triggered at 3.0, so the slow one has to start
        # above it, not on it.
        self.assertEqual(session.start_positions[1], 4.5)
        self.assertIn(([None, None, 4.5], 9.0), printer.toolhead.moves)

    def test_check_probe_attached_rejects_triggered_probe(self):
        probe = FakeProbe()
        probe.mcu_probe.triggered = True
        helper, _printer = make_helper(probe=probe)
        run = z_calibration.CalibrationRun(helper, FakeGcmd())
        with self.assertRaisesRegex(FakeError, 'probe switch not closed'):
            run._check_probe_attached()

    def test_probe_session_adapter_extracts_tuple_test_z(self):
        helper, _printer = make_helper()
        adapter = klipper_compat.ProbeCompat(
            helper, helper.objects_compat.lookup_probe(), FakeGcmd())
        result = ProbeResult(1.0, 2.0, 99.0, 3.0, 4.0, 5.0)
        self.assertEqual(adapter.get_test_position(result), [3.0, 4.0, 5.0])

    def test_legacy_probe_endstop_unwraps_nested_mcu_endstop(self):
        raw_endstop = FakeMCUEndstop()
        wrapper = types.SimpleNamespace(mcu_endstop=raw_endstop)
        probe = FakeProbe()
        probe.mcu_probe = wrapper
        helper, _printer = make_helper(probe=probe)
        adapter = klipper_compat.ProbeCompat(helper, probe, FakeGcmd())
        self.assertIs(adapter.get_legacy_probe_endstop(), raw_endstop)

    def test_legacy_probe_endstop_matches_what_startup_validated(self):
        # A wrapper that has get_steppers() but is still not a probing
        # target. The startup contract resolves past it to the nested MCU
        # endstop, so the probing move has to use that same object; picking
        # the wrapper here would fail later at home_start().
        raw_endstop = FakeMCUEndstop()
        wrapper = types.SimpleNamespace(
            get_steppers=lambda: [],
            query_endstop=lambda print_time: False,
            mcu_endstop=raw_endstop)
        probe = FakeProbe()
        probe.mcu_probe = wrapper
        helper, _printer = make_helper(probe=probe)
        adapter = klipper_compat.ProbeCompat(helper, probe, FakeGcmd())
        self.assertIs(adapter.get_legacy_probe_endstop(), raw_endstop)
        self.assertIs(
            klipper_compat._resolve_legacy_probe_endstop(probe), raw_endstop)

    def test_probe_compat_uses_legacy_multi_probe_fallback(self):
        helper, _printer = make_helper()
        probe = FakeLegacyProbe()
        adapter = klipper_compat.ProbeCompat(helper, probe, FakeGcmd())
        adapter.start()
        adapter.end()
        self.assertEqual(probe.begin_calls, 1)
        self.assertEqual(probe.end_calls, 1)

    def test_probe_compat_reads_legacy_probe_defaults(self):
        helper, _printer = make_helper()
        defaults = klipper_compat.ProbeCompat(
            helper, FakeOldProbe(), FakeGcmd()).get_config_defaults()
        self.assertEqual(defaults['samples'], 2)
        self.assertEqual(defaults['samples_result'], 'median')
        self.assertEqual(defaults['safe_z_height'], 8.0)

    def test_probe_compat_uses_probe_session_attribute_fallback(self):
        helper, _printer = make_helper()
        probe = FakeProbeWithProbeSession()
        adapter = klipper_compat.ProbeCompat(helper, probe, FakeGcmd())
        adapter.start()
        adapter.end()
        self.assertTrue(probe.probe_session.ended)

    def test_probe_compat_reports_unsupported_endstop_query(self):
        helper, _printer = make_helper()
        probe = types.SimpleNamespace(mcu_probe=types.SimpleNamespace())
        adapter = klipper_compat.ProbeCompat(helper, probe, FakeGcmd())
        with self.assertRaisesRegex(FakeError, 'does not support'):
            adapter.query_endstop(1.0)

    def test_probe_compat_reports_empty_probe_result(self):
        helper, _printer = make_helper()
        probe = FakeProbe(session=FakeEmptyProbeSession())
        adapter = klipper_compat.ProbeCompat(helper, probe, FakeGcmd())
        adapter.start()
        with self.assertRaisesRegex(FakeError, 'did not return a result'):
            adapter.run_probe(1.0)

    def test_probe_compat_returns_none_without_session_probe(self):
        helper, _printer = make_helper()
        adapter = klipper_compat.ProbeCompat(
            helper, FakeLegacyProbe(), FakeGcmd())
        self.assertIsNone(adapter.run_probe(1.0))

    def test_probe_compat_extracts_short_probe_tuple(self):
        helper, _printer = make_helper()
        adapter = klipper_compat.ProbeCompat(
            helper, helper.objects_compat.lookup_probe(), FakeGcmd())
        self.assertEqual(adapter.get_test_position([1.0, 2.0, 3.0]),
                         [1.0, 2.0, 3.0])

    def test_probe_compat_extracts_legacy_six_tuple(self):
        # Legacy Klipper returned a plain 6-tuple without a test_z attribute:
        # indexes 0-2 are the bed position and 3-5 the raw trigger position.
        helper, _printer = make_helper()
        adapter = klipper_compat.ProbeCompat(
            helper, helper.objects_compat.lookup_probe(), FakeGcmd())
        probe_result = (1.0, 2.0, 99.0, 3.0, 4.0, 5.0)
        self.assertFalse(hasattr(probe_result, 'test_z'))
        self.assertEqual(adapter.get_test_position(probe_result),
                         [3.0, 4.0, 5.0])
        self.assertEqual(adapter.get_test_position(list(probe_result)),
                         [3.0, 4.0, 5.0])

    def test_probe_compat_creates_gcmd_without_parameter_snapshot(self):
        helper, _printer = make_helper({'samples_result': 'none'})

        class MinimalGcmd:
            def get_command(self):
                return 'CALIBRATE_Z'

            def error(self, message):
                return FakeError(message)

        probe = FakeProbe(session=FakeProbeSession([
            ProbeResult(0.0, 0.0, 0.0, 1.0, 2.0, 3.0),
        ]))
        adapter = klipper_compat.ProbeCompat(helper, probe, MinimalGcmd())
        adapter.start()
        adapter.run_probe(3.0)
        self.assertEqual(probe.session.run_gcmds[0].params['SAMPLES_RESULT'],
                         'average')

    def test_legacy_probe_endstop_reports_missing_or_direct_endstop(self):
        helper, _printer = make_helper()
        missing = types.SimpleNamespace(mcu_probe=None)
        direct = types.SimpleNamespace(mcu_probe=FakeMCUEndstop())
        self.assertIsNone(klipper_compat.ProbeCompat(
            helper, missing, FakeGcmd()).get_legacy_probe_endstop())
        self.assertIs(klipper_compat.ProbeCompat(
            helper, direct, FakeGcmd()).get_legacy_probe_endstop(),
            direct.mcu_probe)

    def test_bed_mesh_compat_reads_zero_reference_paths(self):
        compat = klipper_compat.BedMeshCompat()
        modern = types.SimpleNamespace(
            bmc=types.SimpleNamespace(
                probe_mgr=types.SimpleNamespace(zero_ref_pos=[1.0, 2.0])))
        direct = types.SimpleNamespace(
            bmc=types.SimpleNamespace(zero_ref_pos=[3.0, 4.0]))
        rri = types.SimpleNamespace(
            bmc=types.SimpleNamespace(relative_reference_index=1,
                                      points=[[0.0, 0.0], [5.0, 6.0]]))
        self.assertEqual(compat.get_zero_reference_position(modern),
                         [1.0, 2.0])
        self.assertEqual(compat.get_zero_reference_position(direct),
                         [3.0, 4.0])
        self.assertEqual(compat.get_zero_reference_position(rri), [5.0, 6.0])

    def test_bed_mesh_compat_handles_missing_reference_paths(self):
        compat = klipper_compat.BedMeshCompat()
        self.assertIsNone(compat.get_zero_reference_position(None))
        self.assertIsNone(compat.get_zero_reference_position(
            types.SimpleNamespace()))
        self.assertIsNone(compat.get_zero_reference_position(
            types.SimpleNamespace(bmc=types.SimpleNamespace())))


if __name__ == '__main__':
    unittest.main()
