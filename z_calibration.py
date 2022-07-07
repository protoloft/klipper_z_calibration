
# Klipper plugin for a selfcalibrating Z offset.
#
# Copyright (C) 2021-2022  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
from mcu import MCU_endstop

class ZCalibrationHelper:
    def __init__(self, config):
        self.state = None
        self.z_endstop = None
        self.z_homing = None
        self.last_state = False
        self.last_z_offset = 0.
        self.config = config
        self.printer = config.get_printer()
        self.switch_offset = config.getfloat('switch_offset', 0.0, above=0.)
        self.max_deviation = config.getfloat('max_deviation', 1.0, above=0.)
        self.speed = config.getfloat('speed', 50.0, above=0.)
        self.clearance = config.getfloat('clearance', None, above=0.)
        self.samples = config.getint('samples', None, minval=1)
        self.tolerance = config.getfloat('samples_tolerance', None, above=0.)
        self.retries = config.getint('samples_tolerance_retries',
                                     None, minval=0)
        atypes = {'none': None, 'median': 'median', 'average': 'average'}
        self.samples_result = config.getchoice('samples_result', atypes,
                                               'none')
        self.lift_speed = config.getfloat('lift_speed', None, above=0.)
        self.probing_speed = config.getfloat('probing_speed', None, above=0.)
        self.second_speed = config.getfloat('probing_second_speed',
                                            None, above=0.)
        self.retract_dist = config.getfloat('probing_retract_dist',
                                            None, above=0.)
        self.position_min = config.getfloat('position_min', None)
        self.first_fast = config.getboolean('probing_first_fast', False)
        self.nozzle_site = self._get_site("nozzle_xy_position", "probe_nozzle")
        self.switch_site = self._get_site("switch_xy_position", "probe_switch")
        self.bed_site = self._get_site("bed_xy_position", "probe_bed", True)
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        self.start_gcode = gcode_macro.load_template(config, 'start_gcode', '')
        self.switch_gcode = gcode_macro.load_template(config,
                                                      'before_switch_gcode',
                                                      '')
        self.end_gcode = gcode_macro.load_template(config, 'end_gcode', '')
        self.query_endstops = self.printer.load_object(config,
                                                       'query_endstops')
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
        self.printer.register_event_handler("homing:home_rails_end",
                                            self.handle_home_rails_end)
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('CALIBRATE_Z', self.cmd_CALIBRATE_Z,
                                    desc=self.cmd_CALIBRATE_Z_help)
        self.gcode.register_command('PROBE_Z_ACCURACY',
                                    self.cmd_PROBE_Z_ACCURACY,
                                    desc=self.cmd_PROBE_Z_ACCURACY_help)
    def get_status(self, eventtime):
        return {'last_query': self.last_state,
                'last_z_offset': self.last_z_offset}
    def handle_connect(self):
        # get z-endstop
        for endstop, name in self.query_endstops.endstops:
            if name == 'z':
                # check for virtual endstops..
                if not isinstance(endstop, MCU_endstop):
                    raise self.printer.config_error("A virtual endstop for z"
                                                    " is not supported for %s"
                                                    % (self.config.get_name()))
                self.z_endstop = EndstopWrapper(self.config, endstop)
        # get probing settings
        probe = self.printer.lookup_object('probe', default=None)
        if probe is None:
            raise self.printer.config_error("A probe is needed for %s"
                                            % (self.config.get_name()))
        if self.samples is None:
            self.samples = probe.sample_count
        if self.tolerance is None:
            self.tolerance = probe.samples_tolerance
        if self.retries is None:
            self.retries = probe.samples_retries
        if self.lift_speed is None:
            self.lift_speed = probe.lift_speed
        if self.clearance is None:
            self.clearance = probe.z_offset * 2
        if self.clearance == 0:
            self.clearance = 20 # defaults to 20mm
        if self.samples_result is None:
            self.samples_result = probe.samples_result
    def handle_home_rails_end(self, homing_state, rails):
        # get z homing position
        for rail in rails:
            if rail.get_steppers()[0].is_active_axis('z'):
                # get homing settings from z rail
                self.z_homing = rail.position_endstop
                if self.probing_speed is None:
                    self.probing_speed = rail.homing_speed
                if self.second_speed is None:
                    self.second_speed = rail.second_homing_speed
                if self.retract_dist is None:
                    self.retract_dist = rail.homing_retract_dist
                if self.position_min is None:
                    self.position_min = rail.position_min
    def _build_config(self):
        pass
    cmd_CALIBRATE_Z_help = ("Automatically calibrates the nozzle offset"
                            " to the print surface")
    def cmd_CALIBRATE_Z(self, gcmd):
        if self.z_homing is None:
            raise gcmd.error("Must home axes first")
        site_attr = gcmd.get("BED_POSITION", None)
        if site_attr is not None:
            # set bed site from BED_POSITION parameter
            self.bed_site = self._parse_site("BED_POSITION", site_attr)
        elif self._get_site("bed_xy_position", "probe_bed", True) is not None:
            # set bed site from configuration
            self.bed_site = self._get_site("bed_xy_position", "probe_bed", False)
        else:
            # else get the mesh's relative reference index point
            # a round mesh/bed would not work here so far...
            try:
                mesh = self.printer.lookup_object('bed_mesh', default=None)
                rri = mesh.bmc.relative_reference_index    
                self.bed_site = mesh.bmc.points[rri]
                logging.debug("Z-CALIBRATION probe bed_x=%.3f bed_y=%.3f"
                              % (self.bed_site[0], self.bed_site[1]))
            except:
                raise gcmd.error("Either use the BED_POSITION parameter,"
                                 " configure a bed_xy_position or define"
                                 " a mesh with a relative_reference_index"
                                 " for %s" % (self.config.get_name()))
        self._log_config()
        state = CalibrationState(self, gcmd)
        state.calibrate_z()
    cmd_PROBE_Z_ACCURACY_help = ("Probe Z-Endstop accuracy at"
                                 " Nozzle-Endstop position")
    def cmd_PROBE_Z_ACCURACY(self, gcmd):
        if self.z_homing is None:
            raise gcmd.error("Must home axes first")
        speed = gcmd.get_float("PROBE_SPEED", self.second_speed, above=0.)
        lift_speed = gcmd.get_float("LIFT_SPEED", self.lift_speed, above=0.)
        sample_count = gcmd.get_int("SAMPLES", self.samples, minval=1)
        sample_retract_dist = gcmd.get_float("SAMPLE_RETRACT_DIST",
                                             self.retract_dist, above=0.)
        toolhead = self.printer.lookup_object('toolhead')
        pos = toolhead.get_position()
        if pos[2] < self.clearance:
            # no clearance, better to move up
            self._move([None, None, pos[2] + self.clearance], lift_speed)
        # move to z-endstop position
        self._move(list(self.nozzle_site), self.speed)
        pos = toolhead.get_position()
        gcmd.respond_info("PROBE_ACCURACY at X:%.3f Y:%.3f Z:%.3f"
                          " (samples=%d retract=%.3f"
                          " speed=%.1f lift_speed=%.1f)\n"
                          % (pos[0], pos[1], pos[2],
                             sample_count, sample_retract_dist,
                             speed, lift_speed))
        # Probe bed sample_count times
        positions = []
        while len(positions) < sample_count:
            # Probe position
            pos = self._probe(self.z_endstop, self.position_min, speed)
            positions.append(pos)
            # Retract
            liftpos = [None, None, pos[2] + sample_retract_dist]
            self._move(liftpos, lift_speed)
        # Calculate maximum, minimum and average values
        max_value = max([p[2] for p in positions])
        min_value = min([p[2] for p in positions])
        range_value = max_value - min_value
        avg_value = self._calc_mean(positions)[2]
        median = self._calc_median(positions)[2]
        # calculate the standard deviation
        deviation_sum = 0
        for i in range(len(positions)):
            deviation_sum += pow(positions[i][2] - avg_value, 2.)
        sigma = (deviation_sum / len(positions)) ** 0.5
        # Show information
        gcmd.respond_info(
            "probe accuracy results: maximum %.6f, minimum %.6f, range %.6f,"
            " average %.6f, median %.6f, standard deviation %.6f" % (
            max_value, min_value, range_value, avg_value, median, sigma))        
    def _get_site(self, name, legacy_prefix, optional=False):
        legacy_x = self.config.getfloat("%s_x" % (legacy_prefix), -1.0)
        legacy_y = self.config.getfloat("%s_y" % (legacy_prefix), -1.0)
        if (optional and self.config.get(name, None) is None
            and (legacy_x < 0 or legacy_y < 0)):
            return None
        if legacy_x >= 0 and legacy_y >= 0:
            return [legacy_x, legacy_y, None]
        else:
            return self._parse_site(name, self.config.get(name))
    def _parse_site(self, name, site):
        try:
            x_pos, y_pos = site.split(',')
            return [float(x_pos), float(y_pos), None]
        except:
            raise self.config.error("Unable to parse %s in %s"
                                    % (name, self.config.get_name()))
    def _probe(self, mcu_endstop, z_position, speed):
            toolhead = self.printer.lookup_object('toolhead')
            pos = toolhead.get_position()
            pos[2] = z_position
            # probe
            phoming = self.printer.lookup_object('homing')
            curpos = phoming.probing_move(mcu_endstop, pos, speed)
            # retract
            self._move([None, None, curpos[2] + self.retract_dist],
                       self.lift_speed)
            self.gcode.respond_info("probe at %.3f,%.3f is z=%.6f"
                % (curpos[0], curpos[1], curpos[2]))
            return curpos
    def _move(self, coord, speed):
        self.printer.lookup_object('toolhead').manual_move(coord, speed)
    def _calc_mean(self, positions):
        count = float(len(positions))
        return [sum([pos[i] for pos in positions]) / count
                for i in range(3)]
    def _calc_median(self, positions):
        z_sorted = sorted(positions, key=(lambda p: p[2]))
        middle = len(positions) // 2
        if (len(positions) & 1) == 1:
            # odd number of samples
            return z_sorted[middle]
        # even number of samples
        return self._calc_mean(z_sorted[middle-1:middle+1])
    def _log_config(self):
        logging.debug("Z-CALIBRATION: switch_offset=%.3f, max_deviation=%.3f,"
                      " speed=%.3f, samples=%i, tolerance=%.3f, retries=%i,"
                      " samples_result=%s, lift_speed=%.3f, clearance=%.3f,"
                      " probing_speed=%.3f, second_speed=%.3f,"
                      " retract_dist=%.3f, position_min=%.3f,"
                      " probe_nozzle_x=%.3f, probe_nozzle_y=%.3f,"
                      " probe_switch_x=%.3f, probe_switch_y=%.3f,"
                      " probe_bed_x=%.3f, probe_bed_y=%.3f"
                      % (self.switch_offset, self.max_deviation, self.speed,
                         self.samples, self.tolerance, self.retries,
                         self.samples_result, self.lift_speed, self.clearance,
                         self.probing_speed, self.second_speed,
                         self.retract_dist, self.position_min,
                         self.nozzle_site[0], self.nozzle_site[1],
                         self.switch_site[0], self.switch_site[1],
                         self.bed_site[0], self.bed_site[1]))
class EndstopWrapper:
    def __init__(self, config, endstop):
        self.mcu_endstop = endstop
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self.mcu_endstop.get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop
class CalibrationState:
    def __init__(self, helper, gcmd):
        self.helper = helper
        self.gcmd = gcmd
        self.gcode = helper.gcode
        self.z_endstop = helper.z_endstop
        self.probe = helper.printer.lookup_object('probe')
        self.toolhead = helper.printer.lookup_object('toolhead')
        self.gcode_move = helper.printer.lookup_object('gcode_move')
    def _probe_on_site(self, endstop, site, check_probe=False):
        pos = self.toolhead.get_position()
        if pos[2] < self.helper.clearance:
            # no clearance, better to move up
            self.helper._move([None, None, pos[2] + self.helper.clearance],
                              self.helper.lift_speed)
        # move to position
        self.helper._move(list(site), self.helper.speed)
        if check_probe:
            # check if probe is attached and switch is closed
            time = self.toolhead.get_last_move_time()
            if self.probe.mcu_probe.query_endstop(time):
                raise self.helper.printer.command_error("Probe switch not"
                                                        " closed - Probe not"
                                                        " attached?")
        if self.helper.first_fast:
            # first probe just to get down faster
            self.helper._probe(endstop, self.helper.position_min,
                               self.helper.probing_speed)
        retries = 0
        positions = []
        while len(positions) < self.helper.samples:
            # probe with second probing speed
            curpos = self.helper._probe(endstop,
                                        self.helper.position_min,
                                        self.helper.second_speed)
            positions.append(curpos[:3])
            # check tolerance
            z_positions = [p[2] for p in positions]
            if max(z_positions) - min(z_positions) > self.helper.tolerance:
                if retries >= self.helper.retries:
                    self.helper.end_gcode.run_gcode_from_command()
                    raise self.gcmd.error("Probe samples exceed tolerance")
                self.gcmd.respond_info("Probe samples exceed tolerance."
                                       " Retrying...")
                retries += 1
                positions = []
        # calculate result
        if self.helper.samples_result == 'median':
            return self.helper._calc_median(positions)[2]
        return self.helper._calc_mean(positions)[2]
    def _add_probe_offset(self, site):
        # calculate bed position by using the probe's offsets
        probe_offsets = self.probe.get_offsets()
        probe_site = list(site)
        probe_site[0] -= probe_offsets[0]
        probe_site[1] -= probe_offsets[1]
        return probe_site
    def _set_new_gcode_offset(self, offset):
        # reset gcode z offset to 0
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET",
                                                      "SET_GCODE_OFFSET",
                                                      {'Z': 0.0})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
        # set new gcode z offset
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET",
                                                      "SET_GCODE_OFFSET",
                                                      {'Z_ADJUST': offset})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
    def calibrate_z(self):
        self.helper.start_gcode.run_gcode_from_command()
        # probe the nozzle
        nozzle_zero = self._probe_on_site(self.z_endstop,
                                          self.helper.nozzle_site)
        # probe the probe-switch
        self.helper.switch_gcode.run_gcode_from_command()
        # probe the body of the switch
        switch_zero = self._probe_on_site(self.z_endstop,
                                          self.helper.switch_site,
                                          True)
        # probe position on bed
        probe_site = self._add_probe_offset(self.helper.bed_site)
        probe_zero = self._probe_on_site(self.probe.mcu_probe,
                                         probe_site,
                                         True)
        # calculate the offset
        offset = probe_zero - (switch_zero - nozzle_zero
                               + self.helper.switch_offset)
        # print result
        self.gcmd.respond_info("Z-CALIBRATION: ENDSTOP=%.3f NOZZLE=%.3f"
                               " SWITCH=%.3f PROBE=%.3f --> OFFSET=%.6f"
                               % (self.helper.z_homing, nozzle_zero,
                                  switch_zero, probe_zero, offset))
        # check max deviation
        if abs(offset) > self.helper.max_deviation:
            self.helper.end_gcode.run_gcode_from_command()
            raise self.helper.printer.command_error("Offset is larger as"
                                                    " allowed: OFFSET=%.3f"
                                                    " MAX_DEVIATION=%.3f"
                                                    % (offset,
                                                    self.helper.max_deviation))
        # set new offset
        self._set_new_gcode_offset(offset)
        # set states
        self.helper.last_state = True
        self.helper.last_z_offset = offset
        self.helper.end_gcode.run_gcode_from_command()
def load_config(config):
    return ZCalibrationHelper(config)
