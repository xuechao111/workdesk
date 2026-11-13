"""Offline readback checks: same populated and cleared coverage, fewer reads."""
import ast
from pathlib import Path
import re
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'run_dashboard_update.py'

class ReadbackBatchingTests(unittest.TestCase):
    def verify(self, count=503, width=24, corrupt=None, failure=None, wrong_period=False):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        functions = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in {'verify_current_week_only', 'col_letter'}]
        period = '2026-10-26至2026-11-01'
        expected = [[f'learner-{r}'] + [''] * (width - 2) + [period] for r in range(count)]
        grid = [['header'] * width] + [row[:] for row in expected]
        if wrong_period and count:
            grid[1][-1] = 'old-period'
        if corrupt:
            while len(grid) < corrupt:
                grid.append([''] * width)
            grid[corrupt-1][0] = 'stale'
        calls = []
        def read(method, args, timeout):
            self.assertEqual(method, 'get_range')
            match = re.fullmatch(r'A(\d+):[A-Z]+(\d+)', args['range'])
            first, last = map(int, match.groups())
            self.assertLessEqual((last-first+1) * width, 30000)
            calls.append((first, last))
            if failure and len(calls) == failure:
                return {'success': False, 'errorMsg': 'read failed'}
            return [grid[i-1] if i <= len(grid) else [''] * width for i in range(first, last+1)]
        scope = {'WORKBOOK': 'offline', 'CURRENT_WEEK_CLEAR_LIMIT': 6000, 'mcp_call': read, 'find_rows': lambda x: x}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), scope)
        scope['verify_current_week_only']('sheet', {'columns': list(range(width)), 'data': expected})
        return calls

    def test_populated_and_near_tail_share_one_read(self):
        self.assertEqual(self.verify(), [(1, 524), (5981, 6000)])

    def test_empty_and_near_limit(self):
        self.assertEqual(self.verify(count=0, width=6), [(1, 21), (5981, 6000)])
        calls = self.verify(count=5989, width=24)
        self.assertEqual(calls[-1][1], 6000)

    def test_full_chunk_keeps_separate_near_probe(self):
        calls = self.verify(count=1249, width=24)
        self.assertEqual(calls, [(1, 1250), (1251, 1270), (5981, 6000)])

    def test_no_clear_probe_past_limit(self):
        calls = self.verify(count=6000, width=24)
        self.assertEqual(calls[-1][1], 6001)

    def test_corruption_and_failed_reads_never_succeed(self):
        for corrupt in (505, 520, 5981, 6000):
            with self.subTest(corrupt=corrupt), self.assertRaisesRegex(RuntimeError, '清空区'):
                self.verify(corrupt=corrupt)
        with self.assertRaisesRegex(RuntimeError, '当周数据校验失败'):
            self.verify(wrong_period=True)
        for failure in (1, 2):
            with self.subTest(failure=failure), self.assertRaisesRegex(RuntimeError, '校验读取失败'):
                self.verify(failure=failure)

class CleanupFallbackTests(unittest.TestCase):
    def run_cleanup(self, blocked=False, fail_chunk=False, transport=False, error="server model operate block"):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        functions = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in {'clear_stale_rows', 'col_letter'}]
        calls = []
        self.clear_calls = calls
        def call(method, args, timeout):
            calls.append((method, args))
            if len(calls) == 1 and blocked:
                if transport:
                    raise RuntimeError(error)
                return {'success': False, 'errorMsg': error}
            if len(calls) > 1 and fail_chunk:
                return {'success': False, 'errorMsg': 'permission denied'}
            return {'success': True}
        scope = {'WORKBOOK': 'offline', 'mcp_call': call}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), scope)
        scope['clear_stale_rows']('sheet', 24, 505, 6000, required=True)
        return calls

    def test_success_uses_one_clear(self):
        self.assertEqual(len(self.run_cleanup()), 1)

    def test_model_block_fallback_covers_every_original_cell(self):
        for transport in (False, True):
            calls = self.run_cleanup(blocked=True, transport=transport)
            covered = []
            for method, args in calls[1:]:
                self.assertEqual(method, 'clear_range')
                self.assertEqual(args['type'], 'content')
                match = re.fullmatch(r'A(\d+):X(\d+)', args['range'])
                first, last = map(int, match.groups())
                self.assertLessEqual((last-first+1)*24, 28000)
                covered.extend(range(first, last+1))
            self.assertEqual(covered, list(range(505, 6001)))

    def test_other_errors_are_not_split_or_hidden(self):
        with self.assertRaisesRegex(RuntimeError, 'permission denied'):
            self.run_cleanup(blocked=True, error='permission denied')
        self.assertEqual(len(self.clear_calls), 1)

    def test_failed_fallback_never_reports_success(self):
        with self.assertRaisesRegex(RuntimeError, '历史周数据失败.*permission denied'):
            self.run_cleanup(blocked=True, fail_chunk=True)

if __name__ == '__main__':
    unittest.main()
