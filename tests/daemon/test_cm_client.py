import unittest
from unittest import mock
import os
import sys
from datetime import datetime, timedelta

# Add project root and daemon package to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
daemon_path = os.path.join(project_root, 'daemon')
sys.path.insert(0, project_root)
sys.path.insert(0, daemon_path)

from cm_client import CMClient, CMConnectionError
import requests # For requests.exceptions.HTTPError

class TestCMClient(unittest.TestCase):

    def setUp(self):
        self.mock_auth_config = {
            "token_expiry_threshold_seconds": 300,
            "default_token_validity_seconds": 3600
        }
        self.client = CMClient("http://fake-api-base", self.mock_auth_config)

    @mock.patch('daemon.cm_client.subprocess.run')
    def test_fetch_new_token_from_script_success(self, mock_subprocess_run):
        mock_process_result = mock.Mock()
        mock_process_result.returncode = 0
        mock_process_result.stdout = "Some output\nSuccessfully extracted Bearer Token: new_script_token\nMore output"
        mock_process_result.stderr = ""
        mock_subprocess_run.return_value = mock_process_result

        result = self.client._fetch_new_token_from_script()
        self.assertTrue(result)
        self.assertEqual(self.client._bearer_token, "new_script_token")
        mock_subprocess_run.assert_called_once()
        # Check if the script path is correct (Python 3.7+ for full_script_path access)
        args, _ = mock_subprocess_run.call_args
        script_path_called = args[0][1] # command is like [sys.executable, script_path]
        expected_script_path = os.path.abspath(os.path.join(os.path.dirname(daemon_path), 'get_token.py')) # daemon_path is daemon_cm_client's dir
        self.assertEqual(script_path_called, expected_script_path)


    @mock.patch('daemon.cm_client.subprocess.run')
    def test_fetch_new_token_from_script_failure_script_error(self, mock_subprocess_run):
        mock_process_result = mock.Mock()
        mock_process_result.returncode = 1
        mock_process_result.stdout = ""
        mock_process_result.stderr = "Script error"
        mock_subprocess_run.return_value = mock_process_result

        result = self.client._fetch_new_token_from_script()
        self.assertFalse(result)
        self.assertIsNone(self.client._bearer_token)

    @mock.patch('daemon.cm_client.subprocess.run')
    def test_fetch_new_token_from_script_failure_no_token_in_output(self, mock_subprocess_run):
        mock_process_result = mock.Mock()
        mock_process_result.returncode = 0
        mock_process_result.stdout = "No token here"
        mock_process_result.stderr = ""
        mock_subprocess_run.return_value = mock_process_result

        result = self.client._fetch_new_token_from_script()
        self.assertFalse(result)
        self.assertIsNone(self.client._bearer_token)
    
    @mock.patch('daemon.cm_client.subprocess.run')
    def test_fetch_new_token_from_script_subprocess_exception(self, mock_subprocess_run):
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired(cmd="get_token.py", timeout=10)
        result = self.client._fetch_new_token_from_script()
        self.assertFalse(result)
        self.assertIsNone(self.client._bearer_token)


    @mock.patch('daemon.cm_client.CMClient._fetch_new_token_from_script')
    @mock.patch('daemon.cm_client.requests.Session.request')
    def test_request_auth_retry_success(self, mock_session_request, mock_fetch_token):
        # Initial call fails with 401
        mock_response_401 = mock.Mock()
        mock_response_401.status_code = 401
        mock_response_401.headers = {'Content-Type': 'application/json'}
        mock_response_401.json.return_value = {"error": "unauthorized"}
        # Configure raise_for_status for the 401 response
        http_error_401 = requests.exceptions.HTTPError(response=mock_response_401)
        mock_response_401.raise_for_status.side_effect = http_error_401
        
        # Second call (after token refresh) succeeds
        mock_response_200 = mock.Mock()
        mock_response_200.status_code = 200
        mock_response_200.headers = {'Content-Type': 'application/json'}
        mock_response_200.json.return_value = {"data": "success"}
        mock_response_200.raise_for_status.return_value = None # No error on 200

        mock_session_request.side_effect = [mock_response_401, mock_response_200]
        
        # Mock _fetch_new_token_from_script to succeed and set a token
        def fake_fetch_token():
            self.client._bearer_token = "newly_fetched_token"
            # Simulate _update_renewal_time behavior
            self.client._token_renews_at = datetime.now() + timedelta(seconds=self.mock_auth_config["default_token_validity_seconds"])
            return True
        mock_fetch_token.side_effect = fake_fetch_token

        response = self.client._request("GET", "/test-endpoint")

        self.assertEqual(response, {"data": "success"})
        self.assertEqual(mock_session_request.call_count, 2)
        mock_fetch_token.assert_called_once()
        # Check Authorization header on the second call
        second_call_headers = mock_session_request.call_args_list[1][1]['headers']
        self.assertEqual(second_call_headers['Authorization'], "Bearer newly_fetched_token")


    @mock.patch('daemon.cm_client.CMClient._fetch_new_token_from_script')
    @mock.patch('daemon.cm_client.requests.Session.request')
    def test_request_auth_retry_fails_after_token_refresh(self, mock_session_request, mock_fetch_token):
        # Initial call fails with 401
        mock_response_401_first = mock.Mock()
        mock_response_401_first.status_code = 401
        http_error_401_first = requests.exceptions.HTTPError(response=mock_response_401_first)
        mock_response_401_first.raise_for_status.side_effect = http_error_401_first
        
        # Second call also fails with 401
        mock_response_401_second = mock.Mock()
        mock_response_401_second.status_code = 401
        http_error_401_second = requests.exceptions.HTTPError(response=mock_response_401_second)
        mock_response_401_second.raise_for_status.side_effect = http_error_401_second

        mock_session_request.side_effect = [mock_response_401_first, mock_response_401_second]
        
        def fake_fetch_token():
            self.client._bearer_token = "newly_fetched_token_again"
            self.client._token_renews_at = datetime.now() + timedelta(seconds=3600)
            return True
        mock_fetch_token.side_effect = fake_fetch_token

        # The _request method should return None for unhandled 4xx errors that aren't CMConnectionError
        response = self.client._request("GET", "/test-endpoint")
        self.assertIsNone(response) 
        self.assertEqual(mock_session_request.call_count, 2)
        mock_fetch_token.assert_called_once()

    @mock.patch('daemon.cm_client.CMClient._fetch_new_token_from_script')
    @mock.patch('daemon.cm_client.requests.Session.request')
    def test_request_auth_retry_fails_token_refresh_fails(self, mock_session_request, mock_fetch_token):
        mock_response_401 = mock.Mock()
        mock_response_401.status_code = 401
        http_error_401 = requests.exceptions.HTTPError(response=mock_response_401)
        mock_response_401.raise_for_status.side_effect = http_error_401
        mock_session_request.return_value = mock_response_401 # Only called once

        mock_fetch_token.return_value = False # Simulate failure to get new token

        response = self.client._request("GET", "/test-endpoint")
        self.assertIsNone(response)
        self.assertEqual(mock_session_request.call_count, 1)
        mock_fetch_token.assert_called_once()

    @mock.patch('daemon.cm_client.requests.Session.request')
    def test_request_cm_connection_error_on_5xx(self, mock_session_request):
        mock_response_500 = mock.Mock()
        mock_response_500.status_code = 500
        http_error_500 = requests.exceptions.HTTPError(response=mock_response_500)
        mock_response_500.raise_for_status.side_effect = http_error_500
        mock_session_request.return_value = mock_response_500

        # Set a dummy token to bypass initial fetch for this test
        self.client._bearer_token = "dummy_token"
        self.client._token_renews_at = datetime.now() + timedelta(hours=1)

        with self.assertRaises(CMConnectionError):
            self.client._request("GET", "/test-endpoint")

if __name__ == '__main__':
    unittest.main()
