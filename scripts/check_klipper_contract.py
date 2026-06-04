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


def validate_baseline(root):
    """Validate non-profile contracts required by all supported profiles."""
    errors = []
    try:
        validate_homing(root, errors)
        validate_bed_mesh(root, errors)
        validate_mcu(root, errors)
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
    args = parse_args(argv or sys.argv[1:])
    errors = check_klipper_contract(args.klipper_path)
    if errors:
        sys.stderr.write('\n'.join(errors) + '\n')
        return 1
    profiles = ', '.join(get_contract_profiles(args.klipper_path))
    sys.stdout.write("Klipper contract checks passed: %s\n" % (profiles,))
    return 0


if __name__ == '__main__':
    sys.exit(main())
