"""Self-update runs only an approved commit from the pinned repository."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import atualizacao  # noqa: E402


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          text=True, env={'PATH': '/usr/bin:/bin', 'GIT_AUTHOR_NAME': 't',
                                          'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
                                          'GIT_COMMITTER_EMAIL': 't@t', 'HOME': str(repo)}).stdout.strip()


def commit(repo, name):
    (repo / name).write_text(name)
    git(repo, 'add', name)
    git(repo, 'commit', '-q', '-m', f'add {name}')
    return git(repo, 'rev-parse', 'HEAD')


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.origin, self.state, self.runtime = base / 'origin', base / 'state', base / 'runtime'
        for folder in (self.origin, self.state, self.runtime):
            folder.mkdir()
        git(self.origin, 'init', '-q', '-b', 'main')
        self.first = commit(self.origin, 'a')
        self.second = commit(self.origin, 'b')
        git(self.origin, 'branch', 'dev/sagas')
        git(self.origin, 'branch', 'Feature_Evil')
        (self.runtime / '.heimdall-version.json').write_text(json.dumps(
            {'commit': self.first, 'short': self.first[:7]}))

    def tearDown(self):
        self.temporary.cleanup()

    def check(self):
        return atualizacao.check(self.state, self.runtime, str(self.origin), allow_file=True)

    def test_lists_changes_since_installed_commit_and_valid_channels(self):
        result = self.check()
        self.assertFalse(result['up_to_date'])
        self.assertTrue(result['linear'])
        self.assertEqual([c['commit'] for c in result['commits']], [self.second])
        self.assertEqual(result['branches'], ['dev/sagas', 'main'])
        status = atualizacao.status(self.state, self.runtime)
        self.assertEqual(status['check']['target'], self.second)

    def test_only_https_repositories_outside_tests(self):
        with self.assertRaisesRegex(atualizacao.UpdateError, 'endereço'):
            atualizacao.check(self.state, self.runtime, str(self.origin))
        with self.assertRaisesRegex(atualizacao.UpdateError, 'endereço'):
            atualizacao.check(self.state, self.runtime, 'http://example.com/x.git')
        self.assertIn('error', atualizacao.status(self.state, self.runtime)['check'])

    def test_first_channel_is_the_installed_branch(self):
        (self.runtime / '.heimdall-version.json').write_text(json.dumps(
            {'commit': self.first, 'short': self.first[:7], 'branch': 'dev/sagas'}))
        self.assertEqual(atualizacao.status(self.state, self.runtime)['channel'], 'dev/sagas')
        self.assertEqual(self.check()['channel'], 'dev/sagas')
        atualizacao.set_channel('main', self.state)
        self.assertEqual(atualizacao.channel(self.state, self.runtime), 'main')

    def test_installed_version_comes_from_release_manifest(self):
        release = self.runtime / 'deploy/VERSION'
        release.parent.mkdir()
        release.write_text('0.2.0\n', encoding='ascii')
        self.assertEqual(atualizacao.installed(self.runtime)['version'], '0.2.0')
        (self.runtime / '.heimdall-version.json').write_text(json.dumps({'version': '0.2.1'}))
        self.assertEqual(atualizacao.installed(self.runtime)['version'], '0.2.1')

    def test_channel_names_are_restricted(self):
        for bad in ('Feature_Evil', '../main', 'main; rm', 'dev/', 3):
            with self.subTest(bad=bad), self.assertRaises(atualizacao.UpdateError):
                atualizacao.set_channel(bad, self.state)
        self.assertEqual(atualizacao.set_channel('dev/sagas', self.state), 'dev/sagas')
        self.assertEqual(atualizacao.channel(self.state), 'dev/sagas')

    @unittest.skipIf(sys.platform == 'win32', 'systemd-run is the Linux path; Windows uses a scheduled task')
    def test_start_runs_exactly_the_approved_commit_detached(self):
        self.check()
        calls = []

        def runner(command, **_):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(atualizacao, 'running', return_value=False):
            with self.assertRaisesRegex(atualizacao.UpdateError, 'desatualizada'):
                atualizacao.start(self.first, self.state, runner)
            with self.assertRaises(atualizacao.UpdateError):
                atualizacao.start('main', self.state, runner)
            # The branch moves after the admin looked: the old list is refused.
            third = commit(self.origin, 'c')
            self.check()
            atualizacao.start(third, self.state, runner)
        command = calls[0]
        self.assertEqual(command[0], 'systemd-run')
        self.assertIn('--no-block', command)
        self.assertEqual(command[-1], str(self.state / 'source/deploy/update.sh'))
        self.assertEqual(git(self.state / 'source', 'rev-parse', 'HEAD'), third)

    def test_saved_check_is_up_to_date_after_its_target_is_installed(self):
        self.check()
        self.assertFalse(atualizacao.status(self.state, self.runtime)['check']['up_to_date'])
        (self.runtime / '.heimdall-version.json').write_text(json.dumps(
            {'commit': self.second, 'short': self.second[:7]}))
        after = atualizacao.status(self.state, self.runtime)['check']
        self.assertTrue(after['up_to_date'])
        self.assertEqual(after['commits'], [])
        with patch.object(atualizacao, 'running', return_value=False), \
                self.assertRaisesRegex(atualizacao.UpdateError, 'HN-UPD-013'):
            atualizacao.start(self.second, self.state, lambda *a, **k: None, self.runtime)

    def test_refuses_while_another_update_runs(self):
        self.check()
        with patch.object(atualizacao, 'running', return_value=True), \
                self.assertRaisesRegex(atualizacao.UpdateError, 'andamento'):
            atualizacao.start(self.second, self.state, lambda *a, **k: None)


if __name__ == '__main__':
    unittest.main()
