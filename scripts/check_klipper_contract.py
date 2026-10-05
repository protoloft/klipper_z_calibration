#!/usr/bin/env python3
# Validate Klipper source contracts used by z_calibration.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import argparse
import ast
import pathlib
import sys


class ContractError(Exception):
    """Raised when an expected upstream source file cannot be inspected."""

    pass


PROFILE_VALIDATORS = []

GENERIC_CARTESIAN_PATH = 'klippy/kinematics/generic_cartesian.py'
# Classic kinematics whose rails the plugin reads at connect time. Kalico
# and older Klipper do not ship every file, so only present files are
# checked; the firmware checkouts always contain cartesian.py.
CLASSIC_KINEMATICS_PATHS = [
    'klippy/kinematics/cartesian.py',
    'klippy/kinematics/corexy.py',
    'klippy/kinematics/corexz.py',
    'klippy/kinematics/delta.py',
]


def probe_profile(name):
    """Register a supported probe compatibility profile validator."""

    def register(func):
        """Store the decorated profile validator."""
        PROFILE_VALIDATORS.append((name, func))
        return func
    return register


def read_source(root, relpath):
    """Read and parse a Klipper source file."""
    path = pathlib.Path(root) / relpath
    if not path.is_file():
        raise ContractError("missing %s" % (relpath,))
    source = path.read_text(encoding='utf-8')
    return source, ast.parse(source, filename=str(path))


def read_existing_sources(root, relpaths):
    """Read every existing source from a fallback path list."""
    sources = []
    for relpath in relpaths:
        try:
            sources.append(read_source(root, relpath))
        except ContractError:
            pass
    if not sources:
        raise ContractError("missing one of %s" % (', '.join(relpaths),))
    return sources


def any_has_probe_result(sources):
    """Return whether any parsed source defines ProbeResult."""
    for _source, tree in sources:
        if has_class(tree, 'ProbeResult') or has_assignment(tree,
                                                           'ProbeResult'):
            return True
    return False


def has_class(tree, class_name):
    """Return whether an AST contains a class definition."""
    return any(isinstance(node, ast.ClassDef) and node.name == class_name
               for node in ast.walk(tree))


def has_function(tree, function_name):
    """Return whether an AST contains a function definition."""
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == function_name for node in ast.walk(tree))


def function_calls(tree, class_name, function_name, callee_name):
    """Return whether a method calls a named function or method."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if child.name != function_name:
                continue
            for call in ast.walk(child):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = getattr(func, 'attr', None) or getattr(func, 'id', None)
                if name == callee_name:
                    return True
    return False


def function_call_args(tree, class_name, function_name, callee_name):
    """Return (positional, keyword) counts of a call inside a method."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if child.name != function_name:
                continue
            for call in ast.walk(child):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = getattr(func, 'attr', None) or getattr(func, 'id', None)
                if name == callee_name:
                    return len(call.args), len(call.keywords)
    return None


def class_has_function(tree, class_name, function_name):
    """Return whether a class defines a specific method."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and child.name == function_name for child in node.body)
    return False


def has_assignment(tree, target_name):
    """Return whether an AST assigns to a top-level-style name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == target_name:
                return True
    return False


def require(condition, message, errors):
    """Append a contract error message when a condition is false."""
    if not condition:
        errors.append(message)


def format_errors(errors):
    """Prefix raw contract errors for CLI output."""
    return ["Klipper contract failed: %s" % (error,) for error in errors]


def validate_probe_session(root, errors):
    """Validate source markers for modern probe sessions."""
    # This source-level check can prove that a session API exists, but it
    # cannot prove the runtime object returned by start_probe_session().
    # Behavior of the returned session stays covered by wrapper/unit tests.
    _source, tree = read_source(root, 'klippy/extras/probe.py')
    require(class_has_function(tree, 'PrinterProbe', 'start_probe_session'),
            'PrinterProbe.start_probe_session not found', errors)
    require(has_function(tree, 'run_probe'),
            'probe session run_probe not found', errors)
    require(has_function(tree, 'pull_probed_results'),
            'probe session pull_probed_results not found', errors)
    require(has_function(tree, 'end_probe_session'),
            'probe session end_probe_session not found', errors)


def validate_probe_result(root, errors):
    """Validate source markers for raw test-position probe results."""
    # ProbeResult may move between probe/manual_probe sources. This check
    # guards the coordinate contract, but runtime still accepts tuple/list
    # results for older profiles.
    sources = read_existing_sources(root, [
        'klippy/extras/manual_probe.py',
        'klippy/extras/probe.py',
    ])
    source = '\n'.join([item[0] for item in sources])
    require(any_has_probe_result(sources), 'ProbeResult not found', errors)
    for attr in ['test_x', 'test_y', 'test_z', 'bed_z']:
        require(attr in source, 'ProbeResult.%s not found' % (attr,), errors)


def validate_probe_endstop_wrapper(root, errors):
    """Validate source markers for legacy probe endstop wrappers."""
    # This covers the legacy downstream contract where the plugin passes a
    # probe endstop object into homing.probing_move(). A wrapper exposing only
    # query_endstop() is not enough; probing_move needs the MCU endstop surface.
    #
    # Weak point: source markers cannot prove which concrete object is stored
    # in probe.mcu_probe at runtime, or whether the usable MCU endstop is nested
    # as probe.mcu_probe.mcu_endstop. The runtime validator covers that shape.
    source, tree = read_source(root, 'klippy/extras/probe.py')
    require(has_class(tree, 'ProbeEndstopWrapper'),
            'ProbeEndstopWrapper not found', errors)
    for marker in ['mcu_probe', 'get_steppers', 'home_start',
                   'home_wait', 'query_endstop']:
        require(marker in source,
                'ProbeEndstopWrapper.%s marker not found' % (marker,),
                errors)


@probe_profile('modern_probe_result_session')
def validate_modern_probe_result_session(root, errors):
    """Validate the modern ProbeResult session profile."""
    validate_probe_session(root, errors)
    validate_probe_result(root, errors)


@probe_profile('probe_session_xyz_list')
def validate_probe_session_xyz_list(root, errors):
    """Validate a session profile that returns XYZ list results."""
    validate_probe_session(root, errors)


@probe_profile('legacy_mcu_endstop_probe')
def validate_legacy_mcu_endstop_probe(root, errors):
    """Validate the legacy MCU endstop probing profile."""
    # Keep this profile narrow: it validates the old fallback path only when
    # the modern probe-session profiles are unavailable. A Klipper version can
    # pass a modern profile while still changing legacy wrapper internals; that
    # is acceptable as long as z_calibration uses the modern runtime path.
    source, tree = read_source(root, 'klippy/extras/probe.py')
    require(has_class(tree, 'PrinterProbe'), 'PrinterProbe not found', errors)
    require(class_has_function(tree, 'PrinterProbe', 'multi_probe_begin'),
            'PrinterProbe.multi_probe_begin not found', errors)
    require(class_has_function(tree, 'PrinterProbe', 'multi_probe_end'),
            'PrinterProbe.multi_probe_end not found', errors)
    require(class_has_function(tree, 'PrinterProbe', 'get_offsets'),
            'PrinterProbe.get_offsets not found', errors)
    has_legacy_defaults = (
        'sample_count' in source and 'samples_tolerance' in source
        and 'samples_retries' in source and 'lift_speed' in source
        and 'samples_result' in source and 'z_offset' in source)
    require(has_legacy_defaults or has_function(tree, 'get_probe_params'),
            'probe defaults are not exposed', errors)
    if not class_has_function(tree, 'PrinterProbe', 'run_probe'):
        validate_probe_endstop_wrapper(root, errors)
    require('mcu_probe' in source, 'PrinterProbe.mcu_probe not found', errors)
    require('query_endstop' in source,
            'probe endstop query path not found', errors)


def validate_homing(root, errors):
    """Validate source markers for homing.probing_move."""
    _source, tree = read_source(root, 'klippy/extras/homing.py')
    require(has_function(tree, 'probing_move'),
            'homing.probing_move not found', errors)


def validate_bed_mesh(root, errors):
    """Validate source markers for bed mesh zero-reference lookup."""
    source, _tree = read_source(root, 'klippy/extras/bed_mesh.py')
    markers = [
        'zero_reference_position',
        'zero_ref_pos',
        'probe_mgr',
        'relative_reference_index',
    ]
    require(any(marker in source for marker in markers),
            'bed_mesh zero reference path not found', errors)


def validate_mcu(root, errors):
    """Validate source markers for MCU_endstop."""
    _source, tree = read_source(root, 'klippy/mcu.py')
    require(has_class(tree, 'MCU_endstop'), 'MCU_endstop not found', errors)


def validate_stepper(root, errors):
    """Validate source markers for rail endstop access."""
    # The rail that registered the calibration endstop is the Z rail whose
    # homing settings are cached. The rail class is named PrinterRail in
    # older Klipper and Kalico and GenericPrinterRail in current Klipper,
    # so only the method itself can be required here.
    source, tree = read_source(root, 'klippy/stepper.py')
    require(has_function(tree, 'get_endstops'),
            'rail get_endstops not found', errors)
    # The rail keeps the very object it hands to query_endstops. Only that
    # identity makes the endstop looked up by name comparable to the
    # endstops of a homed rail.
    require('self.endstops.append((mcu_endstop' in source,
            'rail endstop list registration not found', errors)
    require('register_endstop(mcu_endstop' in source,
            'query_endstops registration of the rail endstop not found',
            errors)
    # A plugin-owned endstop has to attach the Z steppers itself. Klipper
    # selects them the same way in probe.LookupZSteppers; an endstop
    # without steppers cannot stop a probing move.
    require(class_has_function(tree, 'MCU_stepper', 'is_active_axis'),
            'stepper is_active_axis not found', errors)


def validate_pins(root, errors):
    """Validate source markers for the plugin-owned calibration endstop."""
    # An optional 'endstop_pin' makes the plugin set up its own MCU endstop
    # on a plain pin, the way tools_calibrate does. Sharing that pin with
    # another consumer requires allow_multi_use_pin(), because lookup_pin()
    # rejects an already active pin otherwise.
    source, tree = read_source(root, 'klippy/pins.py')
    require(class_has_function(tree, 'PrinterPins', 'setup_pin'),
            'pins setup_pin not found', errors)
    require(class_has_function(tree, 'PrinterPins', 'allow_multi_use_pin'),
            'pins allow_multi_use_pin not found', errors)
    # allow_multi_use_pin() parses the descriptor without can_invert or
    # can_pullup, so it only accepts a bare pin name. That is why
    # PinEndstop strips the modifiers before calling it.
    require(function_call_args(tree, 'PrinterPins', 'allow_multi_use_pin',
                               'parse_pin') == (1, 0),
            'allow_multi_use_pin no longer parses a bare pin name', errors)
    # The set of characters a bare pin name must not contain, matched without
    # the surrounding quotes because Kalico is formatted with double ones. A
    # new modifier here means _PIN_MODIFIERS in klipper_compat.py needs it too.
    require('^~!:' in source, 'pin modifier set not found', errors)
    # The own endstop is registered so that QUERY_ENDSTOPS keeps showing it.
    _qsource, qtree = read_source(root, 'klippy/extras/query_endstops.py')
    require(class_has_function(qtree, 'QueryEndstops', 'register_endstop'),
            'query_endstops register_endstop not found', errors)


def validate_generic_cartesian(root, errors):
    """Validate source markers for generic_cartesian Z endstop lookup."""
    # generic_cartesian is newer than the supported Klipper baseline and does
    # not exist in Kalico, so a missing kinematic file is not a failure. The
    # carriage lookup only has to hold where the kinematics is available.
    if not (pathlib.Path(root) / GENERIC_CARTESIAN_PATH).is_file():
        return
    source, tree = read_source(root, GENERIC_CARTESIAN_PATH)
    require(class_has_function(tree, 'MainCarriage', 'get_axis'),
            'MainCarriage.get_axis not found', errors)
    require(class_has_function(tree, 'MainCarriage', 'get_rail'),
            'MainCarriage.get_rail not found', errors)
    # The Z carriage is picked by axis index, so the axis order is part of
    # the contract. A reordered list would silently select another axis.
    require("VALID_AXES = ['x', 'y', 'z']" in source,
            'kinematics VALID_AXES order not found', errors)
    # Match the attribute, not the local variable of the same name, so that
    # a renamed attribute is not covered by the loader internals.
    require('self.primary_carriages' in source,
            'kinematics primary_carriages not found', errors)
    _stepper_source, stepper_tree = read_source(root, 'klippy/stepper.py')
    require(class_has_function(stepper_tree, 'GenericPrinterRail',
                               'get_endstops'),
            'GenericPrinterRail.get_endstops not found', errors)
    # The carriage registers its own endstop in __init__, before any stepper
    # or extra carriage can append one. Only that makes the first rail
    # endstop the primary Z endstop, which is what the lookup returns.
    require(function_calls(stepper_tree, 'GenericPrinterRail', '__init__',
                           'lookup_endstop'),
            'rail primary endstop registration not found', errors)


def validate_classic_kinematics(root, errors):
    """Validate source markers for reading rails from the kinematics."""
    # Klipper homes a probe:z_virtual_endstop Z through a probe session
    # since 2026-05 (homing._do_home_z_via_probe) without firing
    # homing:home_rails_end, so the Z rail settings are read straight from
    # the kinematics at connect time. Classic kinematics keep their rails
    # in a 'rails' attribute by convention; generic_cartesian reaches them
    # through its carriages, which validate_generic_cartesian covers.
    for relpath in CLASSIC_KINEMATICS_PATHS:
        if not (pathlib.Path(root) / relpath).is_file():
            continue
        source, _tree = read_source(root, relpath)
        require('self.rails' in source,
                '%s rails attribute not found' % (relpath,), errors)


def validate_gcode_macro(root, errors):
    """Validate source markers for configured G-Code template hooks."""
    source, tree = read_source(root, 'klippy/extras/gcode_macro.py')
    require(class_has_function(tree, 'PrinterGCodeMacro', 'load_template'),
            'PrinterGCodeMacro.load_template not found', errors)
    require(has_function(tree, 'run_gcode_from_command'),
            'template run_gcode_from_command not found', errors)
    require('create_template_context' in source,
            'template create_template_context not found', errors)


def validate_baseline(root):
    """Validate non-profile contracts required by all supported profiles."""
    errors = []
    try:
        validate_homing(root, errors)
        validate_bed_mesh(root, errors)
        validate_mcu(root, errors)
        validate_gcode_macro(root, errors)
        validate_stepper(root, errors)
        validate_pins(root, errors)
        validate_generic_cartesian(root, errors)
        validate_classic_kinematics(root, errors)
    except ContractError as err:
        errors.append(str(err))
    return errors


def probe_profile_errors(root):
    """Return matching probe profiles and per-profile failures."""
    profile_errors = []
    matches = []
    for name, validator in PROFILE_VALIDATORS:
        errors = []
        try:
            validator(root, errors)
        except ContractError as err:
            errors.append(str(err))
        if not errors:
            matches.append(name)
        else:
            profile_errors.append((name, errors))
    return matches, profile_errors


def get_contract_profiles(root):
    """Return supported profile names for a Klipper checkout."""
    baseline_errors = validate_baseline(root)
    if baseline_errors:
        return []
    matches, _profile_errors = probe_profile_errors(root)
    return matches


def check_klipper_contract(root):
    """Return formatted contract errors for a Klipper checkout."""
    baseline_errors = validate_baseline(root)
    if baseline_errors:
        return format_errors(baseline_errors)
    matches, profile_errors = probe_profile_errors(root)
    if matches:
        return []
    errors = ['no supported probe compatibility profile found']
    for name, missing in profile_errors:
        errors.append("%s missing: %s" % (name, '; '.join(missing)))
    return format_errors(errors)


def parse_args(argv):
    """Parse source contract checker arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--klipper-path', required=True)
    return parser.parse_args(argv)


def main(argv=None):
    """CLI entrypoint for source contract validation."""
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    errors = check_klipper_contract(args.klipper_path)
    if errors:
        sys.stderr.write('\n'.join(errors) + '\n')
        return 1
    profiles = ', '.join(get_contract_profiles(args.klipper_path))
    sys.stdout.write("Klipper contract checks passed: %s\n" % (profiles,))
    return 0


if __name__ == '__main__':
    sys.exit(main())
