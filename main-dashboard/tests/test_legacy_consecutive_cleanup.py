import ast
from pathlib import Path
import re
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'run_dashboard_update.py'


class LegacyConsecutiveCleanupTests(unittest.TestCase):
    def run_cleanup(self, failure=None):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'clear_consecutive_legacy_columns')
        self.calls = []
        def call(method, args, timeout):
            self.calls.append((method, args))
            if failure and len(self.calls) == 3:
                if isinstance(failure, Exception):
                    raise failure
                return failure
            return {'success': True}
        scope = {'WORKBOOK': 'authorized-main-workbook', 'mcp_call': call}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), scope)
        scope['clear_consecutive_legacy_columns']('generated-consecutive-summary')

    def test_bounded_calls_clear_entire_retired_area_and_styles_without_touching_manual_sheet(self):
        self.run_cleanup()
        covered = []
        self.assertEqual(len(self.calls), 60)
        for method, args in self.calls:
            self.assertEqual(method, 'clear_range')
            self.assertEqual(args['nodeId'], 'authorized-main-workbook')
            self.assertEqual(args['sheetId'], 'generated-consecutive-summary')
            self.assertEqual(args['type'], 'all')
            first, last = map(int, re.fullmatch(r'G(\d+):S(\d+)', args['range']).groups())
            self.assertLessEqual((last - first + 1) * 13, 6500)
            covered.extend(range(first, last + 1))
        self.assertEqual(covered, list(range(1, 6001)))

    def test_failure_stops_cleanup_without_claiming_partial_coverage_success(self):
        for failure in (RuntimeError('permission denied'), {'success': False, 'errorMsg': 'permission denied'}):
            with self.subTest(failure=str(failure)), self.assertRaisesRegex(RuntimeError, 'permission denied'):
                self.run_cleanup(failure)
            self.assertEqual(len(self.calls), 3)

    def test_only_named_generated_sheet_uses_legacy_cleanup(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        writer = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'write_sheet')
        guards = [node for node in ast.walk(writer) if isinstance(node, ast.If) and any(
            isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == 'clear_consecutive_legacy_columns'
            for child in ast.walk(ast.Module(body=node.body, type_ignores=[])))]
        self.assertEqual(len(guards), 1)
        self.assertEqual(ast.unparse(guards[0].test), "name == '连续2周及以上未完课'")


if __name__ == '__main__':
    unittest.main()
