import contextlib
from datetime import datetime, timezone
import io
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/daydream/scripts'))
import collect_apple


class AppleExportTests(unittest.TestCase):
    def row(self, identifier='example', text='An idea about reusable picnic maps', **kwargs):
        value = {'id': identifier, 'source': 'apple-notes', 'title': 'Idea', 'text': text,
                 'timestamp': '2026-10-01T00:00:00Z', 'collection': 'Ideas'}
        value.update(kwargs)
        return value

    def test_filters_secret_before_truncation_and_keeps_completed_state(self):
        secret = self.row('secret', 'A harmless opening ' * 100 + '\nAPI_KEY=' + 'synthetic_value_for_testing')
        completed = self.row('done', source='apple-reminders', status='completed')
        result = collect_apple.prepare({'records': [secret, completed]}, days=0, max_chars=20)
        self.assertEqual([r['id'] for r in result['records']], ['done'])
        self.assertEqual(result['records'][0]['status'], 'completed')
        self.assertEqual(result['summary']['skipped_secret'], 1)

    def test_sort_deduplicate_and_filter_by_modified_time(self):
        old = self.row('old', timestamp='2020-01-01T00:00:00Z')
        fresh = self.row('fresh')
        result = collect_apple.prepare({'records': [old, fresh, fresh]}, days=30, limit=1,
                                      now=datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertEqual([r['id'] for r in result['records']], ['fresh'])
        self.assertEqual(result['summary']['duplicates'], 1)
        self.assertEqual(result['summary']['skipped_old'], 1)

    def test_export_mode_does_not_call_apps_or_modify_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'synthetic.json'
            original = json.dumps({'records': [self.row()]})
            source.write_text(original)
            output = io.StringIO()
            with patch.object(collect_apple.subprocess, 'run') as run, contextlib.redirect_stdout(output):
                code = collect_apple.main(['--input-json', str(source), '--days', '0'])
            self.assertEqual(code, 0)
            run.assert_not_called()
            self.assertEqual(source.read_text(), original)
            self.assertEqual(len(json.loads(output.getvalue())['records']), 1)

    def test_live_error_never_echoes_raw_subprocess_output(self):
        raw = 'private fixture payload that must never be echoed'
        failure = subprocess.CompletedProcess([], 1, stdout=raw, stderr=raw)
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(collect_apple.sys, 'platform', 'darwin'), \
             patch.object(collect_apple.subprocess, 'run', return_value=failure), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(collect_apple.main(['--folder', 'Ideas']), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn(raw, errors.getvalue())

    def test_requires_explicit_scope(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            collect_apple.main([])

    def test_rejects_unknown_sources_and_unsafe_metadata(self):
        rows = [self.row(source='unknown'), self.row('safe', collection='API_KEY=synthetic_metadata')]
        result = collect_apple.prepare({'records': rows}, days=0)
        self.assertEqual(result['records'], [])

    def test_multiline_credentials_are_checked_before_json_escaping(self):
        rows = [self.row(text='An ordinary idea\n## Password\nsynthetic_canary_value'),
                self.row('second', text='AppSecret\nsynthetic_canary_value')]
        result = collect_apple.prepare({'records': rows}, days=0)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['summary']['skipped_secret'], 2)

    def test_pending_only_applies_to_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'synthetic.json'
            source.write_text(json.dumps({'records': [self.row('done', source='apple-reminders', status='completed'),
                                                       self.row('pending', source='apple-reminders', status='pending')]}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(collect_apple.main(['--input-json', str(source), '--days', '0', '--pending-only']), 0)
            self.assertEqual([r['id'] for r in json.loads(output.getvalue())['records']], ['pending'])

    @unittest.skipUnless(shutil.which('node'), 'Node is optional; needed only to simulate the JXA adapter')
    def test_ambiguous_collection_stops_before_reading_bodies(self):
        fixture = """
const calls = [];
global.Application = () => ({folders: {whose: () => () => [
  {get notes() { calls.push('body'); throw new Error('must not read'); }},
  {get notes() { calls.push('body'); throw new Error('must not read'); }}
]}});
"""
        script = fixture + collect_apple.JXA + "\nconst result = run([JSON.stringify({folders:['Ideas'],lists:[],days:0,limit:10})]); process.stdout.write(JSON.stringify({result:JSON.parse(result),calls}));"
        result = subprocess.run(['node', '-e', script], text=True, capture_output=True, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['result']['error'], 'ambiguous_collection')
        self.assertEqual(payload['calls'], [])


if __name__ == '__main__':
    unittest.main()
