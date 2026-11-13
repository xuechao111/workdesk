import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import run_dashboard_update as core


class PartialCompletionTests(unittest.TestCase):
    def setUp(self):
        core.UPDATE_WARNINGS.clear()

    def tearDown(self):
        core.UPDATE_WARNINGS.clear()

    def test_exhausted_style_failure_does_not_mark_layout_or_block_next_sheet(self):
        table = {'columns': ['column'] * 24, 'data': [['term', 'teacher', '本周未完课'] + [''] * 21]}
        writes = []

        def call(method, arguments, *unused):
            if method == 'update_range' and 'values' in arguments:
                writes.append(arguments['sheetId'])
            if method == 'update_range' and 'values' not in arguments:
                raise RuntimeError('HSFTimeOutException after retries')
            return {'success': True}

        with ExitStack() as stack:
            stack.enter_context(patch.object(core, 'load_sheet_ids', return_value={'课期异常': 'cohort', 'next': 'next'}))
            stack.enter_context(patch.object(core, 'style_layout_initialized', return_value=False))
            mark = stack.enter_context(patch.object(core, 'mark_style_layout_initialized'))
            stack.enter_context(patch.object(core, 'clear_stale_rows'))
            stack.enter_context(patch.object(core, 'verify_current_week_only'))
            stack.enter_context(patch.object(core, 'apply_explicit_number_formats'))
            stack.enter_context(patch.object(core, 'mcp_call', side_effect=call))
            self.assertEqual(core.write_sheet('课期异常', table), 1)
            mark.assert_not_called()
            self.assertEqual(core.write_sheet('next', {'columns': ['name'], 'data': [['student']]}), 1)
            mark.assert_called_once_with('next', 'next')
        self.assertEqual(writes, ['cohort', 'next'])
        self.assertIn('课期异常样式更新警告', core.UPDATE_WARNINGS[0])
        with patch.object(core, 'set_status') as status:
            core.complete_update('complete', '课期异常 1 行；next 1 行')
        self.assertEqual(status.call_args.args[0], 'error')
        self.assertIn('数据已写入', status.call_args.args[1])
        self.assertIn('HSFTimeOutException', status.call_args.args[2])
        self.assertIn('next 1 行', status.call_args.args[2])

    def test_timestamp_failure_is_visible_and_not_marked_complete(self):
        def call(method, arguments, *unused):
            if method == 'update_range' and str(arguments.get('values', [['']])[0][0]).startswith('数据更新时间'):
                raise RuntimeError('COMM_ERROR timestamp failure')
            return {'success': True}

        with patch.object(core, 'load_sheet_ids', return_value={'fixture': 'sheet'}), patch.object(core, 'style_layout_initialized', return_value=False), patch.object(core, 'mark_style_layout_initialized') as mark, patch.object(core, 'clear_stale_rows'), patch.object(core, 'apply_explicit_number_formats'), patch.object(core, 'mcp_call', side_effect=call):
            self.assertEqual(core.write_sheet('fixture', {'columns': ['name'], 'data': [['student']]}, '2026-11-12 16:00:00'), 1)
            mark.assert_not_called()
        self.assertIn('更新时间单元格写入警告', core.UPDATE_WARNINGS[0])

    def test_partial_failure_preserves_only_proven_success_time(self):
        for previous in [
            {'state': 'success', 'time': '2026-11-09 21:33:10'},
            {'state': 'error', 'lastSuccessTime': '2026-11-09 21:33:10'},
            {},
        ]:
            with self.subTest(previous=previous), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                status = root / 'status.json'
                status.write_text(json.dumps(previous), encoding='utf-8')
                # Snapshot generation precedes DingTalk writes and is never
                # evidence of a successful external refresh.
                (root / 'dashboard-snapshot.json').write_text('{"updatedAt":"2026-11-12 16:00:00"}', encoding='utf-8')
                core.UPDATE_WARNINGS[:] = ['课期异常样式更新警告：HSFTimeOutException']
                with patch.object(core, 'STATUS', status), patch.object(core, 'ROOT', root):
                    core.set_status('running', 'writing')
                    core.complete_update('complete', 'all rows written')
                current = json.loads(status.read_text(encoding='utf-8'))
                self.assertEqual(current['state'], 'error')
                self.assertEqual(current['lastSuccessTime'], '2026-11-09 21:33:10' if previous else '')

    def test_clean_completion_keeps_existing_success_semantics(self):
        with patch.object(core, 'set_status') as status:
            core.complete_update('complete', 'all rows written')
        status.assert_called_once_with('success', 'complete', 'all rows written')


if __name__ == '__main__':
    unittest.main()
