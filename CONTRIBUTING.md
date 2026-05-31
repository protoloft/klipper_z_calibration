# Contributing

Thanks for helping improve `klipper_z_calibration`. This project is a
standalone Klipper/Kalico plugin for dockable contact probes.

## Project Scope

This repository supports:

- stock Klipper installs through `klippy/extras`
- Kalico installs through `klippy/plugins`
- dockable contact probes
- Moonraker Update Manager installs

This repository does not support:

- BLTouch-style probes
- Beacon-style probes
- non-dockable or virtual probe implementations
- virtual Z endstops for the calibration endstop

The Wiki remains the source of truth for complete user configuration. Avoid
copying large Wiki sections into this repository.

## Runtime Layout

Keep the runtime layout simple:

- `z_calibration.py` is the Klipper plugin entrypoint.
- `klipper_compat.py` isolates compatibility-sensitive Klipper/Kalico API
  assumptions.
- Only `z_calibration.py` is linked into Klipper/Kalico by the installer.
  Helper modules load from the repository checkout through the symlink target.

Put direct Klipper/Kalico implementation assumptions in `klipper_compat.py`.
Keep calibration behavior, config parsing, G-Code command handling, and runtime
flow in `z_calibration.py`.

## Code Changes

- Keep behavior changes minimal and explicit.
- Match the existing Klipper-style formatting.
- Do not add new runtime modules unless the install model is intentionally
  changed.
- Do not add unsupported probe workarounds without first defining the support
  policy and tests.
- Preserve compatibility with the currently supported old Kalico plugin
  mechanism.

## Tests

New behavior, bug fixes, and compatibility changes should include tests.

Prioritize tests for:

- config parsing and validation
- event and object lifecycle behavior
- G-Code command behavior
- probe session behavior
- Klipper/Kalico compatibility wrappers
- Moonraker updater config migration
- release helper behavior

Compatibility-sensitive paths should be covered explicitly. Avoid relying only
on broad happy-path tests.

## Validation

Run these checks before submitting a pull request:

```bash
python3 scripts/check_all.py
```

The check runner performs whitespace validation, shell syntax validation,
compile checks, unit tests, and `git diff --check`.

If you touch release helper behavior, also run:

```bash
python3 scripts/check_release.py --tag v1.2.3 --channel stable
python3 scripts/check_release.py --tag v1.2.3-beta.1 --channel beta
```

If you touch Klipper API assumptions and have a local Klipper checkout, run:

```bash
python3 scripts/check_klipper_contract.py --klipper-path ~/klipper
```

To clone or update local Klipper/Kalico compatibility checkouts under the
ignored `.compat_repos/` directory and run all firmware contract checks:

```bash
python3 scripts/check_firmware_compat.py
```

After those checkouts exist, rerun the same contract checks without network
access:

```bash
python3 scripts/check_firmware_compat.py --no-update
```

## Releases

Release publishing is maintainer-owned. Maintainers should follow:

[docs/maintainer-release.md](docs/maintainer-release.md)
