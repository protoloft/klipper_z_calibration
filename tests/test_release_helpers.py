# Unit tests for release validation and Moonraker update config helpers.
#
# Copyright (C) 2021-2026  Titus Meyer <info@protoloft.org>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import importlib.util
import pathlib
import re
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_script(name):
    """Load a script module from the repository scripts directory."""
    path = ROOT / 'scripts' / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_all = load_script('check_all.py')
check_release = load_script('check_release.py')
update_moonraker = load_script('update_moonraker.py')


class ReleaseValidationTest(unittest.TestCase):
    """Covers release tag metadata validation."""

    def test_classifies_stable_tag(self):
        metadata = check_release.classify_tag('v1.2.3')
        self.assertEqual(metadata['version'], '1.2.3')
        self.assertEqual(metadata['channel'], 'stable')
        self.assertEqual(metadata['prerelease'], 'false')

    def test_classifies_beta_tag(self):
        metadata = check_release.classify_tag('v1.2.3-beta.4')
        self.assertEqual(metadata['version'], '1.2.3-beta.4')
        self.assertEqual(metadata['channel'], 'beta')
        self.assertEqual(metadata['prerelease'], 'true')

    def test_rejects_invalid_tags(self):
        for tag in ['1.2.3', 'v1.2', 'v1.2.3rc1', 'v1.2.3-beta']:
            with self.subTest(tag=tag):
                with self.assertRaises(check_release.ReleaseError):
                    check_release.classify_tag(tag)

    def test_rejects_channel_mismatch(self):
        metadata = check_release.classify_tag('v1.2.3-beta.1')
        with self.assertRaises(check_release.ReleaseError):
            check_release.validate_channel(metadata, 'stable')


class MoonrakerUpdateTest(unittest.TestCase):
    """Covers Moonraker update_manager config migration."""

    def test_adds_new_stable_section(self):
        updated, changed = update_moonraker.update_config_text(
            "[server]\nhost: 0.0.0.0\n", "/repo")
        self.assertTrue(changed)
        self.assertIn("[update_manager z_calibration]", updated)
        self.assertIn("channel: stable", updated)
        self.assertIn("path: /repo", updated)

    def test_migrates_existing_section_without_channel(self):
        text = (
            "[update_manager z_calibration]\n"
            "type: git_repo\n"
            "path: /repo\n"
            "\n"
            "[server]\n"
            "host: 0.0.0.0\n"
        )
        updated, changed = update_moonraker.update_config_text(text, "/repo")
        self.assertTrue(changed)
        self.assertIn("type: git_repo\nchannel: stable\npath:", updated)

    def test_preserves_existing_explicit_channels(self):
        for channel in ['stable', 'beta', 'dev']:
            text = (
                "[update_manager z_calibration]\n"
                "type: git_repo\n"
                "channel: %s\n"
                "path: /repo\n" % (channel,))
            with self.subTest(channel=channel):
                updated, changed = update_moonraker.update_config_text(
                    text, "/other")
                self.assertFalse(changed)
                self.assertEqual(updated, text)

    def test_preserves_channels_written_with_an_equals_sign(self):
        # configparser accepts ':' and '=', so Moonraker does too. Missing
        # the '=' form appended a second channel line, which configparser
        # then rejects as a duplicate option and Moonraker fails to start.
        text = (
            "[update_manager z_calibration]\n"
            "type = git_repo\n"
            "channel = stable\n"
            "path = /repo\n")
        updated, changed = update_moonraker.update_config_text(text, "/other")
        self.assertFalse(changed)
        self.assertEqual(updated, text)

    def test_migrates_a_section_written_with_an_equals_sign(self):
        text = (
            "[update_manager z_calibration]\n"
            "type = git_repo\n"
            "path = /repo\n")
        updated, changed = update_moonraker.update_config_text(text, "/repo")
        self.assertTrue(changed)
        self.assertIn("type = git_repo\nchannel: stable\npath = /repo",
                      updated)

    def test_file_update_reports_changed_once(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / 'moonraker.conf'
            path.write_text("[server]\nhost: 0.0.0.0\n", encoding='utf-8')
            backup = path.with_name(path.name + '.bak')
            self.assertTrue(update_moonraker.update_config_file(path, "/repo"))
            self.assertEqual(backup.read_text(encoding='utf-8'),
                             "[server]\nhost: 0.0.0.0\n")
            self.assertFalse(update_moonraker.update_config_file(path, "/repo"))

    def test_second_changing_run_keeps_the_first_backup(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / 'moonraker.conf'
            first_state = "[server]\nhost: 0.0.0.0\n"
            path.write_text(first_state, encoding='utf-8')
            self.assertTrue(update_moonraker.update_config_file(path, "/repo"))
            second_state = path.read_text(encoding='utf-8')
            # Drop the migrated channel again so the next run also changes
            # the file.
            path.write_text(second_state.replace("channel: stable\n", ""),
                            encoding='utf-8')
            second_state = path.read_text(encoding='utf-8')
            self.assertTrue(update_moonraker.update_config_file(path, "/repo"))
            first_backup = path.with_name(path.name + '.bak')
            second_backup = path.with_name(path.name + '.bak.001')
            self.assertEqual(first_backup.read_text(encoding='utf-8'),
                             first_state)
            self.assertEqual(second_backup.read_text(encoding='utf-8'),
                             second_state)
            self.assertIn("channel: stable",
                          path.read_text(encoding='utf-8'))

    def test_backup_names_sort_in_creation_order(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / 'moonraker.conf'
            created = []
            for index in range(4):
                backup = update_moonraker.next_backup_path(path)
                backup.write_text("%d\n" % (index,), encoding='utf-8')
                created.append(backup.name)
            self.assertEqual(
                created,
                ['moonraker.conf.bak', 'moonraker.conf.bak.001',
                 'moonraker.conf.bak.002', 'moonraker.conf.bak.003'])

    def test_exhausted_backup_slots_leave_the_config_untouched(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / 'moonraker.conf'
            original = "[server]\nhost: 0.0.0.0\n"
            path.write_text(original, encoding='utf-8')
            for _ in range(update_moonraker.MAX_BACKUPS):
                update_moonraker.next_backup_path(path).write_text(
                    "old\n", encoding='utf-8')
            with self.assertRaises(update_moonraker.BackupError):
                update_moonraker.update_config_file(path, "/repo")
            self.assertEqual(path.read_text(encoding='utf-8'), original)


ACTION_PIN_REASON = (
    "GitHub Actions resolves tags and branches when the workflow runs, so a"
    " retagged or compromised action release would execute in this"
    " repository without any change here. Pin every action to its full 40"
    " character commit SHA and keep the human readable version in a trailing"
    " comment, the way .github/workflows/release.yml already does:"
    " uses: actions/checkout@<sha>  # actions/checkout@v6.0.3")

LINT_INSTALL_REASON = (
    "scripts/check_all.py skips its lint step when ruff is missing, so a job"
    " that runs it without installing ruff stays green while linting"
    " nothing. Add the step .github/workflows/ci.yml already uses before the"
    " check_all.py step: run: python -m pip install ruff==%s"
    % (check_all.RUFF_VERSION,))


class ReleaseWorkflowTest(unittest.TestCase):
    """Covers release and shared GitHub workflow safety properties."""

    def workflow_text(self, name='release.yml'):
        """Return the tracked GitHub release workflow text."""
        path = ROOT / '.github' / 'workflows' / name
        return path.read_text(encoding='utf-8')

    def workflow_texts(self):
        """Return all tracked GitHub workflow texts keyed by file name."""
        workflow_dir = ROOT / '.github' / 'workflows'
        # GitHub accepts both extensions, so a future .yaml workflow must
        # not slip past the shared workflow invariants below.
        paths = (list(workflow_dir.glob('*.yml'))
                 + list(workflow_dir.glob('*.yaml')))
        return {
            path.name: path.read_text(encoding='utf-8')
            for path in sorted(paths)
        }

    def job_block(self, text, name):
        """Return the release workflow text of one job by job id."""
        start = text.index('\n  %s:\n' % (name,)) + 1
        match = re.compile(r'\n  [a-z][a-z0-9-]*:\n').search(text, start + 1)
        if match is None:
            return text[start:]
        return text[start:match.start() + 1]

    def without_comments(self, text):
        """Return workflow text with whole-line comments removed."""
        # Job structure is asserted against the mapping keys only, so that a
        # comment mentioning a key never counts as that key being set.
        return '\n'.join([line for line in text.splitlines()
                          if not line.lstrip().startswith('#')])

    def iter_run_blocks(self, text):
        """Yield the shell body of every run: step in a workflow."""
        lines = text.splitlines()
        index = 0
        while index < len(lines):
            match = re.match(r'^(\s*)-?\s*run:[ \t]*(.*)$', lines[index])
            index += 1
            if match is None:
                continue
            indent, inline = match.group(1), match.group(2).strip()
            if inline and inline not in ('|', '>', '|-', '>-', '|+', '>+'):
                yield inline
                continue
            body = []
            while index < len(lines):
                following = lines[index]
                if following.strip() and not following.startswith(indent + ' '):
                    break
                body.append(following)
                index += 1
            yield '\n'.join(body)

    def iter_job_blocks(self, text):
        """Yield (job id, job text) pairs of one workflow file."""
        jobs = text.index('\njobs:\n')
        starts = list(re.compile(r'\n  ([a-z][a-z0-9_-]*):\n')
                      .finditer(text, jobs + 1))
        for index, match in enumerate(starts):
            if index + 1 < len(starts):
                end = starts[index + 1].start() + 1
            else:
                end = len(text)
            yield match.group(1), text[match.start() + 1:end]

    def test_release_ref_is_validated_before_release_checkout(self):
        """Check that the tag is classified before any job builds from it.

        The checkout of the validating job is covered by
        test_release_ref_checkout_does_not_persist_credentials; that
        property is not repeated here.
        """
        text = self.workflow_text()
        self.assertLess(text.index('name: Validate release ref'),
                        text.index('name: Check out release tag'))
        self.assertIn(
            'ref: refs/tags/${{ needs.validate-release-ref.outputs.tag }}',
            text)
        self.assertIn('permissions:\n  contents: read', text)
        # The job that checks out the tag only starts once the classifying
        # job succeeded; textual order alone would not enforce that.
        validate_source = self.job_block(text, 'validate-source')
        self.assertIn('needs:\n      - validate-release-ref',
                      validate_source)
        # The validating job stays on the read-only workflow permissions.
        # A job level block could only raise them, never lower the risk.
        validate_ref = self.job_block(text, 'validate-release-ref')
        self.assertNotIn('permissions:', validate_ref)

    def test_release_ref_validation_uses_shared_script(self):
        validate_ref = self.job_block(self.workflow_text(),
                                      'validate-release-ref')
        self.assertIn('python3 scripts/check_release.py', validate_ref)
        self.assertIn('--tag "$RELEASE_TAG"', validate_ref)
        self.assertIn('--github-output "$GITHUB_OUTPUT"', validate_ref)
        # The expected channel is optional and must only be passed when the
        # workflow_dispatch input actually set it.
        self.assertIn('--channel "$RELEASE_CHANNEL"', validate_ref)
        self.assertIn('if [ -n "$RELEASE_CHANNEL" ]; then', validate_ref)
        # Untrusted values stay in env vars instead of being interpolated
        # into the shell command line.
        self.assertIn('RELEASE_TAG: ${{', validate_ref)
        self.assertIn('RELEASE_CHANNEL: ${{', validate_ref)
        self.assertNotIn('--tag "${{', validate_ref)
        self.assertNotIn('--channel "${{', validate_ref)

    def test_release_workflow_has_no_second_tag_classification(self):
        # Comment-free, so that a future comment mentioning one of the
        # banned patterns cannot fail the whole-file assertions below.
        text = self.without_comments(self.workflow_text())
        # scripts/check_release.py is the single source of truth. Any tag
        # regex or output writing in the workflow would silently drift.
        for pattern in ['stable_re', 'beta_re', 'BASH_REMATCH',
                        '-beta\\.', '[0-9]+\\.[0-9]+']:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, text)
        # Bash regex matching only means drift where the tag is classified,
        # so this stays scoped to that job instead of banning '=~' from
        # every unrelated future step of the workflow.
        validate_ref = self.job_block(text, 'validate-release-ref')
        self.assertNotIn('=~', validate_ref)
        self.assertNotIn('>> "$GITHUB_OUTPUT"', text)
        self.assertNotIn('echo "tag=', text)

    def test_release_ref_job_outputs_match_script_outputs(self):
        text = self.workflow_text()
        with tempfile.TemporaryDirectory() as tempdir:
            path = pathlib.Path(tempdir) / 'github_output'
            metadata = check_release.classify_tag('v1.2.3')
            check_release.write_outputs(path, metadata)
            lines = path.read_text(encoding='utf-8').splitlines()
        keys = [line.split('=', 1)[0] for line in lines]
        self.assertEqual(keys,
                         ['tag', 'version', 'channel', 'prerelease', 'title'])
        validate_ref = self.job_block(text, 'validate-release-ref')
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(
                    '%s: ${{ steps.release.outputs.%s }}' % (key, key),
                    validate_ref)

    def test_release_ref_checkout_does_not_persist_credentials(self):
        validate_ref = self.job_block(self.workflow_text(),
                                      'validate-release-ref')
        self.assertIn('uses: actions/checkout@', validate_ref)
        self.assertIn('persist-credentials: false', validate_ref)
        # The checkout action stays pinned to the same commit the rest of
        # the workflow uses.
        pins = set(re.findall(r'uses: actions/checkout@(\S+)',
                              self.workflow_text()))
        self.assertEqual(len(pins), 1)
        self.assertRegex(pins.pop(), r'^[0-9a-f]{40}$')

    def test_checkout_credentials_are_not_persisted(self):
        for name, text in self.workflow_texts().items():
            for match in re.finditer(r'uses:\s+actions/checkout@', text):
                next_step = text.find('\n      - name:', match.end())
                checkout_block = text[match.end():]
                if next_step != -1:
                    checkout_block = text[match.end():next_step]
                with self.subTest(workflow=name, offset=match.start()):
                    self.assertIn('persist-credentials: false',
                                  checkout_block)

    def test_check_all_jobs_install_the_pinned_lint_tool(self):
        """Every job running check_all.py installs ruff before it."""
        install = 'pip install ruff==%s' % (check_all.RUFF_VERSION,)
        checked = 0
        for name, text in sorted(self.workflow_texts().items()):
            for job, block in self.iter_job_blocks(text):
                if 'scripts/check_all.py' not in block:
                    continue
                checked += 1
                with self.subTest(workflow=name, job=job):
                    self.assertIn(install, block, LINT_INSTALL_REASON)
                    self.assertLess(block.index(install),
                                    block.index('scripts/check_all.py'),
                                    LINT_INSTALL_REASON)
        self.assertGreater(checked, 0,
                           "no workflow job runs scripts/check_all.py")

    def test_all_workflow_actions_are_pinned_to_commit_shas(self):
        texts = self.workflow_texts()
        self.assertTrue(texts, "no GitHub workflow files were found")
        checked = 0
        for name, text in sorted(texts.items()):
            for match in re.finditer(r'uses:[ \t]*(\S+)', text):
                reference = match.group(1)
                action, _, ref = reference.partition('@')
                checked += 1
                with self.subTest(workflow=name, action=action):
                    self.assertRegex(
                        ref, r'^[0-9a-f]{40}$',
                        "%s uses %s, which is not pinned to a commit SHA."
                        " %s" % (name, reference, ACTION_PIN_REASON))
        self.assertGreater(checked, 0, "no action references were checked")

    def test_release_publish_job_does_not_checkout_source(self):
        text = self.workflow_text()
        draft_release = self.job_block(text, 'draft-release')
        self.assertNotIn('actions/checkout', draft_release)
        self.assertIn('uses: actions/download-artifact@', draft_release)
        self.assertIn('uses: actions/upload-artifact@', text)
        self.assertLess(text.index('uses: actions/upload-artifact@'),
                        text.index('  draft-release:'))
        self.assertIn('permissions:\n      contents: write', draft_release)

    def test_only_the_publish_job_may_write_releases(self):
        text = self.without_comments(self.workflow_text())
        writers = [name for name, block in self.iter_job_blocks(text)
                   if re.search(r'^\s+contents: write\s*$', block, re.M)]
        self.assertEqual(
            writers, ['draft-release'],
            "exactly one job may hold contents: write, and it must be the"
            " job that publishes releases without checking out source."
            " Jobs found: %s" % (', '.join(writers) or 'none',))

    def test_no_workflow_interpolates_context_into_a_shell_command(self):
        texts = self.workflow_texts()
        self.assertTrue(texts, "no GitHub workflow files were found")
        checked = 0
        for name, text in sorted(texts.items()):
            for body in self.iter_run_blocks(text):
                checked += 1
                with self.subTest(workflow=name, run=body[:40]):
                    self.assertNotIn(
                        '${{', body,
                        "%s interpolates a workflow context directly into a"
                        " shell command. Pass the value through an env: entry"
                        " and reference it as a quoted shell variable, so that"
                        " its content is never parsed as shell syntax."
                        % (name,))
        self.assertGreater(checked, 0, "no run steps were checked")

    def test_release_workflow_updates_existing_draft_assets(self):
        draft_release = self.without_comments(
            self.job_block(self.workflow_text(), 'draft-release'))
        self.assertIn('gh release view "$RELEASE_TAG"', draft_release)
        # The draft update must take the release id from "gh release view",
        # which resolves drafts. The REST releases/tags/<tag> endpoint
        # answers 404 for a draft and would fail every workflow re-run.
        self.assertIn('--json databaseId,isDraft', draft_release)
        self.assertNotIn('releases/tags/', draft_release)
        self.assertIn(
            'gh release upload "$RELEASE_TAG" dist/*.tar.gz --clobber',
            draft_release)
        self.assertIn('already exists and is not a draft', draft_release)


if __name__ == '__main__':
    unittest.main()
