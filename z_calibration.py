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
        self.probing_speed = 5.0
        self.second_probing_speed = self.probing_speed / 2.
        self.probing_retract_dist = 5.
        self.probing_position_min = 0.

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
	for endstop, name in self.query_endstops.endstops:
            if name == 'z':
                self.z_endstop = EndstopWrapper(self.config, endstop)

    def handle_home_rails_end(self, homing_state, rails):
        # get z homing position
        for rail in rails:
            if rail.get_steppers()[0].is_active_axis('z'):
                self.z_homing = rail.get_tag_position()
                # get homing settings from z rail
                self.probing_speed = rail.homing_speed
                self.second_probing_speed = rail.second_homing_speed
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
        state.start()

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
        self.probe = probe = helper.printer.lookup_object('probe')
        self.toolhead = helper.printer.lookup_object('toolhead')
        self.gcode_move = helper.printer.lookup_object('gcode_move')
        self.z_speed = self.probe.lift_speed
        self.probe_clearance = self.probe.z_offset * 2

    def probe_z_endstop(self):
        pos = self.toolhead.get_position()
        pos[2] = self.helper.probing_position_min
        self.phoming.probing_move(self.z_endstop, pos, self.helper.probing_speed)
        curpos = self.toolhead.get_position()
        self.toolhead.manual_move([None, None, curpos[2] + self.helper.probing_retract_dist], self.probe.lift_speed)
        self.phoming.probing_move(self.z_endstop, pos, self.helper.second_probing_speed)
        return self.toolhead.get_position()[2]

    def start(self):
        # determine nozzle position on z-endstop
        self.toolhead.manual_move(list(self.helper.probe_nozzle_site), self.helper.speed)
        nozzle_zero = self.probe_z_endstop()

        # determine switch position on z-endstop
        self.toolhead.manual_move([None, None, nozzle_zero + self.probe_clearance], self.z_speed)
        self.toolhead.manual_move(list(self.helper.probe_switch_site), self.helper.speed)
        switch_zero = self.probe_z_endstop()
        self.toolhead.manual_move([None, None, switch_zero + self.probe_clearance], self.z_speed)

        # perform probe on bed
        probe_offsets = self.probe.get_offsets()
        bed_site = list(self.helper.probe_bed_site)
        bed_site[0] -= probe_offsets[0]
        bed_site[1] -= probe_offsets[1]
        self.toolhead.manual_move(bed_site, self.helper.speed)
        probe_zero = self.probe.run_probe(self.gcmd)[2]
        self.toolhead.manual_move([None, None, probe_zero + self.probe_clearance], self.z_speed)

        # calculate the offset
        offset = probe_zero - (switch_zero - nozzle_zero + self.helper.switch_offset)

        # print result
        self.gcmd.respond_info("Z-CALIBRATION: ENDSTOP=%.3f NOZZLE=%.3f SWITCH=%.3f PROBE=%.3f --> OFFSET=%.3f" 
                % (self.helper.z_homing, nozzle_zero, switch_zero, probe_zero, offset))

        # check max deviation
        if abs(offset) > self.helper.max_deviation:
            raise self.helper.printer.command_error("Offset is larger as allowed: OFFSET=%.3f MAX_DEVIATION=%.3f" 
                % (offset, self.helper.max_deviation))
            return

        # reset gcode z offset to 0
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET", "SET_GCODE_OFFSET", {'Z': 0.0, 'MOVE': '1'})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
        # set new gcode z offset
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET", "SET_GCODE_OFFSET", {'Z_ADJUST': offset, 'MOVE': '1'})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)

        # set state
        self.helper.last_state = True
        self.helper.last_z_offset = offset

def load_config(config):
    return ZCalibrationHelper(config)

