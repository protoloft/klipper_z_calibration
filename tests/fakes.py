# Shared fake Klipper/Kalico objects for unit tests.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from collections import namedtuple


class FakeError(Exception):
    """Exception type returned by fake Klipper error factories."""

    pass


class FakeMCUEndstop:
    """Minimal MCU endstop surface used by probing_move tests."""

    def get_mcu(self):
        return None

    def add_stepper(self, stepper):
        pass

    def get_steppers(self):
        return []

    def home_start(self, *args, **kwargs):
        pass

    def home_wait(self, *args, **kwargs):
        pass

    def query_endstop(self, print_time):
        return False


ProbeResult = namedtuple(
    'probe_result',
    ['bed_x', 'bed_y', 'bed_z', 'test_x', 'test_y', 'test_z'])


class FakeGcmd:
    """Small G-Code command object with parameter and response capture."""

    def __init__(self, command='CALIBRATE_Z', params=None):
        self.command = command
        self.params = dict(params or {})
        self.responses = []

    def get_command(self):
        return self.command

    def get_command_parameters(self):
        return dict(self.params)

    def get(self, name, default=None):
        return self.params.get(name, default)

    def get_float(self, name, default=None, above=None, minval=None):
        value = self.get(name, default)
        if value is None:
            return None
        value = float(value)
        if above is not None and value <= above:
            raise self.error("invalid float")
        if minval is not None and value < minval:
            raise self.error("invalid float")
        return value

    def get_int(self, name, default=None, minval=None):
        value = self.get(name, default)
        if value is None:
            return None
        value = int(value)
        if minval is not None and value < minval:
            raise self.error("invalid int")
        return value

    def respond_info(self, message):
        self.responses.append(message)

    def error(self, message):
        return FakeError(message)


class FakeGCode:
    """Captures registered commands and synthetic G-Code commands."""

    def __init__(self):
        self.commands = {}
        self.created_commands = []
        self.responses = []

    def register_command(self, name, func, desc=None):
        self.commands[name] = (func, desc)

    def create_gcode_command(self, command, commandline, params):
        gcmd = FakeGcmd(command, params)
        self.created_commands.append(gcmd)
        return gcmd

    def respond_info(self, message):
        self.responses.append(message)


class FakeTemplate:
    """Counts macro template executions."""

    def __init__(self):
        self.calls = 0

    def run_gcode_from_command(self):
        self.calls += 1


class FakeGCodeMacro:
    """Creates fake templates for configured macro hooks."""

    def __init__(self):
        self.templates = {}

    def load_template(self, config, name, default):
        template = FakeTemplate()
        self.templates[name] = template
        return template


class FakeConfig:
    """Provides the subset of Klipper config parsing used by the plugin."""

    def __init__(self, printer, values=None):
        self.printer = printer
        self.values = dict(values or {})

    def get_printer(self):
        return self.printer

    def get_name(self):
        return 'z_calibration'

    def get(self, name, default=None):
        return self.values.get(name, default)

    def getfloat(self, name, default=None, above=None, minval=None):
        value = self.get(name, default)
        if value is None:
            return None
        value = float(value)
        if above is not None and value <= above:
            raise self.error("invalid float")
        if minval is not None and value < minval:
            raise self.error("invalid float")
        return value

    def getint(self, name, default=None, minval=None):
        value = self.get(name, default)
        if value is None:
            return None
        value = int(value)
        if minval is not None and value < minval:
            raise self.error("invalid int")
        return value

    def getboolean(self, name, default=False):
        value = self.get(name, default)
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)

    def getchoice(self, name, choices, default=None):
        value = self.get(name, default)
        if isinstance(choices, dict):
            if value not in choices:
                raise self.error("invalid choice")
            return choices[value]
        if value not in choices:
            raise self.error("invalid choice")
        return value

    def error(self, message):
        return FakeError(message)


class FakeReactor:
    """Provides deterministic reactor time for status checks."""

    def monotonic(self):
        return 123.0


class FakeToolhead:
    """Tracks position, homing state, and requested manual moves."""

    def __init__(self):
        self.position = [0.0, 0.0, 10.0, 0.0]
        self.homed_axes = 'xyz'
        self.moves = []

    def get_position(self):
        return list(self.position)

    def manual_move(self, coord, speed):
        for idx, value in enumerate(coord):
            if value is not None:
                self.position[idx] = value
        self.moves.append((list(coord), speed))

    def get_last_move_time(self):
        return 1.0

    def get_status(self, eventtime):
        return {'homed_axes': self.homed_axes}


class FakeHoming:
    """Returns queued probing results and records probing_move calls."""

    def __init__(self, toolhead):
        self.toolhead = toolhead
        self.results = []
        self.calls = []

    def probing_move(self, endstop, pos, speed):
        self.calls.append((endstop, list(pos), speed))
        result = self.results.pop(0)
        self.toolhead.position[:3] = result[:3]
        return list(result)


class FakeGCodeMove:
    """Captures SET_GCODE_OFFSET command parameters."""

    def __init__(self):
        self.offset_commands = []

    def cmd_SET_GCODE_OFFSET(self, gcmd):
        self.offset_commands.append(gcmd.params)


class FakeQueryEndstops:
    """Exposes a default physical Z endstop entry."""

    def __init__(self):
        self.endstops = [(FakeMCUEndstop(), 'stepper_z')]


class FakeProbeEndstop:
    """Probe endstop that returns a configurable trigger state."""

    def __init__(self, triggered=False):
        self.triggered = triggered

    def query_endstop(self, print_time):
        return self.triggered


class FakeProbeSession:
    """Probe session with queued results and command capture."""

    def __init__(self, results):
        self.results = list(results)
        self.pending = []
        self.run_gcmds = []
        self.ended = False

    def run_probe(self, gcmd):
        self.run_gcmds.append(gcmd)
        self.pending.append(self.results.pop(0))

    def pull_probed_results(self):
        results = self.pending
        self.pending = []
        return results

    def start_probe_session(self, gcmd):
        pass

    def end_probe_session(self):
        self.ended = True


class FakeEmptyProbeSession:
    """Probe session that simulates a missing probe result."""

    def run_probe(self, gcmd):
        pass

    def pull_probed_results(self):
        return []

    def end_probe_session(self):
        pass


class FakeProbe:
    """Modern probe exposing start_probe_session and get_probe_params."""

    def __init__(self, session=None, offsets=(1.0, 2.0, 1.5)):
        self.mcu_probe = FakeProbeEndstop(False)
        self.session = session or FakeProbeSession([])
        self.offsets = offsets

    def get_probe_params(self, gcmd=None):
        return {
            'samples': 1,
            'samples_tolerance': 0.1,
            'samples_tolerance_retries': 0,
            'lift_speed': 5.0,
            'samples_result': 'average',
        }

    def get_offsets(self, gcmd=None):
        return self.offsets

    def start_probe_session(self, gcmd):
        return self.session


class FakeLegacyProbe:
    """Legacy probe exposing multi_probe_begin/end fallback hooks."""

    def __init__(self):
        self.mcu_probe = FakeProbeEndstop(False)
        self.offsets = (1.0, 2.0, 1.5)
        self.begin_calls = 0
        self.end_calls = 0

    def get_probe_params(self):
        return {
            'samples': 1,
            'samples_tolerance': 0.1,
            'samples_tolerance_retries': 0,
            'lift_speed': 5.0,
            'samples_result': 'average',
        }

    def get_offsets(self):
        return self.offsets

    def query_endstop(self, print_time):
        return False

    def multi_probe_begin(self):
        self.begin_calls += 1

    def multi_probe_end(self):
        self.end_calls += 1


class FakeOldProbe:
    """Old probe exposing deprecated default attributes."""

    sample_count = 2
    samples_tolerance = 0.05
    samples_retries = 3
    lift_speed = 7.0
    samples_result = 'median'
    z_offset = 4.0

    def __init__(self):
        self.mcu_probe = FakeProbeEndstop(False)


class FakeProbeWithProbeSession:
    """Old probe exposing a nested probe_session object."""

    def __init__(self):
        self.probe_session = FakeProbeSession([])


class FakePrinter:
    """Printer object registry and error factory used by unit tests."""

    missing = object()

    def __init__(self, probe=None):
        self.reactor = FakeReactor()
        self.gcode = FakeGCode()
        self.toolhead = FakeToolhead()
        self.homing = FakeHoming(self.toolhead)
        self.gcode_move = FakeGCodeMove()
        self.gcode_macro = FakeGCodeMacro()
        self.query_endstops = FakeQueryEndstops()
        self.objects = {
            'gcode': self.gcode,
            'toolhead': self.toolhead,
            'homing': self.homing,
            'gcode_move': self.gcode_move,
            'gcode_macro': self.gcode_macro,
            'query_endstops': self.query_endstops,
            'probe': probe or FakeProbe(),
        }
        self.handlers = {}

    def load_object(self, config, name):
        return self.lookup_object(name)

    def lookup_object(self, name, default=missing):
        if name in self.objects:
            return self.objects[name]
        if default is not self.missing:
            return default
        raise KeyError(name)

    def register_event_handler(self, name, handler):
        self.handlers[name] = handler

    def config_error(self, message):
        return FakeError(message)

    def command_error(self, message):
        return FakeError(message)

    def get_reactor(self):
        return self.reactor

    def send_event(self, name, *args):
        pass


class FakeStepper:
    """Stepper that reports itself as active for Z."""

    def is_active_axis(self, axis):
        return axis == 'z'


class FakeInactiveStepper:
    """Stepper that does not report any active axis."""

    def is_active_axis(self, axis):
        return False


class FakeRail:
    """Z rail exposing homing settings consumed by HomingCompat."""

    position_endstop = 0.0
    homing_speed = 6.0
    second_homing_speed = 2.0
    homing_retract_dist = 1.0
    position_min = -2.0

    def get_steppers(self):
        return [FakeStepper()]


class FakeInactiveRail(FakeRail):
    """Rail whose stepper is not active on Z."""

    def get_steppers(self):
        return [FakeInactiveStepper()]
