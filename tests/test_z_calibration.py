# Unit tests for z_calibration command behavior and calibration flow.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib
import sys
import types
import unittest

from fakes import FakeConfig, FakeEmptyProbeSession, FakeError
from fakes import FakeGcmd, FakeInactiveRail, FakeLegacyProbe
from fakes import FakeMCUEndstop, FakeOldProbe, FakePrinter
from fakes import FakeProbe, FakeProbeSession, FakeProbeWithProbeSession
from fakes import FakeRail, ProbeResult


sys.modules['mcu'] = types.SimpleNamespace(MCU_endstop=FakeMCUEndstop)
klipper_compat = importlib.import_module('klipper_compat')
z_calibration = importlib.import_module('z_calibration')


def make_helper(values=None, probe=None):
    """Create a connected helper with Z rail settings initialized."""
    printer = FakePrinter(probe)
    config = FakeConfig(printer, values)
    helper = z_calibration.ZCalibrationHelper(config)
    helper.handle_connect()
    helper.handle_home_rails_end(None, [FakeRail()])
    return helper, printer


class ZCalibrationTest(unittest.TestCase):
    """Covers plugin startup, commands, and calibration behavior."""

    def test_load_config_returns_helper(self):
        printer = FakePrinter()
        config = FakeConfig(printer)
        self.assertIsInstance(
            z_calibration.load_config(config),
            z_calibration.ZCalibrationHelper)

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
            'error_gcode': 'RESPOND MSG={params.ERROR}',
        }
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
        helper, printer = make_helper({
            'switch_offset': '0.5',
            'offset_margins': '-1,1',
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
            'error_gcode': 'RESPOND MSG={params.ERROR}',
        }, probe)
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
        gcmd = FakeGcmd(params={'NOZZLE_POSITION': 'nan,1'})
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

    def test_handle_home_rails_end_ignores_non_z_rails(self):
        printer = FakePrinter()
        config = FakeConfig(printer)
        helper = z_calibration.ZCalibrationHelper(config)
        helper.handle_home_rails_end(None, [FakeInactiveRail()])
        self.assertIsNone(helper.z_homing)

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
        helper.z_homing = None
        with self.assertRaisesRegex(FakeError, 'must home axes first'):
            helper._require_z_homed(FakeGcmd())

    def test_safe_z_height_uses_absolute_move(self):
        helper, printer = make_helper({'safe_z_height': '8'})
        helper._move_safe_z([0.0, 0.0, 3.0, 0.0], 4.0)
        self.assertEqual(printer.toolhead.moves[-1], ([None, None, 8.0], 4.0))

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
        pos = helper._probe(FakeGcmd(), helper.z_endstop, -2.0, 3.0,
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
        self.assertIn('median 0.200000', gcmd.responses[-1])

    def test_calc_median_handles_even_and_odd_samples(self):
        helper, _printer = make_helper()
        self.assertEqual(helper._calc_median([[0, 0, 1], [0, 0, 3]])[2], 2.0)
        self.assertEqual(
            helper._calc_median([[0, 0, 3], [0, 0, 1], [0, 0, 2]])[2],
            2)

    def test_calibration_uses_probe_session_test_z_not_bed_z(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
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
            'offset_gcode': 'SET_GCODE_OFFSET Z_ADJUST={params.Z|float}',
        }
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

    def test_calibration_uses_legacy_probe_endstop_path(self):
        probe = FakeLegacyProbe()
        probe.mcu_probe = FakeMCUEndstop()
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
            make_helper({
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
            }, probe)

    def test_calibration_rejects_offset_outside_margins(self):
        session = FakeProbeSession([
            ProbeResult(30.0, 30.0, 123.0, 29.0, 28.0, 5.0),
        ])
        probe = FakeProbe(session=session, offsets=(1.0, 2.0, 1.5))
        helper, printer = make_helper({
            'switch_offset': '0.5',
            'offset_margins': '-1,1',
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
        }, probe)
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
        helper, printer = make_helper({
            'switch_offset': '0.5',
            'offset_margins': '-1,1',
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
            'offset_gcode': 'SET_GCODE_OFFSET Z_ADJUST={params.Z|float}',
        }, probe)
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
