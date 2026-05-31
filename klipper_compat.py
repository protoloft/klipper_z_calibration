# Klipper compatibility helpers for z_calibration.
#
# Copyright (C) 2021-2025  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from mcu import MCU_endstop


class PrinterObjectCompat:
    def __init__(self, printer):
        self.printer = printer

    def lookup_gcode(self):
        return self.printer.lookup_object('gcode')

    def lookup_gcode_move(self):
        return self.printer.lookup_object('gcode_move')

    def lookup_homing(self):
        return self.printer.lookup_object('homing')

    def lookup_toolhead(self):
        return self.printer.lookup_object('toolhead')

    def lookup_probe(self):
        return self.printer.lookup_object('probe')

    def lookup_optional_probe(self):
        return self.printer.lookup_object('probe', default=None)

    def lookup_safe_z_home(self):
        return self.printer.lookup_object('safe_z_home', default=None)

    def lookup_bed_mesh(self):
        return self.printer.lookup_object('bed_mesh', default=None)

    def load_gcode_macro(self, config):
        return self.printer.load_object(config, 'gcode_macro')

    def load_query_endstops(self, config):
        return self.printer.load_object(config, 'query_endstops')


class EndstopWrapper:
    def __init__(self, endstop):
        self.mcu_endstop = endstop
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self.mcu_endstop.get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop


class HomingCompat:
    def __init__(self, printer):
        self.printer = printer
        self.objects = PrinterObjectCompat(printer)

    def get_z_endstop(self, query_endstops, section_name):
        z_endstop = None
        for endstop, name in query_endstops.endstops:
            if name == 'stepper_z' or name == 'z':
                if not isinstance(endstop, MCU_endstop):
                    raise self.printer.config_error(
                        "A virtual endstop for z is not supported for %s"
                        % (section_name,))
                z_endstop = EndstopWrapper(endstop)
        if z_endstop is None:
            raise self.printer.config_error("No z-endstop found for %s"
                                            % (section_name,))
        return z_endstop

    def get_z_rail_settings(self, rail):
        if not rail.get_steppers()[0].is_active_axis('z'):
            return None
        return {
            'position_endstop': rail.position_endstop,
            'homing_speed': rail.homing_speed,
            'second_homing_speed': rail.second_homing_speed,
            'homing_retract_dist': rail.homing_retract_dist,
            'position_min': rail.position_min,
        }

    def probing_move(self, mcu_endstop, pos, speed):
        homing = self.objects.lookup_homing()
        return homing.probing_move(mcu_endstop, pos, speed)


class ToolheadCompat:
    def __init__(self, printer):
        self.printer = printer
        self.objects = PrinterObjectCompat(printer)

    def _toolhead(self):
        return self.objects.lookup_toolhead()

    def get_position(self):
        return self._toolhead().get_position()

    def manual_move(self, coord, speed):
        self._toolhead().manual_move(coord, speed)

    def get_last_move_time(self):
        return self._toolhead().get_last_move_time()

    def is_axis_homed(self, axis):
        eventtime = self.printer.get_reactor().monotonic()
        homed_axes = self._toolhead().get_status(eventtime).get(
            'homed_axes', '')
        return axis in homed_axes


class BedMeshCompat:
    def get_zero_reference_position(self, mesh):
        if mesh is None:
            return None
        bmc = getattr(mesh, 'bmc', None)
        if bmc is None:
            return None
        if (hasattr(bmc, 'probe_mgr')
            and bmc.probe_mgr.zero_ref_pos is not None):
            return bmc.probe_mgr.zero_ref_pos
        if hasattr(bmc, 'zero_ref_pos') and bmc.zero_ref_pos is not None:
            # TODO: remove - deprecated since 2024-06
            return bmc.zero_ref_pos
        if (hasattr(bmc, 'relative_reference_index')
            and bmc.relative_reference_index is not None):
            # TODO: remove: trying to read the deprecated rri
            rri = bmc.relative_reference_index
            return bmc.points[rri]
        return None


class ProbeCompat:
    def __init__(self, helper, probe, gcmd=None):
        self.helper = helper
        self.probe = probe
        self.gcmd = gcmd
        self.gcode = helper.gcode
        self.session = None

    def get_config_defaults(self):
        # TODO: remove: deprecated since 2024-06-10
        if hasattr(self.probe, 'sample_count'):
            return {
                'samples': self.probe.sample_count,
                'samples_tolerance': self.probe.samples_tolerance,
                'samples_tolerance_retries': self.probe.samples_retries,
                'lift_speed': self.probe.lift_speed,
                'samples_result': self.probe.samples_result,
                'safe_z_height': self.probe.z_offset * 2,
            }
        probe_params = self.probe.get_probe_params()
        return {
            'samples': probe_params['samples'],
            'samples_tolerance': probe_params['samples_tolerance'],
            'samples_tolerance_retries': (
                probe_params['samples_tolerance_retries']),
            'lift_speed': probe_params['lift_speed'],
            'samples_result': probe_params['samples_result'],
            'safe_z_height': self.probe.get_offsets()[2] * 2,
        }

    def get_offsets(self):
        return self.probe.get_offsets()

    def start(self):
        if hasattr(self.probe, 'start_probe_session'):
            self.session = self.probe.start_probe_session(self.gcmd)
        elif hasattr(self.probe, 'multi_probe_begin'):
            # TODO: remove: deprecated since 2024-06-10
            self.probe.multi_probe_begin()
        else:
            # TODO: remove: deprecated since 2024-06-10
            self.probe.probe_session.start_probe_session(None)

    def end(self):
        if self.session is not None:
            self.session.end_probe_session()
            self.session = None
        elif hasattr(self.probe, 'multi_probe_end'):
            # TODO: remove: deprecated since 2024-06-10
            self.probe.multi_probe_end()
        else:
            # TODO: remove: deprecated since 2024-06-10
            self.probe.probe_session.end_probe_session()

    def query_endstop(self, print_time):
        for probe_endstop in self._query_endstop_candidates():
            query_endstop = getattr(probe_endstop, 'query_endstop', None)
            if query_endstop is not None:
                return query_endstop(print_time)
        raise self.gcmd.error("%s: probe does not support endstop queries"
                              % (self.gcmd.get_command(),))

    def can_probe(self):
        return self.session is not None and hasattr(self.session, 'run_probe')

    def get_legacy_probe_endstop(self):
        probe_endstop = getattr(self.probe, 'mcu_probe', None)
        if probe_endstop is None:
            return None
        if hasattr(probe_endstop, 'get_steppers'):
            return probe_endstop
        return getattr(probe_endstop, 'mcu_endstop', None)

    def run_probe(self, speed, samples=None):
        if not self.can_probe():
            return None
        pgcmd = self._create_probe_gcmd(speed, samples)
        self.session.run_probe(pgcmd)
        results = self.session.pull_probed_results()
        if not results:
            raise self.gcmd.error("%s: probe did not return a result"
                                  % (self.gcmd.get_command(),))
        return results[-1]

    def get_test_position(self, probe_result):
        if hasattr(probe_result, 'test_z'):
            return [probe_result.test_x, probe_result.test_y,
                    probe_result.test_z]
        if len(probe_result) >= 6:
            return [probe_result[3], probe_result[4], probe_result[5]]
        return probe_result[:3]

    def _create_probe_gcmd(self, speed, samples):
        params = {}
        if hasattr(self.gcmd, 'get_command_parameters'):
            params.update(self.gcmd.get_command_parameters())
        samples_result = self.helper.samples_result or 'average'
        params.update({
            'PROBE_SPEED': str(speed),
            'LIFT_SPEED': str(self.helper.lift_speed),
            'SAMPLES': str(samples or self.helper.samples),
            'SAMPLE_RETRACT_DIST': str(self.helper.retract_dist),
            'SAMPLES_TOLERANCE': str(self.helper.tolerance),
            'SAMPLES_TOLERANCE_RETRIES': str(self.helper.retries),
            'SAMPLES_RESULT': samples_result,
        })
        command = self.gcmd.get_command()
        return self.gcode.create_gcode_command(command, command, params)

    def _query_endstop_candidates(self):
        probe_endstop = getattr(self.probe, 'mcu_probe', None)
        candidates = [self.probe, probe_endstop]
        if probe_endstop is not None:
            candidates.append(getattr(probe_endstop, 'mcu_endstop', None))
        return [candidate for candidate in candidates if candidate is not None]


class GCodeOffsetCompat:
    def __init__(self, gcode, gcode_move):
        self.gcode = gcode
        self.gcode_move = gcode_move

    def set_new_offset(self, offset):
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET",
                                                      "SET_GCODE_OFFSET",
                                                      {'Z': 0.0})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET",
                                                      "SET_GCODE_OFFSET",
                                                      {'Z_ADJUST': offset})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
