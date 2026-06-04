#!/usr/bin/env python3
# Validate release tags and expose metadata for GitHub Actions.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import argparse
import pathlib
import re
import sys


STABLE_RE = re.compile(r'^v(?P<version>\d+\.\d+\.\d+)$')
BETA_RE = re.compile(r'^v(?P<version>\d+\.\d+\.\d+-beta\.\d+)$')


class ReleaseError(Exception):
    """Raised when release tag metadata is invalid."""

    pass


def classify_tag(tag):
    """Classify a tag as stable or beta release metadata."""
    stable = STABLE_RE.match(tag)
    if stable is not None:
        return {
            'tag': tag,
            'version': stable.group('version'),
            'channel': 'stable',
            'prerelease': 'false',
            'title': tag,
        }
    beta = BETA_RE.match(tag)
    if beta is not None:
        return {
            'tag': tag,
            'version': beta.group('version'),
            'channel': 'beta',
            'prerelease': 'true',
            'title': tag,
        }
    raise ReleaseError(
        "invalid release tag %r; expected vX.Y.Z or vX.Y.Z-beta.N" % (tag,))


def validate_channel(metadata, expected_channel):
    """Ensure the tag channel matches an optional expected channel."""
    if expected_channel is None:
        return
    if metadata['channel'] != expected_channel:
        raise ReleaseError(
            "tag %s is %s, not %s"
            % (metadata['tag'], metadata['channel'], expected_channel))


def write_outputs(path, metadata):
    """Append GitHub Actions output values for release metadata."""
    output_path = pathlib.Path(path)
    with output_path.open('a', encoding='utf-8') as output_file:
        for key in ['tag', 'version', 'channel', 'prerelease', 'title']:
            output_file.write("%s=%s\n" % (key, metadata[key]))


def parse_args(argv):
    """Parse release validation arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--channel', choices=['stable', 'beta'])
    parser.add_argument('--github-output')
    return parser.parse_args(argv)


def main(argv=None):
    """CLI entrypoint for release metadata validation."""
    args = parse_args(argv or sys.argv[1:])
    try:
        metadata = classify_tag(args.tag)
        validate_channel(metadata, args.channel)
    except ReleaseError as err:
        sys.stderr.write(str(err) + "\n")
        return 1
    if args.github_output:
        write_outputs(args.github_output, metadata)
    sys.stdout.write(
        "%s %s %s\n"
        % (metadata['tag'], metadata['channel'], metadata['prerelease']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
