<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="pictures/banner-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="pictures/banner-light.png">
    <img src="docs/assets/banner-light.png" alt="Automatic Z-Calibration" width="100%">
  </picture>
  <h1 align="center">Automatic Z-Calibration</h1>
</p>

<p align="center">
  Automatic Z offset calibration for Klipper and Kalico printers using
  dockable contact probes.
</p>

<p align="center">
  <a aria-label="Downloads" href="https://github.com/protoloft/klipper_z_calibration/releases">
    <img src="https://img.shields.io/github/release/protoloft/klipper_z_calibration?display_name=tag&style=flat-square">
  </a>
  <a aria-label="CI" href="https://github.com/protoloft/klipper_z_calibration/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/protoloft/klipper_z_calibration/ci.yml?branch=master&label=ci&style=flat-square">
  </a>
  <a aria-label="Firmware compatibility" href="https://github.com/protoloft/klipper_z_calibration/actions/workflows/compat.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/protoloft/klipper_z_calibration/compat.yml?branch=master&label=klipper%2Fkalico%20compat&style=flat-square">
  </a>
  <a aria-label="Checked firmware targets" href="https://github.com/protoloft/klipper_z_calibration/actions/workflows/compat.yml">
    <img src="https://img.shields.io/badge/checked-latest%20Klipper%20release%20%2B%20master%20%2B%20Kalico%20main-informational?style=flat-square">
  </a>
  <a aria-label="Moonraker Update Manager" href="https://github.com/protoloft/klipper_z_calibration/blob/master/docs/maintainer-release.md">
    <img src="https://img.shields.io/badge/moonraker-update%20manager-blue?style=flat-square">
  </a>
  <a aria-label="Stars" href="https://github.com/protoloft/klipper_z_calibration/stargazers">
    <img src="https://img.shields.io/github/stars/protoloft/klipper_z_calibration?style=flat-square">
  </a>
  <a aria-label="License" href="https://github.com/protoloft/klipper_z_calibration/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/protoloft/klipper_z_calibration?style=flat-square">
  </a>
</p>

## Overview

`klipper_z_calibration` is a standalone Klipper/Kalico plugin that measures the
relationship between a fixed Z endstop, a dockable probe, and the print surface,
then applies the resulting Z offset. The primary runtime command is
`CALIBRATE_Z`.

The full user documentation remains in the
[Wiki](https://github.com/protoloft/klipper_z_calibration/wiki). This README is
only the quick project overview, installation entry point, and compatibility
summary.

## Supported Setup

Supported:

- Klipper installations using `klippy/extras`
- Kalico installations using the external plugin mechanism in `klippy/plugins`
- Dockable contact probes such as Klicky-style probes
- Moonraker Update Manager installs

Not supported:

- BLTouch-style probes
- Beacon-style probes
- Other non-dockable or virtual probe implementations
- Virtual Z endstops for the Z calibration endstop

Kalico users must enable plugin overrides:

```ini
[danger_options]
allow_plugin_override: True
```

## Quick Install

Clone the repository and run the installer as the printer user, not as root:

```bash
git clone https://github.com/protoloft/klipper_z_calibration.git
cd klipper_z_calibration
./install.sh
```

Useful installer options:

```bash
./install.sh -k ~/klipper
./install.sh -m ~/printer_data/config/moonraker.conf
./install.sh -n 2
./install.sh -u
```

The installer links only `z_calibration.py` into Klipper or Kalico. Supporting
Python modules are loaded from this repository checkout through the symlink
target, so the checkout must remain in place.

## Moonraker Updates

The installer manages the `[update_manager z_calibration]` section in
`moonraker.conf`.

- New installations use `channel: stable`.
- Existing sections without a `channel` are migrated to `channel: stable`.
- Existing explicit `stable`, `beta`, or `dev` channels are left unchanged.
- `managed_services: klipper` is configured so updates restart Klipper.

Moonraker's modern default config path is
`~/printer_data/config/moonraker.conf`. Use `install.sh -m <path>` for custom
layouts.

## Configuration Notes

Use the Wiki for the full configuration reference:

https://github.com/protoloft/klipper_z_calibration/wiki

Current releases expect the modern option names:

- `offset_margins`
- `safe_z_height`

The older `max_deviation` and `clearance` options are no longer supported.

The smaller the configured `switch_offset`, the farther the nozzle is from the
bed.

## Commands

The plugin registers these G-Code commands:

- `CALIBRATE_Z`: measure and apply the current Z offset.
- `PROBE_Z_ACCURACY`: probe the fixed Z endstop repeatedly for repeatability
  checks.
- `CALCULATE_SWITCH_OFFSET`: calculate a switch offset from the current Z
  position after calibration.

Command parameters and complete configuration examples are documented in the
Wiki.

## Development And Releases

Contributor guide:
[CONTRIBUTING.md](CONTRIBUTING.md)

Maintainer release process:
[docs/maintainer-release.md](docs/maintainer-release.md)

This repository includes unit tests, release validation helpers, GitHub Actions
CI, and a scheduled Klipper/Kalico compatibility workflow. Critical Klipper and
Kalico API assumptions are isolated in `klipper_compat.py`.

Run the standard local validation suite with:

```bash
python3 scripts/check_all.py
```

## Further Resources

Kapman's how-to video:
[https://youtu.be/oQYHFecsTto](https://youtu.be/oQYHFecsTto)

RRF version of automatic Z offset calibration:
[Auto-Z-calibration-for-RRF-3.3-or-later-and-Klicky-Probe](https://github.com/pRINTERnOODLE/Auto-Z-calibration-for-RRF-3.3-or-later-and-Klicky-Probe)

## Support

If this project is useful to you, support is welcome:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/X8X1C0DTD)

## Disclaimer

Use this plugin at your own risk. You are responsible for validating your
printer configuration and checking all motion paths before use. Never leave a
printer unattended while printing.
