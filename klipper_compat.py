# Compatibility helpers and runtime contracts for Klipper/Kalico APIs.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from mcu import MCU_endstop


# Objects passed to homing.probing_move() need the MCU endstop interface, not
# just the query_endstop() surface. Klipper has wrapped probe endstops before,
# so keep this downstream contract explicit and shared by all probe targets.
_PROBING_ENDSTOP_METHODS = [
    'get_steppers',
    'home_start',
    'home_wait',
    'query_endstop',
]


def _missing_probing_endstop_methods(endstop):
    """Return MCU endstop methods missing from a probing target."""
    return [name for name in _PROBING_ENDSTOP_METHODS
            if not callable(getattr(endstop, name, None))]


def _resolve_legacy_probe_endstop(probe):
    """Resolve direct or wrapped probe MCU endstop objects."""
    probe_endstop = getattr(probe, 'mcu_probe', None)
    if probe_endstop is None:
        return None
    if not _missing_probing_endstop_methods(probe_endstop):
        return probe_endstop
    # Newer ProbeEndstopWrapper objects may retain query_endstop() while
    # nesting the MCU endstop needed by homing.probing_move().
    return getattr(probe_endstop, 'mcu_endstop', None)


class PrinterObjectCompat:
    """Centralizes Klipper object lookup assumptions."""

    def __init__(self, printer):
        self.printer = printer

    def lookup_gcode(self):
        """Return the required gcode object."""
        return self.printer.lookup_object('gcode')

    def lookup_gcode_move(self):
        """Return the required gcode_move object."""
        return self.printer.lookup_object('gcode_move')

    def lookup_homing(self):
        """Return the required homing object."""
        return self.printer.lookup_object('homing')

    def lookup_toolhead(self):
        """Return the required toolhead object."""
        return self.printer.lookup_object('toolhead')

    def lookup_probe(self):
        """Return the required probe object."""
        return self.printer.lookup_object('probe')

    def lookup_optional_probe(self):
        """Return the probe object when one is configured."""
        return self.printer.lookup_object('probe', default=None)

    def lookup_safe_z_home(self):
        """Return safe_z_home when present."""
        return self.printer.lookup_object('safe_z_home', default=None)

    def lookup_bed_mesh(self):
        """Return bed_mesh when present."""
        return self.printer.lookup_object('bed_mesh', default=None)

    def load_gcode_macro(self, config):
        """Load Klipper's gcode_macro helper object."""
        return self.printer.load_object(config, 'gcode_macro')

    def load_query_endstops(self, config):
        """Load Klipper's query_endstops helper object."""
        return self.printer.load_object(config, 'query_endstops')


class RuntimeContractValidator:
    """Validates live Klipper objects before calibration can run."""

    # Runtime validation is deliberately side-effect free: no moves, no
    # endstop queries, and no probe session start. It catches live object shape
    # mismatches early, while behavior inside created sessions/results remains
    # covered by focused tests and the source contract checker.
    def __init__(self, printer, probe, section_name, z_endstop=None):
        self.printer = printer
        self.probe = probe
        self.section_name = section_name
        self.z_endstop = z_endstop
        self.objects = PrinterObjectCompat(printer)

    def validate(self):
        """Run all startup runtime compatibility checks."""
        self._validate_homing_probing_move()
        self._validate_z_endstop_probe_target()
        self._validate_toolhead_motion_status()
        self._validate_gcode_offset_command()
        self._validate_probe_defaults()
        self._validate_probe_execution_profile()
        self._validate_legacy_probe_mcu_endstop()
        self._validate_probe_endstop_query()

    def _validate_homing_probing_move(self):
        """Ensure the homing object still exposes probing_move()."""
        topic = 'homing_probing_move'
        homing = self._lookup(topic, self.objects.lookup_homing)
        self._require_callable(homing, 'probing_move', topic)

    def _validate_z_endstop_probe_target(self):
        """Ensure the calibration endstop can be passed to probing_move()."""
        if self.z_endstop is None:
            return
        # The Z endstop is always passed into homing.probing_move(), so it must
        # satisfy the downstream probing target contract at startup.
        self._require_probing_endstop(self.z_endstop,
                                      'z_endstop_probe_target')

    def _validate_toolhead_motion_status(self):
        """Ensure toolhead movement and status methods are available."""
        topic = 'toolhead_motion_status'
        toolhead = self._lookup(topic, self.objects.lookup_toolhead)
        for attr in ['get_position', 'manual_move', 'get_last_move_time',
                     'get_status']:
            self._require_callable(toolhead, attr, topic)

    def _validate_gcode_offset_command(self):
        """Ensure G-Code offset commands can still be synthesized."""
        topic = 'gcode_offset_command'
        gcode = self._lookup(topic, self.objects.lookup_gcode)
        gcode_move = self._lookup(topic, self.objects.lookup_gcode_move)
        self._require_callable(gcode, 'create_gcode_command', topic)
        self._require_callable(gcode_move, 'cmd_SET_GCODE_OFFSET', topic)

    def _validate_probe_defaults(self):
        """Ensure probe defaults can be read from a supported API shape."""
        topic = 'probe_defaults'
        legacy_attrs = [
            'sample_count',
            'samples_tolerance',
            'samples_retries',
            'lift_speed',
            'samples_result',
            'z_offset',
        ]
        if all(hasattr(self.probe, attr) for attr in legacy_attrs):
            return
        if (self._has_callable(self.probe, 'get_probe_params')
            and self._has_callable(self.probe, 'get_offsets')):
            return
        self._fail(topic, 'probe defaults API is not supported')

    def _validate_probe_execution_profile(self):
        """Ensure the probe exposes one supported probing profile."""
        topic = 'probe_execution_profile'
        if self._has_callable(self.probe, 'start_probe_session'):
            return
        if (self._has_callable(self.probe, 'multi_probe_begin')
            and self._has_callable(self.probe, 'multi_probe_end')):
            return
        session = getattr(self.probe, 'probe_session', None)
        if (session is not None
            and self._has_callable(session, 'start_probe_session')
            and self._has_callable(session, 'end_probe_session')):
            return
        self._fail(topic, 'probe execution API is not supported')

    def _validate_legacy_probe_mcu_endstop(self):
        """Ensure legacy probe fallback has a usable MCU endstop."""
        if self._has_callable(self.probe, 'start_probe_session'):
            return
        topic = 'legacy_probe_mcu_endstop'
        # Legacy probing falls back to passing the probe endstop into
        # homing.probing_move(). Validate the resolved object, not only
        # probe.mcu_probe, because Klipper may wrap it.
        probe_endstop = _resolve_legacy_probe_endstop(self.probe)
        if probe_endstop is None:
            self._fail(topic, 'probe MCU endstop is not available')
        self._require_probing_endstop(probe_endstop, topic)

    def _validate_probe_endstop_query(self):
        """Ensure probe attach checks can query an endstop."""
        topic = 'probe_endstop_query'
        # Query support is separate from probing_move support. A wrapper can
        # expose query_endstop() while lacking the MCU endstop methods.
        for candidate in self._query_endstop_candidates():
            if self._has_callable(candidate, 'query_endstop'):
                return
        self._fail(topic, 'probe endstop query API is not supported')

    def _query_endstop_candidates(self):
        """Return probe objects that may expose query_endstop()."""
        probe_endstop = getattr(self.probe, 'mcu_probe', None)
        candidates = [self.probe, probe_endstop]
        if probe_endstop is not None:
            candidates.append(getattr(probe_endstop, 'mcu_endstop', None))
        return [candidate for candidate in candidates if candidate is not None]

    def _lookup(self, topic, lookup_func):
        """Translate lookup failures into named contract failures."""
        try:
            return lookup_func()
        except Exception as err:
            self._fail(topic, 'object lookup failed: %s' % (err,))

    def _require_callable(self, obj, attr, topic):
        """Fail a contract when an expected method is unavailable."""
        if not self._has_callable(obj, attr):
            self._fail(topic, '%s.%s is not callable'
                       % (obj.__class__.__name__, attr))

    def _require_probing_endstop(self, endstop, topic):
        """Fail when an object cannot be passed to probing_move()."""
        missing = _missing_probing_endstop_methods(endstop)
        if missing:
            self._fail(topic, 'missing %s' % (', '.join(missing),))

    def _has_callable(self, obj, attr):
        """Return whether an object exposes a callable attribute."""
        return callable(getattr(obj, attr, None))

    def _fail(self, topic, detail):
        """Raise a Klipper config error for a named runtime contract."""
        message = "Klipper compatibility check failed for %s: %s" % (
            self.section_name, topic)
        if detail:
            message += " (%s)" % (detail,)
        raise self.printer.config_error(message)


def validate_runtime_contract(printer, probe, section_name, z_endstop=None):
    """Validate live Klipper/Kalico objects during plugin startup."""
    RuntimeContractValidator(printer, probe, section_name,
                             z_endstop).validate()


class EndstopWrapper:
    """Forwards the MCU endstop surface expected by probing_move()."""

    def __init__(self, endstop):
        self.mcu_endstop = endstop

    def get_mcu(self):
        """Forward get_mcu() to the wrapped MCU endstop."""
        return self.mcu_endstop.get_mcu()

    def add_stepper(self, stepper):
        """Forward add_stepper() to the wrapped MCU endstop."""
        return self.mcu_endstop.add_stepper(stepper)

    def get_steppers(self):
        """Forward get_steppers() to the wrapped MCU endstop."""
        return self.mcu_endstop.get_steppers()

    def home_start(self, *args, **kwargs):
        """Forward home_start() to the wrapped MCU endstop."""
        return self.mcu_endstop.home_start(*args, **kwargs)

    def home_wait(self, *args, **kwargs):
        """Forward home_wait() to the wrapped MCU endstop."""
        return self.mcu_endstop.home_wait(*args, **kwargs)

    def query_endstop(self, print_time):
        """Forward query_endstop() to the wrapped MCU endstop."""
        return self.mcu_endstop.query_endstop(print_time)


class HomingCompat:
    """Wraps homing and Z endstop API assumptions."""

    def __init__(self, printer):
        self.printer = printer
        self.objects = PrinterObjectCompat(printer)

    def get_z_endstop(self, query_endstops, section_name):
        """Find and wrap the physical Z calibration endstop."""
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
        """Extract Z rail homing settings from a Klipper rail object."""
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
        """Call Klipper's probing move through the homing object."""
        homing = self.objects.lookup_homing()
        return homing.probing_move(mcu_endstop, pos, speed)


class ToolheadCompat:
    """Wraps toolhead movement and status calls."""

    def __init__(self, printer):
        self.printer = printer
        self.objects = PrinterObjectCompat(printer)

    def _toolhead(self):
        """Return the current toolhead object."""
        return self.objects.lookup_toolhead()

    def get_position(self):
        """Return the current toolhead position."""
        return self._toolhead().get_position()

    def manual_move(self, coord, speed):
        """Move the toolhead manually through Klipper."""
        self._toolhead().manual_move(coord, speed)

    def get_last_move_time(self):
        """Return the print time for the last toolhead move."""
        return self._toolhead().get_last_move_time()

    def is_axis_homed(self, axis):
        """Return whether Klipper currently reports an axis as homed."""
        eventtime = self.printer.get_reactor().monotonic()
        homed_axes = self._toolhead().get_status(eventtime).get(
            'homed_axes', '')
        return axis in homed_axes


class BedMeshCompat:
    """Reads bed mesh zero-reference positions across Klipper versions."""

    def get_zero_reference_position(self, mesh):
        """Return the mesh zero reference position when configured."""
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
    """Adapts modern and legacy Klipper probe APIs."""

    def __init__(self, helper, probe, gcmd=None):
        self.helper = helper
        self.probe = probe
        self.gcmd = gcmd
        self.gcode = helper.gcode
        self.session = None

    def get_config_defaults(self):
        """Return probe defaults used by z_calibration config fallbacks."""
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
        """Return configured probe offsets."""
        return self.probe.get_offsets()

    def start(self):
        """Start the best supported probe session/profile."""
        if hasattr(self.probe, 'start_probe_session'):
            self.session = self.probe.start_probe_session(self.gcmd)
        elif hasattr(self.probe, 'multi_probe_begin'):
            # TODO: remove: deprecated since 2024-06-10
            self.probe.multi_probe_begin()
        else:
            # TODO: remove: deprecated since 2024-06-10
            self.probe.probe_session.start_probe_session(None)

    def end(self):
        """End the active probe session/profile."""
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
        """Query the first supported probe endstop candidate."""
        for probe_endstop in self._query_endstop_candidates():
            query_endstop = getattr(probe_endstop, 'query_endstop', None)
            if query_endstop is not None:
                return query_endstop(print_time)
        raise self.gcmd.error("%s: probe does not support endstop queries"
                              % (self.gcmd.get_command(),))

    def can_probe(self):
        """Return whether a modern session can run probe samples."""
        return self.session is not None and hasattr(self.session, 'run_probe')

    def get_legacy_probe_endstop(self):
        """Return the MCU endstop used by the legacy fallback path."""
        probe_endstop = getattr(self.probe, 'mcu_probe', None)
        if probe_endstop is None:
            return None
        if hasattr(probe_endstop, 'get_steppers'):
            return probe_endstop
        return getattr(probe_endstop, 'mcu_endstop', None)

    def run_probe(self, speed, samples=None):
        """Run a probe sample through a modern probe session."""
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
        """Extract the raw trigger/test position from a probe result."""
        if hasattr(probe_result, 'test_z'):
            return [probe_result.test_x, probe_result.test_y,
                    probe_result.test_z]
        if len(probe_result) >= 6:
            return [probe_result[3], probe_result[4], probe_result[5]]
        return probe_result[:3]

    def _create_probe_gcmd(self, speed, samples):
        """Create the synthetic PROBE command used by probe sessions."""
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
        """Return probe objects that may expose query_endstop()."""
        probe_endstop = getattr(self.probe, 'mcu_probe', None)
        candidates = [self.probe, probe_endstop]
        if probe_endstop is not None:
            candidates.append(getattr(probe_endstop, 'mcu_endstop', None))
        return [candidate for candidate in candidates if candidate is not None]


class GCodeOffsetCompat:
    """Applies new Z offsets through Klipper's G-Code move object."""

    def __init__(self, gcode, gcode_move):
        self.gcode = gcode
        self.gcode_move = gcode_move

    def set_new_offset(self, offset):
        """Reset the old Z offset and apply the newly calculated adjust."""
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET",
                                                      "SET_GCODE_OFFSET",
                                                      {'Z': 0.0})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
        gcmd_offset = self.gcode.create_gcode_command("SET_GCODE_OFFSET",
                                                      "SET_GCODE_OFFSET",
                                                      {'Z_ADJUST': offset})
        self.gcode_move.cmd_SET_GCODE_OFFSET(gcmd_offset)
