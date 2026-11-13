import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_dashboard_update as core


class AtomicStatusTests(unittest.TestCase):
    def test_status_updates_preserve_existing_run_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            status.write_text(json.dumps({'state': 'running', 'runId': 'owned-run-123', 'lastSuccessTime': '2026-11-09 21:33:10'}), encoding='utf-8')
            with patch.object(core, 'ROOT', Path(directory)), patch.object(core, 'STATUS', status):
                for state in ['running', 'error', 'success']:
                    core.set_status(state, 'status update')
                    self.assertEqual(json.loads(status.read_text(encoding='utf-8'))['runId'], 'owned-run-123')

    def test_locked_replace_retries_with_previous_state_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            previous = {'state': 'success', 'time': '2026-11-09 21:33:10'}
            status.write_text(json.dumps(previous), encoding='utf-8')
            original = Path.replace
            calls = []

            def replace(source, destination):
                calls.append(1)
                self.assertIsInstance(json.loads(source.read_text(encoding='utf-8')), dict)
                if len(calls) < 3:
                    self.assertEqual(json.loads(status.read_text(encoding='utf-8')), previous)
                    raise PermissionError('reader sharing conflict')
                return original(source, destination)

            with patch.object(core, 'ROOT', Path(directory)), patch.object(core, 'STATUS', status), patch.object(Path, 'replace', replace), patch.object(core.time, 'sleep'):
                core.set_status('running', 'writing', 'test')
            updated = json.loads(status.read_text(encoding='utf-8'))
            self.assertEqual(updated['lastSuccessTime'], previous['time'])
            self.assertEqual(updated['state'], 'running')
            self.assertEqual(len(calls), 3)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_persistent_sharing_conflict_is_bounded_and_keeps_old_status(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'
            previous = '{"state":"error","lastSuccessTime":"2026-11-09 21:33:10"}'
            status.write_text(previous, encoding='utf-8')
            with patch.object(core, 'ROOT', Path(directory)), patch.object(core, 'STATUS', status), patch.object(Path, 'replace', side_effect=PermissionError('locked')) as replace, patch.object(core.time, 'sleep'), self.assertRaises(PermissionError):
                core.set_status('running', 'writing')
            self.assertEqual(replace.call_count, 6)
            self.assertEqual(status.read_text(encoding='utf-8'), previous)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
