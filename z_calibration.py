import logging

# [z_calibration]
# switch_offset: 0.675 # D2F-5: about 0.5, SSG-5H: about 0.7
# max_deviation: 1.0   # max deviation in mm
# speed: 80
# probe_nozzle_x: 206 
# probe_nozzle_y: 300
# probe_switch_x: 211
# probe_switch_y: 281
# probe_bed_x: 150
# probe_bed_y: 150

class ZCalibrationHelper:
    def __init__(self, config):
        self.state = None
        self.z_endstop = None
        self.z_homing = None
        self.last_state = False
        self.last_z_offset = 0.
        self.probing_speed = 3.
        self.probing_retract_dist = 5.
        self.probing_position_min = 0.
        self.probing_lift_speed = 50
        self.probing_sample_count = 5
        self.probing_tolerance = 0.006
        self.probing_retries = 10
        self.probing_clearance = 10
        self.probing_result = 'median'

        self.config = config
        self.printer = config.get_printer()
        self.switch_offset = config.getfloat('switch_offset', 0.0, above=0.)
        self.max_deviation = config.getfloat('max_deviation', 1.0, above=0.)
        self.speed = config.getfloat('speed', 100.0, above=0.)
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
        self.probing_sample_count = probe.sample_count
        self.probing_tolerance = probe.samples_tolerance
        self.probing_retries = probe.samples_retries
        self.probing_lift_speed = probe.lift_speed
        self.probing_clearance = probe.z_offset * 2
        self.probing_result = probe.samples_result

    def handle_home_rails_end(self, homing_state, rails):
        # get z homing position
        for rail in rails:
            if rail.get_steppers()[0].is_active_axis('z'):
                self.z_homing = rail.get_tag_position()
                # get homing settings from z rail
                self.probing_speed = rail.second_homing_speed
                self.probing_retract_dist = rail.homing_retract_dist
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
        state = CalibrationState(self, gcmd)
        state.calibrate_z()

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

    def _probe_on_z_endstop(self, site):
        # move to position
        pos = self.toolhead.get_position()
        self.toolhead.manual_move([None, None, pos[2] + self.helper.probing_clearance], self.helper.probing_lift_speed)
        self.toolhead.manual_move(list(site), self.helper.speed)

        retries = 0
        positions = []
        while len(positions) < self.helper.probing_sample_count:
            # probe
            pos = self.toolhead.get_position()
            pos[2] = self.helper.probing_position_min
            curpos = self.phoming.probing_move(self.z_endstop, pos, self.helper.probing_speed)
            self.helper.gcode.respond_info("probe at %.3f,%.3f is z=%.6f"
                % (curpos[0], curpos[1], curpos[2]))
            positions.append(curpos[:3])
            # check tolerance
            z_positions = [p[2] for p in positions]
            if max(z_positions) - min(z_positions) > self.helper.probing_tolerance:
                if retries >= self.helper.probing_retries:
                    raise self.gcmd.error("Probe samples exceed samples_tolerance")
                self.gcmd.respond_info("Probe samples exceed tolerance. Retrying...")
                retries += 1
                positions = []
            # retract
            self.toolhead.manual_move([None, None, curpos[2] + self.helper.probing_retract_dist], self.probe.lift_speed)
        # calculate result
        if self.helper.probing_result == 'median':
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
