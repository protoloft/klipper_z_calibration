import logging

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
        self.probing_samples = config.getint('samples', None, minval=1)
        self.probing_samples_tolerance = config.getfloat('samples_tolerance', None, above=0.)
        self.probing_samples_tolerance_retries = config.getint('samples_tolerance_retries', None, minval=0)
        atypes = {'none': None, 'median': 'median', 'average': 'average'}
        self.probing_samples_result = config.getchoice('samples_result', atypes, 'none')
        self.probing_lift_speed = config.getfloat('lift_speed', None, above=0.)
        self.probing_clearance = config.getfloat('clearance', None, above=0.)
        self.probing_speed = config.getfloat('probing_speed', None, above=0.)
        self.probing_second_speed = config.getfloat('probing_second_speed', None, above=0.)
        self.probing_retract_dist = config.getfloat('probing_retract_dist', None, above=0.)
        self.probing_position_min = config.getfloat('position_min', None)
        self.probing_first_fast = config.getboolean('probing_first_fast', False)
        self.probe_nozzle_site = [
            config.getfloat('probe_nozzle_x'),
            config.getfloat('probe_nozzle_y'),
            None,
        ]
        self.probe_switch_site = [
            config.getfloat('probe_switch_x'),
            config.getfloat('probe_switch_y'),
            None,
        ]
        self.probe_bed_site = [
            config.getfloat('probe_bed_x'),
            config.getfloat('probe_bed_y'),
            None,
        ]

        self.query_endstops = self.printer.load_object(config, 'query_endstops')

        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("homing:home_rails_end",
                                            self.handle_home_rails_end)

        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('CALIBRATE_Z', self.cmd_CALIBRATE_Z,
                                    desc=self.cmd_CALIBRATE_Z_help)

    def get_status(self, eventtime):
        return {'last_query': self.last_state,
                'last_z_offset': self.last_z_offset}

    def handle_connect(self):
        # get z-endstop
        for endstop, name in self.query_endstops.endstops:
            if name == 'z':
                self.z_endstop = EndstopWrapper(self.config, endstop)
        # get probing settings
        probe = self.printer.lookup_object('probe')
        if self.probing_samples is None:
            self.probing_samples = probe.sample_count
        if self.probing_samples_tolerance is None:
            self.probing_samples_tolerance = probe.samples_tolerance
        if self.probing_samples_tolerance_retries is None:
            self.probing_samples_tolerance_retries = probe.samples_retries
        if self.probing_lift_speed is None:
            self.probing_lift_speed = probe.lift_speed
        if self.probing_clearance is None:
            self.probing_clearance = probe.z_offset * 2
        if self.probing_samples_result is None:
            self.probing_samples_result = probe.samples_result

    def handle_home_rails_end(self, homing_state, rails):
        # get z homing position
        for rail in rails:
            if rail.get_steppers()[0].is_active_axis('z'):
                self.z_homing = rail.get_tag_position()
                # get homing settings from z rail
                if self.probing_speed is None:
                    self.probing_speed = rail.homing_speed
                if self.probing_second_speed is None:
                    self.probing_second_speed = rail.second_homing_speed
                if self.probing_retract_dist is None:
                    self.probing_retract_dist = rail.homing_retract_dist
                if self.probing_position_min is None:
                    self.probing_position_min = rail.position_min
            
    def _build_config(self):
        pass

    cmd_CALIBRATE_Z_help = "Automatically calibrates the nozzles offset to the print surface"

    def cmd_CALIBRATE_Z(self, gcmd):
        if self.state is not None:
            raise self.printer.command_error("Already performing CALIBRATE_Z")
            return
        # check if probe is attached and the switch is closed
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        if self.z_endstop.query_endstop(print_time):
            raise self.printer.command_error("Probe switch not closed - Probe not attached?")
            return
        self._log_config()
        state = CalibrationState(self, gcmd)
        state.calibrate_z()

    def _log_config(self):
        logging.debug(("Z-CALIBRATION: switch_offset=%.3f, max_deviation=%.3f, speed=%.3f, "
            "samples=%i, samples_tolerance=%.3f, samples_tolerance_retries=%i, samples_result=%s, "
            "lift_speed=%.3f, clearance=%.3f, probing_speed=%.3f, probing_second_speed=%.3f, "
            "probing_retract_dist=%.3f, position_min=%.3f, probe_nozzle_x=%.3f, probe_nozzle_y=%.3f, "
            "probe_switch_x=%.3f, probe_switch_y=%.3f, probe_bed_x=%.3f, probe_bed_y=%.3f")
            % (self.switch_offset, self.max_deviation, self.speed, self.probing_samples,
            self.probing_samples_tolerance, self.probing_samples_tolerance_retries,
            self.probing_samples_result, self.probing_lift_speed, self.probing_clearance,
            self.probing_speed, self.probing_second_speed, self.probing_retract_dist,
            self.probing_position_min, self.probe_nozzle_site[0], self.probe_nozzle_site[1],
            self.probe_switch_site[0], self.probe_switch_site[1], self.probe_bed_site[0],
            self.probe_bed_site[1]))

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
        self.phoming = helper.printer.lookup_object('homing')
        self.probe = helper.printer.lookup_object('probe')
        self.toolhead = helper.printer.lookup_object('toolhead')
        self.gcode_move = helper.printer.lookup_object('gcode_move')


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

    def _probe(self, mcu_endstop, z_position, speed):
            pos = self.toolhead.get_position()
            pos[2] = z_position
            # probe
            curpos = self.phoming.probing_move(mcu_endstop, pos, speed)
            # retract
            self.toolhead.manual_move([None, None, curpos[2] + self.helper.probing_retract_dist], self.probe.lift_speed)
            self.helper.gcode.respond_info("probe at %.3f,%.3f is z=%.6f"
                % (curpos[0], curpos[1], curpos[2]))
            return curpos
        
    def _probe_on_z_endstop(self, site):
        # move to position
        pos = self.toolhead.get_position()
        self.toolhead.manual_move([None, None, pos[2] + self.helper.probing_clearance], self.helper.probing_lift_speed)
        self.toolhead.manual_move(list(site), self.helper.speed)

        if self.helper.probing_first_fast:
            # first probe just to get down faster
            self._probe(self.z_endstop, self.helper.probing_position_min, self.helper.probing_speed)

        retries = 0
        positions = []
        while len(positions) < self.helper.probing_samples:
            # probe with second probing speed
            curpos = self._probe(self.z_endstop, self.helper.probing_position_min, self.helper.probing_second_speed)
            positions.append(curpos[:3])
            # check tolerance
            z_positions = [p[2] for p in positions]
            if max(z_positions) - min(z_positions) > self.helper.probing_samples_tolerance:
                if retries >= self.helper.probing_samples_tolerance_retries:
                    raise self.gcmd.error("Probe samples exceed samples_tolerance")
                self.gcmd.respond_info("Probe samples exceed tolerance. Retrying...")
                retries += 1
                positions = []
        # calculate result
        if self.helper.probing_samples_result == 'median':
            return self._calc_median(positions)[2]
        return self._calc_mean(positions)[2]

    def _probe_on_bed(self, bed_site):
        # calculate bed position by using the probe's offsets
        probe_offsets = self.probe.get_offsets()
        probe_site = list(bed_site)
        probe_site[0] -= probe_offsets[0]
        probe_site[1] -= probe_offsets[1]
        # move to probing position
        pos = self.toolhead.get_position()
        self.toolhead.manual_move([None, None, pos[2] + self.helper.probing_clearance], self.helper.probing_lift_speed)
        self.toolhead.manual_move(probe_site, self.helper.speed)
        if self.helper.probing_first_fast:
            # fast probe to get down - may be not the best way to get the mcu_probe..
            self._probe(self.probe.mcu_probe, self.probe.z_position, self.helper.probing_speed)
        # probe it
        return self.probe.run_probe(self.gcmd)[2]

    def _set_new_gcode_offset(self, offset):
        # reset gcode z offset to 0
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET", "SET_GCODE_OFFSET", {'Z': 0.0, 'MOVE': '1'})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
        # set new gcode z offset
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET", "SET_GCODE_OFFSET", {'Z_ADJUST': offset, 'MOVE': '1'})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)

    def calibrate_z(self):
        # probe the nozzle
        nozzle_zero = self._probe_on_z_endstop(self.helper.probe_nozzle_site)
        # probe the probe-switch
        switch_zero = self._probe_on_z_endstop(self.helper.probe_switch_site)
        # probe position on bed
        probe_zero = self._probe_on_bed(self.helper.probe_bed_site)

        # move up
        self.toolhead.manual_move([None, None, probe_zero + self.helper.probing_clearance], self.helper.probing_lift_speed)

        # calculate the offset
        offset = probe_zero - (switch_zero - nozzle_zero + self.helper.switch_offset)
        # print result
        self.gcmd.respond_info("Z-CALIBRATION: ENDSTOP=%.3f NOZZLE=%.3f SWITCH=%.3f PROBE=%.3f --> OFFSET=%.6f" 
                % (self.helper.z_homing, nozzle_zero, switch_zero, probe_zero, offset))

        # check max deviation
        if abs(offset) > self.helper.max_deviation:
            raise self.helper.printer.command_error("Offset is larger as allowed: OFFSET=%.3f MAX_DEVIATION=%.3f" 
                % (offset, self.helper.max_deviation))
            return

        # set new offset
        self._set_new_gcode_offset(offset)

        # set states
        self.helper.last_state = True
        self.helper.last_z_offset = offset

def load_config(config):
    return ZCalibrationHelper(config)
