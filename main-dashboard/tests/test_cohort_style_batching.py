"""Verify bounded cohort styles retain every cell and cohort/severity color."""
import ast
import re
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'run_dashboard_update.py'


class CohortStyleBatchingTests(unittest.TestCase):
    def capture(self, count):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'style_cohort_exception_sheet', 'col_letter'}]
        calls = []
        namespace = {'WORKBOOK': 'offline', 'mcp_call': lambda method, arguments: calls.append((method, arguments))}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), namespace)
        rows = [[f'cohort-{index // 133}', 'teacher', '上周准时参播下降' if index % 2 else '本周未完课'] + [''] * 21 for index in range(count)]
        namespace['style_cohort_exception_sheet']('sheet', {'columns': ['column'] * 24, 'data': rows}, False)
        return calls

    def test_real_532_rows_cover_exact_bounds_and_preserve_all_styles(self):
        calls = self.capture(532)
        styles = [arguments for method, arguments in calls if method == 'update_range']
        self.assertEqual([style['rangeAddress'] for style in styles], ['A1:X1', 'A2:X151', 'A152:X301', 'A302:X451', 'A452:X533'])
        header = styles[0]
        self.assertEqual(header['backgroundColors'], [['#173F5F'] * 24])
        coverage = []
        palette = ['#EAF3F8', '#EDF6E8', '#FFF1E6', '#F1EDFA']
        for style in styles[1:]:
            first, last = map(int, re.fullmatch(r'A(\d+):X(\d+)', style['rangeAddress']).groups())
            count = last - first + 1
            self.assertLessEqual(count * 24, 3600)
            coverage.extend(range(first, last + 1))
            for field in ['backgroundColors', 'fontColors', 'fontWeights', 'fontSizes', 'horizontalAlignments', 'verticalAlignments']:
                self.assertEqual(len(style[field]), count)
                self.assertTrue(all(len(row) == 24 for row in style[field]))
            self.assertEqual(style['wordWrap'], 'autoWrap')
            for offset, row_number in enumerate(range(first, last + 1)):
                index = row_number - 2
                down = index % 2 == 1
                expected_fill = [palette[index // 133]] * 5 + [('#FCE8E6' if down else '#E8F7F2')] * 2 + ['#F5F7F9'] + ['#E6F1F7'] * 7 + ['#E9F4E7'] * 7 + ['#F5F7F9'] * 2
                font = '#A3322E' if down else '#116F5E'
                expected_fonts = ['#233746', '#233746', font, '#233746', '#233746'] + [font] * 2 + ['#233746'] * 17
                self.assertEqual(style['backgroundColors'][offset], expected_fill)
                self.assertEqual(style['fontColors'][offset], expected_fonts)
                self.assertEqual(style['fontWeights'][offset], ['bold'] * 3 + ['normal'] * 21)
                self.assertEqual(style['fontSizes'][offset], [9] * 24)
                self.assertEqual(style['horizontalAlignments'][offset], ['center'] * 24)
                self.assertEqual(style['verticalAlignments'][offset], ['middle'] * 24)
        self.assertEqual(coverage, list(range(2, 534)))
        filter_call = next(arguments for method, arguments in calls if method == 'create_filter')
        self.assertEqual(filter_call['range'], 'A1:X533')

    def test_empty_and_chunk_boundaries(self):
        for count in [0, 1, 149, 150, 151, 300, 301]:
            with self.subTest(count=count):
                styles = [arguments for method, arguments in self.capture(count) if method == 'update_range'][1:]
                coverage = []
                for style in styles:
                    first, last = map(int, re.fullmatch(r'A(\d+):X(\d+)', style['rangeAddress']).groups())
                    self.assertLessEqual(last - first + 1, 150)
                    coverage.extend(range(first, last + 1))
                self.assertEqual(coverage, list(range(2, count + 2)))


if __name__ == '__main__':
    unittest.main()
