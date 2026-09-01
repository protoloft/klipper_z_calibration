# Agent Instructions

This file is for automated coding agents working in this repository.
Human contributor guidance is in `CONTRIBUTING.md`. Maintainer release steps
are in `docs/maintainer-release.md`.

It is the single source of truth for agent instructions. Claude Code does not
read `AGENTS.md` itself, so the repository ships a `CLAUDE.md` that pulls this
file in with an `@AGENTS.md` import. Keep the rules here; do not duplicate
them into `CLAUDE.md`.

## Safety Model

This plugin drives real hardware: it moves the nozzle toward the print bed.
The central calculation is `CalibrationRun.calibrate_z` in `z_calibration.py`:

    offset = probe_zero - (switch_zero - nozzle_zero + switch_offset)

A sign or term error here drives the nozzle into the bed. Changes to this
formula or to its signs require an explicit derivation in the commit message
and in the final response; "simplifications" without one are not acceptable.
Bed probing is a hard invariant: it always uses the raw trigger Z (equivalent
to `ProbeResult.test_z`), never `ProbeResult.bed_z`, which subtracts the
configured probe `z_offset` and would shift the formula by exactly that amount.
That reason is documented as a comment in `calibrate_z`; refer to it.

## Language

Everything in this repository is English: code, comments, docstrings, commit
messages, documentation, G-Code response text, and error messages - regardless
of the language the user speaks to the agent in.

## Project Rules

`klipper_z_calibration` is a standalone Klipper/Kalico plugin for dockable
contact probes.

Keep these boundaries intact:

- `z_calibration.py` is the Klipper plugin entrypoint.
- `klipper_compat.py` isolates Klipper/Kalico API assumptions.
- Only `z_calibration.py` is linked into Klipper/Kalico by `install.sh`.
- Helper modules load from the repository checkout through the symlink target.
- Do not add runtime Python modules unless the install model is intentionally
  changed.
- Preserve support for the old Kalico external plugin mechanism.

Why no extra runtime modules: `z_calibration.py` inserts the repository root at
position 0 of `sys.path` in the live Klipper process so that
`klipper_compat.py` resolves through the symlink. Every further import in
`klippy` then hits the checkout first, including the standard library, so a
root-level `probe.py`, `configfile.py`, or `queue.py` would silently take over
that import process-wide. Position 0 is deliberate - it shadows stale
`klipper_compat.py` copies in `klippy/extras/` that `install.sh` cannot remove
because they are not repository symlinks - so keep root naming discipline.

Unsupported probe families are out of scope unless project policy changes:

- BLTouch-style probes
- Beacon-style probes
- non-dockable or virtual probe implementations
- virtual Z endstops for the calibration endstop

The Wiki is the source of truth for full user configuration. Do not copy large
Wiki sections into repository docs.

## Compatibility Rules

Put direct Klipper/Kalico implementation assumptions in `klipper_compat.py`.
Examples include:

- event and object lookup assumptions
- homing/probing APIs
- kinematics rail, carriage, and endstop naming assumptions
- pin setup and the stepper attachment of a plugin-owned endstop
- probe session APIs
- bed mesh internals
- toolhead status access
- gcode offset APIs

When adding or changing compatibility-sensitive behavior, add focused tests for
the affected wrapper and update `scripts/check_klipper_contract.py` if a new
upstream Klipper source contract is required.

## Public Contract

The config option names of the `[z_calibration]` section, the G-Code commands
`CALIBRATE_Z`, `PROBE_Z_ACCURACY`, and `CALCULATE_SWITCH_OFFSET`, and the
`get_status` keys `last_query` and `last_z_offset` live in other people's
`printer.cfg` files and in Mainsail/Fluidd dashboards. They are effectively
API; changing them requires a documented migration path.

## Formatting

This repository follows Klipper-style formatting via:

```bash
python3 scripts/check_whitespace.py
```

It enforces UTF-8, no trailing whitespace, no tabs, 80 columns for Python
source, and a single trailing newline. Run it rather than reasoning about it.

Target Python 3.9 (CI matrix: 3.9 and 3.13): no f-strings, no walrus operator,
no `match` statements, no `X | Y` type unions. Klipper-style `%` formatting is
used throughout on purpose, not by accident.

Keep diffs focused. Do not perform unrelated formatting-only changes.

## Testing Expectations

The goal is behavioral coverage, not just line coverage.

Add or update tests for new behavior, bug fixes, and compatibility changes,
and specifically for:

- config parsing and validation
- event and object lifecycle behavior
- G-Code command and probe session behavior
- Moonraker updater config migration
- release helper behavior

Compatibility-sensitive paths should have explicit tests for feature detection,
old/new Klipper behavior, Kalico-specific behavior, or Moonraker behavior as
applicable.

`tests/fakes.py` is the shared fake surface for Klipper objects. Carry
compatibility changes over into it; otherwise the tests verify a shape that no
longer exists. Run a single test file or a single test case with:

```bash
python3 -m unittest discover -s tests -p test_z_calibration.py -v
python3 -m unittest discover -s tests -k test_load_config_returns_helper -v
```

`tests` is only importable through `discover -s tests`, so the plain
`python3 -m unittest tests.test_z_calibration` form fails with a
`ModuleNotFoundError`.

Tests use the standard library only; `ruff` is the single optional tool. Do
not add a YAML parser to assert on workflow files. `ReleaseWorkflowTest`
provides `job_block`, `iter_job_blocks`, `iter_run_blocks`, and
`without_comments`; scope assertions with those instead of matching substrings
against a whole file, which silently breaks on comments.

## Required Validation

Before considering a task complete, run:

```bash
python3 scripts/check_all.py
```

This runs whitespace validation, shell syntax validation, a `ruff check .` lint
step, compile checks, unit tests, and `git diff --check`. Without `ruff` the
lint step is skipped with a notice; install the pinned version CI uses with
`python3 -m pip install ruff==0.16.4`. Its rules live in `ruff.toml`.

`scripts/check_release.py` is the single source of truth for release tag
classification; the `Release` workflow calls it instead of reimplementing the
rules. If release helper behavior changed, also run:

```bash
python3 scripts/check_release.py --tag v1.2.3 --channel stable
python3 scripts/check_release.py --tag v1.2.3-beta.1 --channel beta
```

If Klipper API assumptions changed and a local Klipper checkout is available,
run:

```bash
python3 scripts/check_klipper_contract.py --klipper-path ~/klipper
```

The first form clones or updates the ignored local Klipper/Kalico checkouts;
once they exist, the second runs the same checks offline:

```bash
python3 scripts/check_firmware_compat.py
python3 scripts/check_firmware_compat.py --no-update
```

Any command written into this repository must have been executed in the form
it is written, documentation included. The same applies to claims about what
CI enforces: verify them against the workflow files, not from memory.

## Review Checklist

Before finishing, review whether the change affects:

- startup behavior
- printer state transitions
- configuration parsing or migration
- Moonraker integration
- Kalico compatibility
- probe session cleanup
- installer cleanup
- release workflow behavior

Document any remaining risks or assumptions in the final response.
