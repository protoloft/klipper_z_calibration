#!/usr/bin/env python3
# Clone/update firmware repositories and run local compatibility contracts.
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import argparse
import importlib.util
import pathlib
import re
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_REPO_DIR = ROOT / '.compat_repos'
KLIPPER_URL = 'https://github.com/Klipper3d/klipper.git'
KALICO_URL = 'https://github.com/KalicoCrew/kalico.git'
TAG_RE = re.compile(r'refs/tags/(v[0-9]+\.[0-9]+\.[0-9]+)$')


def load_contract_checker():
    path = SCRIPT_DIR / 'check_klipper_contract.py'
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_klipper_contract = load_contract_checker()


def run(command, cwd=None, capture=False):
    text = ' '.join([str(item) for item in command])
    sys.stdout.write("+ %s\n" % (text,))
    sys.stdout.flush()
    kwargs = {
        'cwd': str(cwd) if cwd is not None else None,
        'text': True,
        'check': True,
    }
    if capture:
        kwargs.update({'stdout': subprocess.PIPE})
    return subprocess.run([str(item) for item in command], **kwargs)


def latest_klipper_tag():
    result = run(
        ('git', 'ls-remote', '--tags', '--refs', KLIPPER_URL, 'v*'),
        capture=True)
    tags = []
    for line in result.stdout.splitlines():
        match = TAG_RE.search(line)
        if match is not None:
            tags.append(match.group(1))
    if not tags:
        raise RuntimeError("Unable to find latest Klipper release tag")
    return sorted(tags, key=version_key)[-1]


def version_key(tag):
    return tuple([int(part) for part in tag[1:].split('.')])


def clone_or_update(path, url, ref, update=True):
    path = pathlib.Path(path)
    if not path.exists():
        if ref is None:
            raise RuntimeError(
                "missing %s; run without --no-update first" % (path,))
        run(('git', 'clone', '--depth', '1', '--branch', ref, url, path))
        return
    if not update:
        return
    run(('git', 'fetch', '--depth', '1', 'origin', ref), cwd=path)
    run(('git', 'checkout', '--detach', 'FETCH_HEAD'), cwd=path)


def check_contract(name, path):
    sys.stdout.write("Checking %s contract at %s\n" % (name, path))
    errors = check_klipper_contract.check_klipper_contract(path)
    if errors:
        for error in errors:
            sys.stderr.write("%s: %s\n" % (name, error))
        return 1
    profiles = check_klipper_contract.get_contract_profiles(path)
    sys.stdout.write("%s contract checks passed: %s\n"
                     % (name, ', '.join(profiles)))
    return 0


def get_targets(repo_dir, update=True):
    klipper_ref = latest_klipper_tag() if update else None
    return [
        ('klipper-release', KLIPPER_URL, klipper_ref,
         repo_dir / 'klipper-release'),
        ('klipper-master', KLIPPER_URL, 'master' if update else None,
         repo_dir / 'klipper-master'),
        ('kalico-main', KALICO_URL, 'main' if update else None,
         repo_dir / 'kalico-main'),
    ]


def run_checks(repo_dir, update=True):
    repo_dir = pathlib.Path(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    targets = get_targets(repo_dir, update=update)
    for _name, url, ref, path in targets:
        if ref is None and not path.exists():
            raise RuntimeError(
                "missing %s; run without --no-update first" % (path,))
        clone_or_update(path, url, ref, update=update)
    result = 0
    for name, _url, _ref, path in targets:
        result |= check_contract(name, path)
    return result


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-dir', default=str(DEFAULT_REPO_DIR),
                        help='directory for local firmware checkouts')
    parser.add_argument('--no-update', action='store_true',
                        help='reuse existing checkouts without fetching')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    try:
        return run_checks(args.repo_dir, update=not args.no_update)
    except (RuntimeError, subprocess.CalledProcessError) as err:
        sys.stderr.write("%s\n" % (err,))
        return 1


if __name__ == '__main__':
    sys.exit(main())
