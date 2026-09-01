# Shared fake Klipper/Kalico objects for unit tests.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from collections import namedtuple


class FakeError(Exception):
    """Exception type returned by fake Klipper error factories."""

    pass


class FakeConfigError(FakeError):
    """Error type of config.error() and printer.config_error().

    A distinct type per channel lets tests catch a config error being
    raised from a G-Code handler, where Klipper would report it as an
    internal error instead of a command response.
    """

    pass


class FakeCommandError(FakeError):
    """Error type of gcmd.error() and printer.command_error()."""

    pass


class FakeMCUEndstop:
    """Minimal MCU endstop surface used by probing_move tests.

    A rail attaches its steppers while the config is read, so a real
    endstop that reaches the plugin always reports at least one. An empty
    list is the misconfiguration that RuntimeContractValidator rejects, so
    it belongs to FakeStepperlessMCUEndstop and not to the default shape.
    """

    def __init__(self, steppers=None):
        self.steppers = list(steppers if steppers is not None
                             else [FakeStepper()])

    def get_mcu(self):
        return None

    def add_stepper(self, stepper):
        self.steppers.append(stepper)

    def get_steppers(self):
        return list(self.steppers)

    def home_start(self, *args, **kwargs):
        pass

    def home_wait(self, *args, **kwargs):
        pass

    def query_endstop(self, print_time):
        return False


class FakeStepperlessMCUEndstop(FakeMCUEndstop):
    """Endstop that never had a stepper attached to it."""

    def __init__(self):
        FakeMCUEndstop.__init__(self, [])


class FakeRecordingMCUEndstop(FakeMCUEndstop):
    """MCU endstop that records forwarded calls and returns markers."""

    def __init__(self, steppers=None):
        FakeMCUEndstop.__init__(self, steppers)
        self.calls = []
        self.mcu = object()
        self.add_stepper_result = object()
        self.home_start_result = object()
        self.home_wait_result = object()
        self.query_result = True

    def get_mcu(self):
        self.calls.append(('get_mcu', (), {}))
        return self.mcu

    def add_stepper(self, stepper):
        self.calls.append(('add_stepper', (stepper,), {}))
        self.steppers.append(stepper)
        return self.add_stepper_result

    def get_steppers(self):
        self.calls.append(('get_steppers', (), {}))
        return list(self.steppers)

    def home_start(self, *args, **kwargs):
        self.calls.append(('home_start', args, dict(kwargs)))
        return self.home_start_result

    def home_wait(self, *args, **kwargs):
        self.calls.append(('home_wait', args, dict(kwargs)))
        return self.home_wait_result

    def query_endstop(self, print_time):
        self.calls.append(('query_endstop', (print_time,), {}))
        return self.query_result


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
        return FakeCommandError(message)


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

    def __init__(self, name=None, executions=None):
        self.name = name
        self.calls = 0
        self.contexts = []
        self.exception = None
        self.executions = executions

    def create_template_context(self):
        return {'printer': 'fake'}

    def run_gcode_from_command(self, context=None):
        self.calls += 1
        self.contexts.append(context)
        if self.executions is not None:
            self.executions.append(self.name)
        if self.exception is not None:
            raise self.exception


class FakeGCodeMacro:
    """Creates fake templates for configured macro hooks."""

    def __init__(self):
        self.templates = {}
        self.executions = []

    def load_template(self, config, name, default=None):
        template = FakeTemplate(name, self.executions)
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

    missing = object()

    def get(self, name, default=missing):
        if default is self.missing:
            # Klipper raises its config error for a missing required
            # option instead of returning None.
            if name not in self.values:
                raise self.error("Option '%s' in section '%s' must be"
                                 " specified" % (name, self.get_name()))
            return self.values[name]
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
        return FakeConfigError(message)


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
        self.kinematics = FakeKinematics()

    def get_kinematics(self):
        return self.kinematics

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
        # Klipper returns the full toolhead position, extruder included,
        # not just the three probing axes.
        return list(self.toolhead.position)


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

    def register_endstop(self, mcu_endstop, name):
        self.endstops.append((mcu_endstop, name))


class FakeProbeEndstop:
    """Probe endstop that returns a configurable trigger state."""

    def __init__(self, triggered=False):
        self.triggered = triggered

    def query_endstop(self, print_time):
        return self.triggered


class FakeProbeSession:
    """Probe session with queued results and command capture."""

    def __init__(self, results, end_exception=None, toolhead=None):
        self.results = list(results)
        self.pending = []
        self.run_gcmds = []
        self.start_positions = []
        self.ended = False
        self.end_exception = end_exception
        # With a toolhead the session reproduces what Klipper does to it:
        # a probing move leaves it standing on the trigger position.
        self.toolhead = toolhead

    def run_probe(self, gcmd):
        self.run_gcmds.append(gcmd)
        result = self.results.pop(0)
        if self.toolhead is not None:
            self.start_positions.append(self.toolhead.position[2])
            self.toolhead.position[2] = result.test_z
        self.pending.append(result)

    def pull_probed_results(self):
        results = self.pending
        self.pending = []
        return results

    def start_probe_session(self, gcmd):
        pass

    def end_probe_session(self):
        self.ended = True
        if self.end_exception is not None:
            raise self.end_exception


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


class FakeOldDefaultsProbe:
    """Old probe combining attribute defaults with multi_probe hooks.

    Klipper probes from before 2024-06-10 published their defaults as plain
    attributes instead of get_probe_params()/get_offsets(). This shape has
    the deprecated attributes only, so runtime contract tests can tell the
    legacy branch apart from the modern one. The attributes are set per
    instance so a test can drop a single one.
    """

    def __init__(self):
        self.mcu_probe = FakeMCUEndstop()
        self.sample_count = FakeOldProbe.sample_count
        self.samples_tolerance = FakeOldProbe.samples_tolerance
        self.samples_retries = FakeOldProbe.samples_retries
        self.lift_speed = FakeOldProbe.lift_speed
        self.samples_result = FakeOldProbe.samples_result
        self.z_offset = FakeOldProbe.z_offset
        self.begin_calls = 0
        self.end_calls = 0

    def multi_probe_begin(self):
        self.begin_calls += 1

    def multi_probe_end(self):
        self.end_calls += 1


class FakeProbeWithProbeSession:
    """Old probe exposing a nested probe_session object."""

    def __init__(self):
        self.probe_session = FakeProbeSession([])


class FakePins:
    """Klipper's pins module, reduced to endstop setup."""

    def __init__(self):
        self.allowed_multi_use = []
        self.setup_calls = []
        self.active_pins = {}

    def allow_multi_use_pin(self, pin_desc):
        self.allowed_multi_use.append(pin_desc)

    def setup_pin(self, pin_type, pin_desc):
        # Klipper rejects a second consumer of a pin unless the bare name
        # was allowed for multi use first. Reproduce that, because it is
        # the reason allow_multi_use_pin() has to be called.
        bare = pin_desc.strip().lstrip('^~! ')
        if bare in self.active_pins and bare not in self.allowed_multi_use:
            raise FakeConfigError(
                "pin %s used multiple times in config" % (bare,))
        self.active_pins[bare] = pin_desc
        self.setup_calls.append((pin_type, pin_desc))
        endstop = FakeRecordingMCUEndstop(steppers=[])
        return endstop


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
        self.pins = FakePins()
        self.objects['pins'] = self.pins
        # Klipper allows several handlers per event, and both the plugin
        # and a plugin-owned endstop register their own.
        self.handlers = {}

    def load_object(self, config, name):
        return self.lookup_object(name)

    def lookup_object(self, name, default=missing):
        if name in self.objects:
            return self.objects[name]
        if default is not self.missing:
            return default
        # Klipper raises its config error here, never a KeyError.
        raise self.config_error("Unknown config object '%s'" % (name,))

    def register_event_handler(self, name, handler):
        self.handlers.setdefault(name, []).append(handler)

    def run_event_handlers(self, name, *args):
        """Fire every handler registered for an event, in order."""
        for handler in self.handlers.get(name, []):
            handler(*args)

    def config_error(self, message):
        return FakeConfigError(message)

    def command_error(self, message):
        return FakeCommandError(message)

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
    """Rail of unknown shape that exposes no endstop list.

    Every supported firmware exposes get_endstops() on its rail class, so
    this shape only covers the defensive fallback of HomingCompat and is
    not a rail that Klipper or Kalico actually build.
    """

    position_endstop = 0.0
    homing_speed = 6.0
    second_homing_speed = 2.0
    homing_retract_dist = 1.0
    position_min = -2.0

    def get_steppers(self):
        return [FakeStepper()]


class FakeInactiveRail(FakeRail):
    """Rail of unknown shape whose stepper is not active on Z."""

    def get_steppers(self):
        return [FakeInactiveStepper()]


class FakeEndstopRail(FakeRail):
    """Rail that also reports the endstops registered for it.

    Klipper rails serve both the homing settings of the home_rails_end
    event and their endstop list. Carriage rails of the generic_cartesian
    kinematics have the same shape.
    """

    def __init__(self, endstops=None):
        self.endstops = list(endstops or [])

    def get_endstops(self):
        return list(self.endstops)


class FakeForeignEndstopRail(FakeEndstopRail):
    """Rail with a Z active stepper but an endstop of another axis.

    This is the corexz and hybrid_corexz shape, where the X rail steppers
    report themselves as active on Z. Its homing settings differ from the
    Z rail defaults so that a mix-up is visible in tests.
    """

    position_endstop = 300.0
    homing_speed = 50.0
    second_homing_speed = 25.0
    homing_retract_dist = 5.0
    position_min = 0.0

    def __init__(self, endstops=None):
        FakeEndstopRail.__init__(
            self, endstops or [(FakeMCUEndstop(), 'stepper_x')])


class FakeCarriage:
    """Kinematic carriage that reports its axis and rail."""

    def __init__(self, axis, rail):
        self.axis = axis
        self.rail = rail

    def get_axis(self):
        return self.axis

    def get_rail(self):
        return self.rail


class FakeKinematics:
    """Classic kinematics exposing rails instead of carriages."""

    def __init__(self, rails=None, steppers=None):
        self.rails = list(rails or [])
        # A plugin-owned endstop asks the kinematics for its steppers and
        # attaches every one that is active on Z.
        self.steppers = list(steppers if steppers is not None
                             else [FakeStepper()])

    def get_steppers(self):
        return list(self.steppers)


class FakeGenericCartesianKinematics(FakeKinematics):
    """Kinematics that resolves axes through primary carriages."""

    def __init__(self, carriages=None, steppers=None):
        FakeKinematics.__init__(self, steppers=steppers)
        self.primary_carriages = list(carriages or [])
