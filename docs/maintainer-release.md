# Maintainer Release Process

This document is the release checklist for maintainers of
`klipper_z_calibration`. It is intentionally procedural so a release can be
prepared, verified, and published without making process decisions during the
release.

## Release Model

1. Keep `master` releasable at all times.
2. Use semantic version tags for all new releases.
3. Use stable tags for production releases:

   ```text
   v1.2.0
   v1.2.1
   ```

4. Use beta tags for prereleases:

   ```text
   v1.2.0-beta.1
   v1.2.0-beta.2
   ```

5. Treat GitHub Releases as the public release record.
6. Mark beta tags as GitHub prereleases.
7. Mark stable tags as normal GitHub releases.
8. Let the `Release` GitHub Actions workflow create draft releases.
9. Publish draft releases manually after reviewing the generated notes.

Moonraker supports `stable`, `beta`, and `dev` channels for `git_repo`
extensions. If `channel` is omitted, Moonraker treats the extension as `dev`.
This project should guide normal users to `stable`. Existing no-channel
installs are not migrated by normal Moonraker updates, because Moonraker does
not run `install.sh` during a `git_repo` update.

## Moonraker Channel Policy

New installer-created updater sections should use `channel: stable`:

```ini
[update_manager z_calibration]
type: git_repo
channel: stable
path: /home/pi/klipper_z_calibration
origin: https://github.com/protoloft/klipper_z_calibration.git
managed_services: klipper
```

Existing updater sections should be handled as follows:

1. If `[update_manager z_calibration]` has no `channel`, the installer should
   migrate it to `channel: stable` when the installer is rerun.
2. If the section already has `channel: stable`, leave it unchanged.
3. If the section already has `channel: beta`, leave it unchanged.
4. If the section already has `channel: dev`, leave it unchanged.

This preserves explicit user intent while moving old implicit `dev` users to
the safer stable release stream when they rerun the installer or edit
`moonraker.conf`. Release notes alone are not a reliable migration mechanism,
because many users update directly through Mainsail or Fluidd.

## Pre-release Checklist

Run this checklist before creating any beta or stable release.

1. Confirm the working tree contains only intended release changes:

   ```bash
   git status --short
   ```

2. Confirm the target branch is `master`:

   ```bash
   git branch --show-current
   ```

3. Pull or fetch the latest remote state before tagging:

   ```bash
   git fetch origin --tags
   ```

4. Run the local validation suite:

   ```bash
   python3 scripts/check_all.py
   python3 scripts/check_release.py --tag v1.2.3 --channel stable
   python3 scripts/check_release.py --tag v1.2.3-beta.1 --channel beta
   python3 scripts/check_klipper_contract.py --klipper-path ~/klipper
   ```

5. Confirm the GitHub Actions CI workflow passes on `master`.
6. Confirm the Klipper Compatibility workflow is passing or review its latest
   failure before release.
7. Review installer behavior:
   - stock Klipper installs link `z_calibration.py` to `klippy/extras`
   - Kalico installs link `z_calibration.py` to `klippy/plugins`
   - `klipper_compat.py` loads from the repository checkout
   - Moonraker updater config uses the agreed channel policy
   - no-channel Moonraker migration is documented as installer-scoped
   - `managed_services: klipper` is present
   - custom Moonraker paths use `install.sh -m <path>`
8. Review compatibility notes:
   - standalone Klipper/Kalico plugin
   - dockable contact probes only
   - BLTouch, Beacon, and non-dockable virtual probes are unsupported
   - `offset_margins` replaces the removed `max_deviation` option
   - `safe_z_height` replaces the removed `clearance` option
9. Update release notes with:
   - compatibility changes
   - migration notes
   - installer behavior changes
   - known limitations

## Klipper Compatibility Monitoring

Critical Klipper implementation assumptions are isolated in `klipper_compat.py`.
The compatibility workflow validates the upstream source contracts that module
uses.

The `Klipper And Kalico Compatibility` workflow runs weekly and can be started
manually.
It checks:

1. This repository's normal validation suite.
2. The latest Klipper release tag.
3. Klipper `master` as an early warning for upcoming breakage.
4. Kalico `main` as an early warning for fork-specific breakage.

Run the contract check manually against a local Klipper checkout:

```bash
python3 scripts/check_klipper_contract.py --klipper-path ~/klipper
```

To clone or update local Klipper/Kalico compatibility checkouts under the
ignored `.compat_repos/` directory and run the same contract checks locally:

```bash
python3 scripts/check_firmware_compat.py
```

After the checkouts exist, rerun without fetching:

```bash
python3 scripts/check_firmware_compat.py --no-update
```

If the latest-release lane fails, treat it as a release blocker. If the
`master` lane fails but the latest-release lane passes, open an issue and fix
the compatibility layer before the upstream change reaches a Klipper release.

## Beta Release Steps

Use a beta release when a change needs testing on real printers before being
promoted to stable.

1. Choose the next beta version.

   Example:

   ```text
   v1.2.0-beta.1
   ```

2. Run the pre-release checklist.
3. Create and push the beta tag:

   ```bash
   git tag -a v1.2.0-beta.1 -m "v1.2.0-beta.1"
   git push origin v1.2.0-beta.1
   ```

4. Wait for the `Release` workflow to pass on the tag.
5. Open the draft GitHub Release created by the workflow.
6. Confirm the draft is marked as a prerelease.
7. Review and edit the generated release notes.
8. Include tester guidance:
   - configure Moonraker with `channel: beta`
   - restart Moonraker after changing `moonraker.conf`
   - update through Moonraker Update Manager
   - report printer model, Klipper/Kalico commit, and probe type with issues
9. Include rollback guidance:
   - use Moonraker Update Manager rollback if available
   - or switch back to `channel: stable`
10. Publish the GitHub Release manually.
11. Verify from a beta-channel install that Moonraker detects the prerelease.

## Stable Release Steps

Use a stable release for production-ready changes.

1. Choose the next stable version.

   Examples:

   ```text
   v1.2.0
   v1.2.1
   ```

2. Run the pre-release checklist.
3. If promoting a beta, confirm the stable tag points at the validated commit.
4. Create and push the stable tag:

   ```bash
   git tag -a v1.2.0 -m "v1.2.0"
   git push origin v1.2.0
   ```

5. Wait for the `Release` workflow to pass on the tag.
6. Open the draft GitHub Release created by the workflow.
7. Confirm the draft is not marked as a prerelease.
8. Review and edit the generated release notes.
9. Include release notes:
   - user-visible changes
   - compatibility changes
   - no-channel Moonraker migration guidance
   - exact `channel: stable` updater config snippet
   - Moonraker restart instructions after editing `moonraker.conf`
   - installer migration notes that explain `install.sh` must be rerun
   - manual verification performed
10. Publish the GitHub Release manually.
11. Verify from a stable-channel install that Moonraker detects the release.

## Post-release Verification

After publishing, verify the release from user-like environments.

1. Fresh stock Klipper install:
   - run `install.sh`
   - confirm `z_calibration.py` links into `klippy/extras`
   - confirm no new `klipper_compat.py` link is created in `klippy/extras`
   - confirm Moonraker updater section exists
   - confirm Moonraker Update Manager shows the new version
   - confirm custom Moonraker config paths work with `install.sh -m <path>`
2. Fresh Kalico install:
   - run `install.sh`
   - confirm `z_calibration.py` links into `klippy/plugins`
   - confirm no new `klipper_compat.py` link is created in `klippy/plugins`
   - confirm `allow_plugin_override` instructions are shown
3. Existing no-channel Moonraker config:
   - rerun `install.sh`
   - confirm the installer migrates the section to `channel: stable`
4. Existing no-channel Moonraker config through normal Moonraker update:
   - update through Moonraker without rerunning `install.sh`
   - confirm the section is not automatically migrated
5. Existing explicit-channel Moonraker config:
   - confirm `channel: stable` is unchanged
   - confirm `channel: beta` is unchanged
   - confirm `channel: dev` is unchanged
6. Runtime smoke test:
   - Klipper starts successfully
   - `[z_calibration]` loads
   - `CALIBRATE_Z` is registered
   - status object exposes `last_query` and `last_z_offset`

## Hotfix Process

Use a hotfix for critical compatibility or safety fixes.

1. Identify the latest stable release tag.
2. Create the fix from `master` if it is releasable.
3. If `master` contains unrelated risky changes, branch from the latest stable
   tag instead.
4. Apply only the minimal fix and related tests.
5. Run the full pre-release checklist.
6. Publish a patch release.

Example:

```text
v1.2.1
```

7. Clearly mark the release as a hotfix in the GitHub Release notes.

## Release Notes Template

Use this structure for GitHub Release notes:

```markdown
## Summary

- Short description of the release.

## Changes

- User-visible change.
- Compatibility fix.
- Installer or Moonraker behavior change.

## Compatibility

- Klipper:
- Kalico:
- Moonraker:
- Supported probes:

## Migration Notes

- Required user action, if any.

## Validation

- CI passed.
- Local validation commands passed.
- Manual install/update checks performed.
```

## Maintainer Command Reference

Run all validation:

```bash
python3 scripts/check_whitespace.py
bash -n install.sh
python3 scripts/check_release.py --tag v1.2.3 --channel stable
python3 scripts/check_release.py --tag v1.2.3-beta.1 --channel beta
python3 scripts/check_klipper_contract.py --klipper-path ~/klipper
python3 -m compileall .
python3 -m unittest discover -s tests -v
git diff --check
```

List recent tags:

```bash
git tag --sort=-version:refname | head -20
```

Create an annotated stable tag:

```bash
git tag -a v1.2.0 -m "v1.2.0"
git push origin v1.2.0
```

Create an annotated beta tag:

```bash
git tag -a v1.2.0-beta.1 -m "v1.2.0-beta.1"
git push origin v1.2.0-beta.1
```
