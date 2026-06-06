#!/usr/bin/env python3
# Update Moonraker config for the z_calibration update manager section.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os
import pathlib
import re
import sys
import tempfile


SECTION_RE = re.compile(r'^\[update_manager(?:\s+[^\]]*)?\s+z_calibration\]$')
ANY_SECTION_RE = re.compile(r'^\[[^\]]+\]$')


def _find_section(lines):
    """Return the start/end indexes for the z_calibration updater section."""
    start = None
    for index, line in enumerate(lines):
        if SECTION_RE.match(line.strip()):
            start = index
            break
    if start is None:
        return None, None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if ANY_SECTION_RE.match(lines[index].strip()):
            end = index
            break
    return start, end


def _new_section(repo_path):
    """Build a default stable Moonraker update_manager section."""
    return [
        "",
        "[update_manager z_calibration]",
        "type: git_repo",
        "channel: stable",
        "path: %s" % (repo_path,),
        "origin: https://github.com/protoloft/klipper_z_calibration.git",
        "managed_services: klipper",
        "",
    ]


def update_config_text(text, repo_path):
    """Add or migrate the update_manager section in Moonraker config text."""
    lines = text.splitlines()
    start, end = _find_section(lines)
    if start is None:
        new_lines = lines + _new_section(repo_path)
        return "\n".join(new_lines).rstrip() + "\n", True
    section = lines[start:end]
    for line in section[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        key = stripped.split(':', 1)[0].strip().lower()
        if key == 'channel':
            return text, False
    insert_at = start + 1
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        key = stripped.split(':', 1)[0].strip().lower()
        if key == 'type':
            insert_at = index + 1
            break
    new_lines = lines[:insert_at] + ["channel: stable"] + lines[insert_at:]
    return "\n".join(new_lines).rstrip() + "\n", True


def update_config_file(path, repo_path):
    """Update a Moonraker config file and report whether it changed."""
    config_path = pathlib.Path(path)
    original = config_path.read_text(encoding='utf-8')
    updated, changed = update_config_text(original, repo_path)
    if changed:
        write_config_atomically(config_path, original, updated)
    return changed


def write_config_atomically(config_path, original, updated):
    """Back up the current config, then atomically replace it."""
    backup_path = config_path.with_name(config_path.name + '.bak')
    backup_path.write_text(original, encoding='utf-8')
    mode = config_path.stat().st_mode
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=config_path.name + '.', suffix='.tmp',
            dir=str(config_path.parent))
        tmp_path = pathlib.Path(tmp_name)
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp_file:
            tmp_file.write(updated)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, config_path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def main():
    """CLI entrypoint for Moonraker config migration."""
    if len(sys.argv) != 3:
        sys.stderr.write("Usage: update_moonraker.py <config> <repo-path>\n")
        return 2
    changed = update_config_file(sys.argv[1], sys.argv[2])
    if changed:
        sys.stdout.write("changed\n")
    else:
        sys.stdout.write("unchanged\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
