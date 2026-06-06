# Klipper plugin entrypoint for automatic dockable-probe Z calibration.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import math
import os
import sys

# Only this file is linked into Klipper. Resolve the symlink so helper modules
# load from the repository checkout.
MODULE_PATH = os.path.dirname(os.path.realpath(__file__))
if MODULE_PATH not in sys.path:
    sys.path.insert(0, MODULE_PATH)

from klipper_compat import BedMeshCompat, GCodeOffsetCompat, HomingCompat
from klipper_compat import PrinterObjectCompat, ProbeCompat, ToolheadCompat
from klipper_compat import run_gcode_template, validate_runtime_contract

class ZCalibrationHelper:
    """Owns plugin configuration, startup state, and G-Code commands."""

    def __init__(self, config):
        self.state = None
        self.z_endstop = None
        self.z_homing = None
        self.last_state = False
        self.last_z_offset = None
        self.position_z_endstop = None
        self.name = config.get_name()
        self.printer = config.get_printer()
        self.objects_compat = PrinterObjectCompat(self.printer)
        self.bed_mesh_compat = BedMeshCompat()
        self.homing_compat = HomingCompat(self.printer)
        self.toolhead_compat = ToolheadCompat(self.printer)
        self.switch_offset = config.getfloat('switch_offset', None, above=0.)
        self.offset_margins = self._get_offset_margins(
            config, 'offset_margins', '-1.0,1.0')
        self.speed = config.getfloat('speed', 50.0, above=0.)
        self.safe_z_height = config.getfloat('safe_z_height', None, above=0.)
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
        self.nozzle_site = self._get_xy(config, "nozzle_xy_position", True)
        self.switch_site = self._get_xy(config, "switch_xy_position", True)
        self.switch_xy_offsets = self._get_xy(
            config, "switch_xy_offsets", True)
        self.bed_site = self._get_xy(config, "bed_xy_position", True)
        self.wiggle_offsets = self._get_xy(config, "wiggle_xy_offsets", True)
        gcode_macro = self.objects_compat.load_gcode_macro(config)
        self.start_gcode = self._load_gcode_template(config, gcode_macro,
                                                     'start_gcode')
        self.switch_gcode = self._load_gcode_template(
            config, gcode_macro, 'before_switch_gcode')
        self.end_gcode = self._load_gcode_template(config, gcode_macro,
                                                   'end_gcode')
        self.offset_gcode = self._load_optional_gcode_template(
            config, gcode_macro, 'offset_gcode')
        self.error_gcode = self._load_optional_gcode_template(
            config, gcode_macro, 'error_gcode')
        self.query_endstops = self.objects_compat.load_query_endstops(config)
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
        self.printer.register_event_handler("homing:home_rails_end",
                                            self.handle_home_rails_end)
        self.gcode = self.objects_compat.lookup_gcode()
        self.gcode.register_command('CALIBRATE_Z', self.cmd_CALIBRATE_Z,
                                    desc=self.cmd_CALIBRATE_Z_help)
        self.gcode.register_command('PROBE_Z_ACCURACY',
                                    self.cmd_PROBE_Z_ACCURACY,
                                    desc=self.cmd_PROBE_Z_ACCURACY_help)
        self.gcode.register_command('CALCULATE_SWITCH_OFFSET',
                                    self.cmd_CALCULATE_SWITCH_OFFSET,
                                    desc=self.cmd_CALCULATE_SWITCH_OFFSET_help)
    # Configuration parsing helpers
    def _load_gcode_template(self, config, gcode_macro, name):
        """Load a G-Code template that defaults to an empty no-op."""
        return gcode_macro.load_template(config, name, '')

    def _load_optional_gcode_template(self, config, gcode_macro, name):
        """Load an optional G-Code template, rejecting explicit blanks."""
        value = config.get(name, None)
        if value is None:
            return None
        if not value.strip():
            raise config.error("%s in %s cannot be blank" % (name, self.name))
        return gcode_macro.load_template(config, name)

    def _get_xy(self, config, name, optional=False):
        """Read an optional `x,y` config value as a Klipper coordinate."""
        if optional and config.get(name, None) is None:
            return None
        return self._parse_xy(name, config.get(name), config=config)

    def _parse_xy(self, name, site, gcmd=None, config=None):
        """Parse an `x,y` value and report errors in the caller's context."""
        try:
            x_pos, y_pos = site.split(',')
            return [self._parse_finite_float(x_pos),
                    self._parse_finite_float(y_pos),
                    None]
        except (AttributeError, TypeError, ValueError):
            if gcmd is not None:
                raise gcmd.error("%s: unable to parse %s"
                                 % (gcmd.get_command(), name))
            if config is not None:
                raise config.error("Unable to parse %s in %s"
                                   % (name, self.name))
            raise self.printer.config_error("Unable to parse %s in %s"
                                            % (name, self.name))

    def _parse_finite_float(self, raw_value):
        """Parse a float and reject NaN or infinite values."""
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError()
        return value

    def _get_offset_margins(self, config, name, default):
        """Parse offset margins as symmetric or explicit min/max bounds."""
        try:
            margins = [self._parse_finite_float(val.strip())
                       for val in config.get(name, default).split(',')]
            if len(margins) == 1:
                val = abs(margins[0])
                margins[0] = -val
                margins.append(val)
            elif len(margins) != 2:
                raise ValueError()
            if margins[0] > margins[1]:
                raise ValueError()
            return margins
        except (AttributeError, TypeError, ValueError):
            raise config.error("Unable to parse %s in %s"
                               % (name, self.name))
    # Klipper lifecycle and status
    def get_status(self, eventtime):
        """Expose last calibration state through Klipper's status API."""
        return {'last_query': self.last_state,
                'last_z_offset': self.last_z_offset}

    def handle_connect(self):
        """Resolve required printer objects once Klipper is connected."""
        self.z_endstop = self.homing_compat.get_z_endstop(
            self.query_endstops, self.name)
        # get probing settings
        probe = self.objects_compat.lookup_optional_probe()
        if probe is None:
            raise self.printer.config_error("A probe is needed for %s"
                                            % (self.name,))
        validate_runtime_contract(self.printer, probe, self.name,
                                  self.z_endstop, self.offset_gcode,
                                  self.error_gcode)
        probe_defaults = ProbeCompat(self, probe).get_config_defaults()
        if self.samples is None:
            self.samples = probe_defaults['samples']
        if self.tolerance is None:
            self.tolerance = probe_defaults['samples_tolerance']
        if self.retries is None:
            self.retries = probe_defaults['samples_tolerance_retries']
        if self.lift_speed is None:
            self.lift_speed = probe_defaults['lift_speed']
        if self.samples_result is None:
            self.samples_result = probe_defaults['samples_result']
        if self.safe_z_height is None:
            self.safe_z_height = probe_defaults['safe_z_height']
        if self.safe_z_height < 3:
            self.safe_z_height = 20 # defaults to 20mm

    def handle_home_rails_end(self, homing_state, rails):
        """Cache Z rail homing settings after Klipper homes rails."""
        # get z homing position
        for rail in rails:
            settings = self.homing_compat.get_z_rail_settings(rail)
            if settings is None:
                continue
            # get homing settings from z rail
            self.z_homing = settings['position_endstop']
            if self.probing_speed is None:
                self.probing_speed = settings['homing_speed']
            if self.second_speed is None:
                self.second_speed = settings['second_homing_speed']
            if self.retract_dist is None:
                self.retract_dist = settings['homing_retract_dist']
            if self.position_min is None:
                self.position_min = settings['position_min']
            self.position_z_endstop = settings['position_endstop']
    # G-Code command handlers
    cmd_CALIBRATE_Z_help = ("Automatically calibrates the nozzle offset"
                            " to the print surface")
    def cmd_CALIBRATE_Z(self, gcmd):
        """Run the full nozzle, switch, and bed probe calibration flow."""
        self.last_state = False
        try:
            self._require_z_homed(gcmd)
            nozzle_site = self._get_nozzle_site(gcmd)
            switch_site = self._get_switch_site(gcmd, nozzle_site)
            bed_site = self._get_bed_site(gcmd)
            switch_offset = self._get_switch_offset(gcmd)
            self._log_params(gcmd, switch_offset, nozzle_site, switch_site,
                             bed_site)
            run = CalibrationRun(self, gcmd)
            run.calibrate_z(switch_offset, nozzle_site, switch_site, bed_site)
        except Exception as err:
            self._run_error_gcode(err)
            raise
    cmd_PROBE_Z_ACCURACY_help = ("Probe Z-Endstop accuracy at"
                                 " Nozzle-Endstop position")
    def cmd_PROBE_Z_ACCURACY(self, gcmd):
        """Sample the calibration endstop and report repeatability stats."""
        self._require_z_homed(gcmd)
        speed = gcmd.get_float("PROBE_SPEED", self.second_speed, above=0.)
        lift_speed = gcmd.get_float("LIFT_SPEED", self.lift_speed, above=0.)
        sample_count = gcmd.get_int("SAMPLES", self.samples, minval=1)
        sample_retract_dist = gcmd.get_float("SAMPLE_RETRACT_DIST",
                                             self.retract_dist, above=0.)
        nozzle_site = self._get_nozzle_site(gcmd)
        pos = self.toolhead_compat.get_position()
        self._move_safe_z(pos, lift_speed)
        # move to z-endstop position
        self._move(list(nozzle_site), self.speed)
        pos = self.toolhead_compat.get_position()
        gcmd.respond_info("%s at X:%.3f Y:%.3f Z:%.3f"
                          " (samples=%d retract=%.3f"
                          " speed=%.1f lift_speed=%.1f)\n"
                          % (gcmd.get_command(), pos[0], pos[1], pos[2],
                             sample_count, sample_retract_dist, speed,
                             lift_speed))
        # Probe bed sample_count times
        positions = []
        while len(positions) < sample_count:
            # Probe position
            pos = self._probe(gcmd, self.z_endstop, self.position_min, speed,
                              retract=False)
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
        # show result
        gcmd.respond_info(
            "%s: probe z accuracy results: maximum %.6f, minimum %.6f,"
            " range %.6f, average %.6f, median %.6f, standard deviation %.6f"
            % (gcmd.get_command(), max_value, min_value, range_value,
               avg_value, median, sigma))
    cmd_CALCULATE_SWITCH_OFFSET_help = ("Calculates a switch_offset based on"
                                        " the current z position")
    def cmd_CALCULATE_SWITCH_OFFSET(self, gcmd):
        """Estimate a new switch_offset from the last calibration result."""
        if self.last_z_offset is None:
            raise gcmd.error("%s: must run CALIBRATE_Z first"
                             % (gcmd.get_command()))
        switch_offset = self._get_switch_offset(gcmd)
        pos = self.toolhead_compat.get_position()
        new_switch_offset = switch_offset - (pos[2] - self.last_z_offset)
        if new_switch_offset > 0.0:
            gcmd.respond_info("%s: switch_offset=%.3f - (current_z=%.3f -"
                              " z_offset=%.3f) --> new switch_offset=%.3f"
                              % (gcmd.get_command(), switch_offset, pos[2],
                                 self.last_z_offset, new_switch_offset))
        else:
            gcmd.respond_info("%s: the resulting switch offset is negative!"
                              " Either the nozzle is still too far away or"
                              " something else is wrong..."
                              % (gcmd.get_command()))
    # Command parameter and position resolution
    def _get_nozzle_site(self, gcmd):
        """Resolve the nozzle endstop XY position for this command."""
        nozzle_param = gcmd.get("NOZZLE_POSITION", "")
        safe_z_home = self.objects_compat.lookup_safe_z_home()
        # from NOZZLE_POSITION parameter
        if nozzle_param:
            return self._parse_xy("NOZZLE_POSITION", nozzle_param, gcmd)
        # from configuration
        if self.nozzle_site is not None:
            return self.nozzle_site
        # get z-endstop position from safe_z_home
        if safe_z_home is not None:
            return [safe_z_home.home_x_pos, safe_z_home.home_y_pos, None]
        raise gcmd.error("%s: cannot find a nozzle position! Either configure"
                         " the nozzle_xy_position for %s, the [safe_z_home],"
                         " or use the NOZZLE_POSITION parameter."
                         % (gcmd.get_command(), self.name))
    def _get_switch_site(self, gcmd, nozzle_site):
        """Resolve the switch body XY position for this command."""
        switch_param = gcmd.get("SWITCH_POSITION", "")
        # from SWITCH_POSITION parameter
        if switch_param:
            return self._parse_xy("SWITCH_POSITION", switch_param, gcmd)
        # from configuration
        if self.switch_site is not None:
            return self.switch_site
        # calculate from offsets
        if self.switch_xy_offsets is not None:
            return [nozzle_site[0] + self.switch_xy_offsets[0],
                    nozzle_site[1] + self.switch_xy_offsets[1],
                    None]
        raise gcmd.error("%s: cannot find a switch position! Either configure"
                         " the switch_xy_position or the switch_xy_offsets for"
                         " %s or use the SWITCH_POSITION parameter."
                         % (gcmd.get_command(), self.name))
    def _get_bed_site(self, gcmd):
        """Resolve the bed probing XY position for this command."""
        bed_param = gcmd.get("BED_POSITION", "")
        mesh = self.objects_compat.lookup_bed_mesh()
        # from BED_POSITION parameter
        if bed_param:
            return self._parse_xy("BED_POSITION", bed_param, gcmd)
        # from configuration
        if self.bed_site is not None:
            return self.bed_site
        # from mesh's zero reference position
        bed_site = self.bed_mesh_compat.get_zero_reference_position(mesh)
        if bed_site is not None:
            return bed_site
        raise gcmd.error("%s: cannot find a bed position! Either configure the"
                         " bed_xy_position for %s, the mesh's"
                         " zero_reference_position, or use the NOZZLE_POSITION"
                         " parameter."
                         % (gcmd.get_command(), self.name))
    def _get_switch_offset(self, gcmd):
        """Resolve switch_offset from G-Code parameter or config."""
        # from SWITCH_OFFSET parameter
        if gcmd.get("SWITCH_OFFSET", ""):
            return gcmd.get_float("SWITCH_OFFSET", None, above=0.)
        # from configuration
        if self.switch_offset is not None:
            return self.switch_offset
        raise gcmd.error("%s: cannot find a switch offset! Either configure"
                         " the switch_offset for %s, or use the SWITCH_OFFSET"
                         " parameter."
                         % (gcmd.get_command(), self.name))
    def _run_error_gcode(self, err):
        """Run the configured error hook without masking the original error."""
        if self.error_gcode is None:
            return
        try:
            run_gcode_template(self.error_gcode, {'ERROR': err})
        except Exception:
            logging.exception("error_gcode failed")
    # Movement and probing primitives
    def _probe(self, gcmd, mcu_endstop, z_position, speed, wiggle=False,
               retract=True):
        """Probe a given endstop at the current XY position."""
        pos = self.toolhead_compat.get_position()
        pos[2] = z_position
        # probe
        curpos = self.homing_compat.probing_move(mcu_endstop, pos, speed)
        # retract
        if retract:
            self._move([None, None, curpos[2] + self.retract_dist],
                       self.lift_speed)
        if wiggle and self.wiggle_offsets is not None:
            self._move([curpos[0] + self.wiggle_offsets[0],
                        curpos[1] + self.wiggle_offsets[1],
                        None],
                       self.speed)
            self._move([curpos[0], curpos[1], None], self.speed)
        self.gcode.respond_info("%s: probe at %.3f,%.3f is z=%.6f"
                                % (gcmd.get_command(), curpos[0],
                                   curpos[1], curpos[2]))
        return curpos
    def _require_z_homed(self, gcmd):
        """Reject commands until Z homing state is known and current."""
        if self.z_homing is None:
            raise gcmd.error("%s: must home axes first" % (gcmd.get_command()))
        if not self.toolhead_compat.is_axis_homed('z'):
            raise gcmd.error("%s: must home axes first" % (gcmd.get_command()))
    def _move(self, coord, speed):
        """Move through Klipper's toolhead wrapper."""
        self.toolhead_compat.manual_move(coord, speed)

    def _move_safe_z(self, pos, lift_speed):
        """Lift to safe_z_height when the current Z is below it."""
        if pos[2] < self.safe_z_height:
            # no safe z position, better to move up (absolute)
            self._move([None, None, self.safe_z_height], lift_speed)
    # Calculation and logging helpers
    def _calc_mean(self, positions):
        """Return the coordinate-wise mean of sampled positions."""
        count = float(len(positions))
        return [sum([pos[i] for pos in positions]) / count
                for i in range(3)]
    def _calc_median(self, positions):
        """Return the median Z sample, averaging the middle pair if needed."""
        z_sorted = sorted(positions, key=(lambda p: p[2]))
        middle = len(positions) // 2
        if (len(positions) & 1) == 1:
            # odd number of samples
            return z_sorted[middle]
        # even number of samples
        return self._calc_mean(z_sorted[middle-1:middle+1])
    def _log_params(self, gcmd, switch_offset, nozzle_site, switch_site,
                    bed_site):
        """Write the effective calibration parameters to the Klipper log."""
        logging.info("%s: switch_offset=%.3f, offset_margins=%.3f,%.3f,"
                     " speed=%.3f, samples=%i, tolerance=%.3f, retries=%i,"
                     " samples_result=%s, lift_speed=%.3f, safe_z_height=%.3f,"
                     " probing_speed=%.3f, second_speed=%.3f,"
                     " retract_dist=%.3f, position_min=%.3f,"
                     " probe_nozzle_x=%.3f, probe_nozzle_y=%.3f,"
                     " probe_switch_x=%.3f, probe_switch_y=%.3f,"
                     " probe_bed_x=%.3f, probe_bed_y=%.3f"
                     % (gcmd.get_command(), switch_offset,
                        self.offset_margins[0], self.offset_margins[1],
                        self.speed, self.samples, self.tolerance,
                        self.retries, self.samples_result, self.lift_speed,
                        self.safe_z_height, self.probing_speed,
                        self.second_speed, self.retract_dist,
                        self.position_min, nozzle_site[0], nozzle_site[1],
                        switch_site[0], switch_site[1], bed_site[0],
                        bed_site[1]))
class CalibrationRun:
    """Executes one CALIBRATE_Z command with resolved runtime state."""

    def __init__(self, helper, gcmd):
        self.helper = helper
        self.gcmd = gcmd
        self.gcode = helper.gcode
        self.z_endstop = helper.z_endstop
        self.objects_compat = helper.objects_compat
        self.probe = self.objects_compat.lookup_probe()
        self.probe_compat = ProbeCompat(helper, self.probe, gcmd)
        self.toolhead_compat = ToolheadCompat(helper.printer)
        if helper.offset_gcode is None:
            gcode_move = self.objects_compat.lookup_gcode_move()
        else:
            gcode_move = None
        self.gcode_offset = GCodeOffsetCompat(self.gcode, gcode_move,
                                              helper.offset_gcode)
        self.offset_margins = helper.offset_margins
    def _probe_on_site(self, endstop, site, check_probe=False, split_xy=False,
                       wiggle=False):
        """Move to a site and sample the given endstop with retry handling."""
        pos = self.toolhead_compat.get_position()
        self.helper._move_safe_z(pos, self.helper.lift_speed)
        # move to position
        if split_xy:
            self.helper._move([site[0], pos[1], None], self.helper.speed)
            self.helper._move([site[0], site[1], site[2]], self.helper.speed)
        else:
            self.helper._move(site, self.helper.speed)
        if check_probe:
            # check if probe is attached and switch is closed
            self._check_probe_attached()
        if self.helper.first_fast:
            # first probe just to get down faster
            self.helper._probe(self.gcmd, endstop, self.helper.position_min,
                               self.helper.probing_speed, wiggle=wiggle)
        retries = 0
        positions = []
        while len(positions) < self.helper.samples:
            # probe with second probing speed
            curpos = self.helper._probe(self.gcmd, endstop,
                                        self.helper.position_min,
                                        self.helper.second_speed,
                                        wiggle=wiggle)
            positions.append(curpos[:3])
            # check tolerance
            z_positions = [p[2] for p in positions]
            if max(z_positions) - min(z_positions) > self.helper.tolerance:
                if retries >= self.helper.retries:
                    raise self.gcmd.error("%s: probe samples exceed tolerance"
                                          % (self.gcmd.get_command()))
                self.gcmd.respond_info("%s: probe samples exceed tolerance."
                                       " Retrying..."
                                       % (self.gcmd.get_command()))
                retries += 1
                positions = []
        # calculate result
        if self.helper.samples_result == 'median':
            return self.helper._calc_median(positions)[2]
        return self.helper._calc_mean(positions)[2]
    def _probe_bed_on_site(self, site):
        """Probe the bed using the Klipper probe session path."""
        pos = self.toolhead_compat.get_position()
        self.helper._move_safe_z(pos, self.helper.lift_speed)
        self.helper._move(site, self.helper.speed)
        self._check_probe_attached()
        if self.helper.first_fast:
            self.probe_compat.run_probe(self.helper.probing_speed, samples=1)
        probe_result = self.probe_compat.run_probe(self.helper.second_speed)
        curpos = self.probe_compat.get_test_position(probe_result)
        self.gcode.respond_info("%s: probe at %.3f,%.3f is z=%.6f"
                                % (self.gcmd.get_command(), curpos[0],
                                   curpos[1], curpos[2]))
        return curpos[2]
    def _check_probe_attached(self):
        """Verify the detachable probe switch is not already triggered."""
        time = self.toolhead_compat.get_last_move_time()
        if self.probe_compat.query_endstop(time):
            raise self.gcmd.error("%s: probe switch not closed - probe not"
                                  " attached?" % (self.gcmd.get_command()))
    def _add_probe_offset(self, site):
        """Convert a nozzle XY site to the matching probe XY site."""
        # calculate bed position by using the probe's offsets
        probe_offsets = self.probe_compat.get_offsets()
        probe_site = list(site)
        probe_site[0] -= probe_offsets[0]
        probe_site[1] -= probe_offsets[1]
        return probe_site
    def _set_new_gcode_offset(self, offset):
        """Apply the newly calculated Z offset through Klipper."""
        self.gcode_offset.set_new_offset(offset)

    def calibrate_z(self, switch_offset, nozzle_site, switch_site, bed_site):
        """Run the complete calibration sequence and store the result."""
        # execute start gcode
        self.helper.start_gcode.run_gcode_from_command()
        try:
            # probe the nozzle
            nozzle_zero = self._probe_on_site(self.z_endstop,
                                              nozzle_site,
                                              check_probe=False,
                                              split_xy=True,
                                              wiggle=True)
            # execute switch gcode
            self.helper.switch_gcode.run_gcode_from_command()
            # start probe session
            self.probe_compat.start()
            try:
                # probe switch body
                switch_zero = self._probe_on_site(self.z_endstop,
                                                  switch_site,
                                                  check_probe=True)
                # Probe bed position. Keep the raw trigger Z here, equivalent
                # to modern ProbeResult.test_z. Do not use ProbeResult.bed_z:
                # bed_z subtracts the configured probe z_offset and would
                # shift this calibration formula by that amount.
                probe_site = self._add_probe_offset(bed_site)
                if self.probe_compat.can_probe():
                    probe_zero = self._probe_bed_on_site(probe_site)
                else:
                    probe_endstop = (
                        self.probe_compat.get_legacy_probe_endstop())
                    if probe_endstop is None:
                        raise self.gcmd.error(
                            "%s: probe does not expose an MCU endstop"
                            % (self.gcmd.get_command(),))
                    probe_zero = self._probe_on_site(probe_endstop,
                                                     probe_site,
                                                     check_probe=True)
            finally:
                # end probe session
                try:
                    self.probe_compat.end()
                except Exception:
                    logging.exception("Multi-probe end")
            # calculate the offset
            offset = probe_zero - (switch_zero - nozzle_zero + switch_offset)
            # print result
            self.gcmd.respond_info("%s: bed_probe=%.3f - (switch=%.3f"
                                   " - nozzle=%.3f + switch_offset=%.3f) -->"
                                   " new_offset=%.6f"
                                   % (self.gcmd.get_command(), probe_zero,
                                      switch_zero, nozzle_zero, switch_offset,
                                      offset))
            if abs(offset) > 0.2:
                pos_z_estop = self.helper.position_z_endstop
                new_pos_z_estop = pos_z_estop - offset
                self.gcmd.respond_info("%s: current z axis position_endstop="
                                       "%.3f - new offset=%.6f --> POSSIBLE"
                                       " SUGGESTION: new z axis"
                                       " position_endstop=%.3f"
                                       % (self.gcmd.get_command(),
                                          pos_z_estop, offset,
                                          new_pos_z_estop))
            # check offset margins
            if (offset < self.offset_margins[0]
                or offset > self.offset_margins[1]):
                raise self.gcmd.error("%s: offset %.3f is outside the"
                                      " configured range of min=%.3f and"
                                      " max=%.3f"
                                      % (self.gcmd.get_command(), offset,
                                         self.offset_margins[0],
                                         self.offset_margins[1]))
            # set new offset
            self._set_new_gcode_offset(offset)
            # set states
            self.helper.last_state = True
            self.helper.last_z_offset = offset
        finally:
            # execute end gcode
            self.helper.end_gcode.run_gcode_from_command()
def load_config(config):
    """Klipper entrypoint used to instantiate the plugin."""
    return ZCalibrationHelper(config)
