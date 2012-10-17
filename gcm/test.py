import unittest
from gcm import *
import json
from mock import MagicMock
import time


# Helper method to return a different value for each call.
def create_side_effect(returns):
    def side_effect(*args, **kwargs):
        result = returns.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    return side_effect


class GCMTest(unittest.TestCase):
    def setUp(self):
        self.gcm = GCM('123api')
        self.data = {
            'param1': '1',
            'param2': '2'
        }
        self.mock_results_all_error = {
            "multicast_id": 216,
            "success": 0,
            "failure": 3,
            "canonical_ids": 0,
            'results': [
                    {'error': 'Unavailable'},
                    {"error": "InvalidRegistration"},
                    {"error": "NotRegistered"}
            ]
        }
        self.mock_results_all_success = {
            "multicast_id": 216,
            "success": 3,
            "failure": 0,
            "canonical_ids": 1,
            'results': [
                    {'message_id': '5678'},
                    {'message_id': '1234'},
                    {"message_id": "1:2342", "registration_id": "32"},
            ]
        }
        self.mock_mixed_request_ids = ['4', '8', '15', '16', '23', '42']
        self.mock_results_mixed = {
            # Here are JSON results for 6 recipients (IDs 4, 8, 15, 16, 23, and 42 respectively) with 3 messages successfully processed, 1 canonical registration ID returned, and 3 errors:
            #            In this example:
            #            First message: success, not required.
            #            Second message: should be resent (to registration ID 8).
            #            Third message: had an unrecoverable error (maybe the value got corrupted in the database).
            #            Fourth message: success, nothing required.
            #            Fifth message: success, but the registration ID should be updated in the server database (from 23 to 32).
            #            Sixth message: registration ID (42) should be removed from the server database because the application was uninstalled from the device.

            "multicast_id": 216,
            "success": 3,
            "failure": 3,
            "canonical_ids": 1,
            "results": [
                    {"message_id": "1:0408"},
                    {"error": "Unavailable"},
                    {"error": "InvalidRegistration"},
                    {"message_id": "1:1516"},
                    {"message_id": "1:2342", "registration_id": "32"},
                    {"error": "NotRegistered"}
            ]
        }
        time.sleep = MagicMock()

    def test_construct_payload(self):
        res = self.gcm.construct_payload(
            registration_ids=['1', '2'], data=self.data, collapse_key='foo',
            delay_while_idle=True, time_to_live=3600, is_json=True
        )
        payload = json.loads(res)
        for arg in ['registration_ids', 'data', 'collapse_key', 'delay_while_idle', 'time_to_live']:
            self.assertIn(arg, payload)

    def test_require_collapse_key(self):
        with self.assertRaises(GCMNoCollapseKeyException):
            self.gcm.construct_payload(registration_ids='1234', data=self.data, time_to_live=3600)

    def test_json_payload(self):
        reg_ids = ['12', '145', '56']
        json_payload = self.gcm.construct_payload(registration_ids=reg_ids, data=self.data)
        payload = json.loads(json_payload)

        self.assertIn('registration_ids', payload)
        self.assertEqual(payload['data'], self.data)
        self.assertEqual(payload['registration_ids'], reg_ids)

    def test_plaintext_payload(self):
        result = self.gcm.construct_payload(registration_ids='1234', data=self.data, is_json=False)

        self.assertIn('registration_id', result)
        self.assertIn('data.param1', result)
        self.assertIn('data.param2', result)

    def test_limit_reg_ids(self):
        reg_ids = range(1003)
        self.assertTrue(len(reg_ids) > 1000)
        with self.assertRaises(GCMTooManyRegIdsException):
            self.gcm.request_json(registration_ids=reg_ids, data=self.data)

    def test_missing_reg_id(self):
        with self.assertRaises(GCMMissingRegistrationException):
            self.gcm.request_json(registration_ids=[], data=self.data)

        with self.assertRaises(GCMMissingRegistrationException):
            self.gcm.request_plaintext(registration_id=None, data=self.data)

    def test_invalid_ttl(self):
        with self.assertRaises(GCMInvalidTtlException):
            self.gcm.construct_payload(
                registration_ids='1234', data=self.data, is_json=False, time_to_live=5000000
            )

        with self.assertRaises(GCMInvalidTtlException):
            self.gcm.construct_payload(
                registration_ids='1234', data=self.data, is_json=False, time_to_live=-10
            )

    def test_handle_plaintext_response(self):
        response = 'Error=NotRegistered'
        with self.assertRaises(GCMNotRegisteredException):
            self.gcm.handle_plaintext_response(response)

        response = 'id=23436576'
        res = self.gcm.handle_plaintext_response(response)
        self.assertIsNone(res)

        response = 'id=23436576\nregistration_id=3456'
        res = self.gcm.handle_plaintext_response(response)
        self.assertEqual(res, '3456')

    def test_retry_plaintext_request_ok(self):
        returns = [GCMUnavailableException(), GCMUnavailableException(), 'id=123456789']

        self.gcm.make_request = MagicMock(side_effect=create_side_effect(returns))
        res = self.gcm.request_plaintext(registration_id='1234', data=self.data)

        self.assertIsNone(res)
        self.assertEqual(self.gcm.make_request.call_count, 3)

    def test_retry_plaintext_request_fail(self):
        returns = [GCMUnavailableException(), GCMUnavailableException(), GCMUnavailableException()]

        self.gcm.make_request = MagicMock(side_effect=create_side_effect(returns))
        with self.assertRaises(IOError):
            self.gcm.request_plaintext(registration_id='1234', data=self.data, tries=2)

        self.assertEqual(self.gcm.make_request.call_count, 2)

    def test_json_request_ok(self):
        returns = [self.mock_results_all_success]
        json_returns = []
        for a_return in returns:
            json_returns.append(json.dumps(a_return))

        self.gcm.make_request = MagicMock(side_effect=create_side_effect(json_returns))
        registration_ids = ['abc', 'def', 'ghi']
        res = self.gcm.request_json(registration_ids=registration_ids, data=self.data)

        self.assertFalse(res.has_error())
        self.assertFalse(res.has_resends())
        self.assertTrue(res.has_canonical())
        self.assertTrue(len(res.get_canonical_ids(registration_ids)) == 1)
        self.assertEqual('ghi', res.get_canonical_ids(registration_ids)[0][0])

    def test_json_request_fail(self):
        returns = [self.mock_results_all_error]
        json_returns = []
        for a_return in returns:
            json_returns.append(json.dumps(a_return))
        self.gcm.make_request = MagicMock(side_effect=create_side_effect(json_returns))
        registration_ids = ['abc', 'def', 'ghi']
        res = self.gcm.request_json(registration_ids=registration_ids, data=self.data)
        self.assertFalse(res.has_success())
        self.assertTrue(res.has_error())
        self.assertTrue(res.has_resends())
        self.assertFalse(res.has_canonical())

    def test_retry_exponential_backoff(self):
        returns = [GCMUnavailableException(), GCMUnavailableException(), 'id=123456789']

        self.gcm.make_request = MagicMock(side_effect=create_side_effect(returns))
        self.gcm.request_plaintext(registration_id='1234', data=self.data)

        # time.sleep is actually mock object.
        self.assertEqual(time.sleep.call_count, 2)
        backoff = self.gcm.BACKOFF_INITIAL_DELAY_MS
        for arg in time.sleep.call_args_list:
            sleep_time = int(arg[0][0] * 1000)
            self.assertTrue(backoff / 2 <= sleep_time <= backoff * 3 / 2)
            if 2 * backoff < self.gcm.MAX_BACKOFF_DELAY_MS:
                backoff *= 2

    def test_json_wrapper(self):
        resp = GCM_response_wrapper(json.dumps(self.mock_results_mixed))
        self.assertTrue(resp.has_error())
        self.assertTrue(resp.has_canonical())
        self.assertTrue(resp.has_resends())
        self.assertTrue(resp.has_success())
        self.assertEquals(len(resp.get_unregister_errors(self.mock_mixed_request_ids)), 2)
        self.assertEquals(len(resp.get_canonical_ids(self.mock_mixed_request_ids)), 1)
        self.assertEquals(len(resp.get_resend_ids(self.mock_mixed_request_ids)), 1)
        self.assertRaises(resp.get_unregister_errors([]))
        self.assertRaises(resp.get_canonical_ids([]))
        self.assertRaises(resp.get_resend_ids([]))

if __name__ == '__main__':
    unittest.main()
