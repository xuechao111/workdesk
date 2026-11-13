import io
import json
import unittest
from unittest.mock import Mock, patch

import run_dashboard_update as core


class McpOperationErrors(unittest.TestCase):
    def responses(self, name, payloads, attempts=3, arguments=None):
        opener = Mock()
        opener.open.side_effect = [io.BytesIO(json.dumps({'result': {'content': [{'text': json.dumps(payload)}]}}).encode()) for payload in payloads]
        with patch.object(core.urllib.request, 'build_opener', return_value=opener), patch.object(core.time, 'sleep'):
            value = core.mcp_call(name, arguments or {'sheetId': 'fixture'}, attempts=attempts)
        return value, opener.open.call_count

    def test_transient_upstream_read_failure_retries_without_losing_data(self):
        failure = {'success': False, 'errorCode': 'internalError', 'errorMsg': "Can't connect to upstream"}
        result = {'values': [['verified', 17]]}
        value, calls = self.responses('get_range', [failure, failure, result])
        self.assertEqual(value, result)
        self.assertEqual(calls, 3)

    def test_incomplete_write_and_permission_error_are_not_retried(self):
        for name, message in [('update_range', "Can't connect to upstream"), ('get_range', 'Permission denied')]:
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, message):
                self.responses(name, [{'success': False, 'errorMsg': message}])

    def test_complete_literal_overwrite_retries_identical_request(self):
        for address, values in [('A2:B3', [['one', 1], ['two', 2]]), ('AA10:AB10', [[True, None]]), ('$A$1', [[0]])]:
            arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', 'rangeAddress': address, 'values': values, 'format': 'auto'}
            failure = {'success': False, 'errorCode': 'internalError', 'errorMsg': "Can't connect to upstream"}
            opener = Mock()
            opener.open.side_effect = [io.BytesIO(json.dumps({'result': result}).encode()) for result in [failure, failure, {'success': True}]]
            with self.subTest(address=address), patch.object(core.urllib.request, 'build_opener', return_value=opener), patch.object(core.time, 'sleep'):
                self.assertTrue(core.mcp_call('update_range', arguments)['success'])
            self.assertEqual(opener.open.call_count, 3)
            requests = [json.loads(call.args[0].data) for call in opener.open.call_args_list]
            self.assertEqual([request['params']['arguments'] for request in requests], [arguments] * 3)

    def test_literal_overwrite_rejects_formulas_shapes_unknown_and_dynamic_ranges(self):
        base = {'nodeId': 'workbook', 'sheetId': 'fixture', 'rangeAddress': 'A1:B1', 'values': [['student', 1]]}
        invalid = [
            {'formulas': [['=NOW()', '']]}, {'append': True}, {'unknown': True}, {'format': 'formula'},
            {'rangeAddress': 'A:B'}, {'rangeAddress': 'B1:A1'}, {'rangeAddress': 'A1:B2'},
            {'values': [['=NOW()', 1]]}, {'values': [['student']]}, {'values': [['student', {}]]},
            {'values': [['student', float('nan')]]}, {'values': []}, {'nodeId': ''}, {'sheetId': ''},
            {'range': 'A1:B1'}, {'values': [['student', 1], ['extra', 2]]},
        ]
        failure = {'success': False, 'errorMsg': 'COMM_ERROR connection closed'}
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, 'COMM_ERROR'):
                self.responses('update_range', [failure], arguments={**base, **changes})

    def test_value_overwrite_retry_budget_and_rejections(self):
        arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', 'rangeAddress': 'A1', 'values': [['data']]}
        for message, count in [('COMM_ERROR connection closed', 3), ('COMM_ERROR permission denied', 1), ('COMM_ERROR invalid parameter', 1), ('COMM_ERROR MERGED_CELLS_CONFLICT', 1)]:
            opener = Mock()
            opener.open.side_effect = [io.BytesIO(json.dumps({'result': {'success': False, 'errorMsg': message}}).encode()) for _ in range(count)]
            with self.subTest(message=message), patch.object(core.urllib.request, 'build_opener', return_value=opener), patch.object(core.time, 'sleep'), self.assertRaises(RuntimeError):
                core.mcp_call('update_range', arguments)
            self.assertEqual(opener.open.call_count, count)

    def test_sheet_writer_preserves_original_error_and_range_schema(self):
        with patch.object(core, 'load_sheet_ids', return_value={'fixture': 'sheet'}), patch.object(core, 'style_layout_initialized', return_value=True), patch.object(core, 'mcp_call', side_effect=RuntimeError("Can't connect to upstream")) as call, self.assertRaisesRegex(RuntimeError, "Can't connect to upstream"):
            core.write_sheet('fixture', {'columns': ['name'], 'data': [['student']]})
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[1]['rangeAddress'], 'A1:A2')
        self.assertNotIn('range', call.call_args.args[1])

    def test_absolute_sheet_settings_retry_without_schema_mutation(self):
        arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', 'frozenRowCount': 1, 'frozenColumnCount': 5, 'tabColor': '#78A9C5'}
        failure = {'success': False, 'errorMsg': 'HSFTimeOutException'}
        value, count = self.responses('update_sheet', [failure, {'success': True}], arguments=arguments)
        self.assertTrue(value['success'])
        self.assertEqual(count, 2)
        for changes in [{'name': 'renamed'}, {'rowCount': 10}, {'frozenRowCount': -1}, {'tabColor': 'unknown'}]:
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.responses('update_sheet', [failure], arguments={**arguments, **changes})

    def test_read_retry_budget_is_bounded(self):
        failure = {'success': False, 'errorMsg': "Can't connect to upstream"}
        with self.assertRaisesRegex(RuntimeError, "Can't connect"):
            self.responses('get_range', [failure] * 3)

    def test_interrupted_fixed_clear_retries_same_range(self):
        failure = {'success': False, 'errorCode': 'internalError', 'errorMsg': 'COMM_ERROR: Invalid call is removed because connection has been closed suddenly'}
        arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', 'range': 'A505:X6000', 'type': 'content'}
        result, calls = self.responses('clear_range', [failure, failure, {'success': True}], arguments=arguments)
        self.assertTrue(result['success'])
        self.assertEqual(calls, 3)
        self.assertEqual(arguments['range'], 'A505:X6000')

    def test_clear_failure_budget_and_rejection_are_bounded(self):
        arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', 'range': 'A505:X6000', 'type': 'content'}
        for message, count in [('COMM_ERROR connection closed', 3), ('COMM_ERROR Permission denied', 1), ('COMM_ERROR MERGED_CELLS_CONFLICT', 1)]:
            with self.subTest(message=message):
                opener = Mock()
                payload = {'success': False, 'errorMsg': message}
                opener.open.side_effect = [io.BytesIO(json.dumps({'result': payload}).encode()) for _ in range(count)]
                with patch.object(core.urllib.request, 'build_opener', return_value=opener), patch.object(core.time, 'sleep'), self.assertRaises(RuntimeError):
                    core.mcp_call('clear_range', arguments)
                self.assertEqual(opener.open.call_count, count)

    def test_dynamic_or_incomplete_clear_request_is_not_retried(self):
        failure = {'success': False, 'errorMsg': 'COMM_ERROR connection closed'}
        for arguments in [
            {'sheetId': 'fixture', 'range': 'A1:X6000', 'type': 'content'},
            {'nodeId': 'workbook', 'sheetId': 'fixture', 'range': 'A:X', 'type': 'content'},
            {'nodeId': 'workbook', 'sheetId': 'fixture', 'range': 'A1:X6000'},
        ]:
            with self.subTest(arguments=arguments), self.assertRaisesRegex(RuntimeError, 'COMM_ERROR'):
                self.responses('clear_range', [failure], arguments=arguments)

    def test_fixed_style_retries_transient_upstream_timeout(self):
        for error in ['HSFTimeOutException: request is already timeout Timeout 6000', 'COMM_ERROR connection has been closed suddenly']:
            for range_key in ['range', 'rangeAddress']:
                with self.subTest(error=error, range_key=range_key):
                    failure = {'success': False, 'errorCode': 'internalError', 'errorMsg': error}
                    arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', range_key: 'A2:X900', 'backgroundColors': [['#FFFFFF']], 'wordWrap': 'autoWrap'}
                    result, count = self.responses('update_range', [failure, failure, {'success': True}], arguments=arguments)
                    self.assertTrue(result['success'])
                    self.assertEqual(count, 3)

    def test_checkpoint_busy_retries_only_safe_request_shapes(self):
        busy = {'success': False, 'errorCode': 'model.checkpoint.refuse', 'errorMsg': 'The workbook cannot be loaded right now because the service is busy. Wait a moment and try again.'}
        arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', 'rangeAddress': 'A2:X151', 'fontSizes': [[9]]}
        value, count = self.responses('update_range', [busy, busy, {'success': True}], arguments=arguments)
        self.assertTrue(value['success'])
        self.assertEqual(count, 3)
        for method, unsafe in [('update_range', {**arguments, 'append': True}), ('create_sheet', {'nodeId': 'workbook', 'name': 'new'})]:
            with self.subTest(method=method), self.assertRaisesRegex(RuntimeError, 'model.checkpoint.refuse'):
                self.responses(method, [busy], arguments=unsafe)
        for failure in [
            {**busy, 'errorMsg': busy['errorMsg'] + ' Permission denied'},
            {**busy, 'errorMsg': 'Workbook permission was refused'},
            {**busy, 'errorCode': 'INVALID_REQUEST'},
        ]:
            with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                self.responses('update_range', [failure], arguments=arguments)

    def test_styles_do_not_make_data_or_unknown_arguments_retryable(self):
        failure = {'success': False, 'errorMsg': 'HSFTimeOutException: request is already timeout Timeout 6000'}
        base = {'nodeId': 'workbook', 'sheetId': 'fixture', 'rangeAddress': 'A2:X900', 'fontSizes': [[10]]}
        for extra in [{'values': [['student']]}, {'formulas': [['=1']]}, {'format': 'auto'}, {'unknownField': True}, {'range': 'A2:X900'}]:
            with self.subTest(extra=extra), self.assertRaisesRegex(RuntimeError, 'HSFTimeOutException'):
                self.responses('update_range', [failure], arguments={**base, **extra})
        for changes in [{'rangeAddress': 'A:X'}, {'nodeId': ''}, {'sheetId': ''}]:
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.responses('update_range', [failure], arguments={**base, **changes})

    def test_style_retry_budget_and_permission_conflict_stop(self):
        arguments = {'nodeId': 'workbook', 'sheetId': 'fixture', 'rangeAddress': 'A1', 'numberFormat': '0'}
        for message, count in [('HSFTimeOutException', 3), ('HSFTimeOutException permission denied', 1), ('COMM_ERROR MERGED_CELLS_CONFLICT', 1)]:
            with self.subTest(message=message):
                opener = Mock()
                opener.open.side_effect = [io.BytesIO(json.dumps({'result': {'success': False, 'errorMsg': message}}).encode()) for _ in range(count)]
                with patch.object(core.urllib.request, 'build_opener', return_value=opener), patch.object(core.time, 'sleep'), self.assertRaises(RuntimeError):
                    core.mcp_call('update_range', arguments)
                self.assertEqual(opener.open.call_count, count)

    def call(self, result):
        response = io.BytesIO(json.dumps(result).encode('utf-8'))
        opener = Mock()
        opener.open.return_value = response
        with patch.object(core.urllib.request, 'build_opener', return_value=opener):
            return core.mcp_call('update_range', {'sheetId': 'fixture'}, attempts=1)

    def test_merged_cell_conflict_stops_even_when_transport_succeeds(self):
        payload = {'success': False, 'errorCode': 'MERGED_CELLS_CONFLICT', 'errorMsg': 'Unmerge header first'}
        with self.assertRaisesRegex(RuntimeError, 'MERGED_CELLS_CONFLICT.*Unmerge header first'):
            self.call({'result': {'content': [{'type': 'text', 'text': json.dumps(payload)}]}})

    def test_tool_error_flag_stops_plain_text_result(self):
        with self.assertRaisesRegex(RuntimeError, 'permission denied'):
            self.call({'result': {'isError': True, 'content': [{'type': 'text', 'text': 'permission denied'}]}})

    def test_direct_operation_failure_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'FAILED'):
            self.call({'result': {'success': False, 'errorCode': 'FAILED'}})

    def test_business_rows_and_non_boolean_flags_remain_data(self):
        for payload in [
            {'success': True, 'data': [{'success': False, 'isError': True}]},
            {'success': 0, 'rows': [[0, False]]},
            {'values': [['success', False]]},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.call({'result': {'content': [{'text': json.dumps(payload)}]}}), payload)


if __name__ == '__main__':
    unittest.main()
