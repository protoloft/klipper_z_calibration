# Agent Instructions

This file is for automated coding agents working in this repository.
Human contributor guidance is in `CONTRIBUTING.md`. Maintainer release steps
are in `docs/maintainer-release.md`.

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
- probe session APIs
- bed mesh internals
- toolhead status access
- gcode offset APIs

When adding or changing compatibility-sensitive behavior, add focused tests for
the affected wrapper and update `scripts/check_klipper_contract.py` if a new
upstream Klipper source contract is required.

## Formatting

This repository follows Klipper-style formatting via:

```bash
python3 scripts/check_whitespace.py
```

Requirements include:

- UTF-8 encoded files
- no trailing whitespace
- no tabs, except where explicitly allowed
- maximum line length of 80 characters for Python source
- newline at end of file
- no extra blank lines at end of file
- no invalid control characters

Keep diffs focused. Do not perform unrelated formatting-only changes.

## Testing Expectations

The goal is behavioral coverage, not just line coverage.

Add or update tests for:

- new behavior
- bug fixes
- compatibility changes
- config parsing and validation
- event and object lifecycle behavior
- G-Code command behavior
- probe session behavior
- Moonraker updater config migration
- release helper behavior

Compatibility-sensitive paths should have explicit tests for feature detection,
old/new Klipper behavior, Kalico-specific behavior, or Moonraker behavior as
applicable.

## Required Validation

Before considering a task complete, run:

```bash
python3 scripts/check_all.py
```

This runs whitespace validation, shell syntax validation, compile checks, unit
tests, and `git diff --check`.

If release helper behavior changed, also run:

```bash
python3 scripts/check_release.py --tag v1.2.3 --channel stable
python3 scripts/check_release.py --tag v1.2.3-beta.1 --channel beta
```

If Klipper API assumptions changed and a local Klipper checkout is available,
run:

```bash
python3 scripts/check_klipper_contract.py --klipper-path ~/klipper
```

To clone or update ignored local Klipper/Kalico checkouts and run all firmware
contract checks:

```bash
python3 scripts/check_firmware_compat.py
```

After the ignored checkouts exist, use the offline form when network access is
not needed:

```bash
python3 scripts/check_firmware_compat.py --no-update
```

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
