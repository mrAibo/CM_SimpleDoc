import unittest
from unittest import mock
import os
import json
import sys

# Add project root to sys.path to allow importing get_token
# This assumes 'get_token.py' is in the project root and 'tests' is a subdir.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

import get_token # Import the script we want to test

class TestGetToken(unittest.TestCase):

    def setUp(self):
        # Create a dummy credentials file for tests
        self.credentials_dir = os.path.join(project_root, 'config')
        self.credentials_file = os.path.join(self.credentials_dir, 'credentials.json')
        os.makedirs(self.credentials_dir, exist_ok=True)
        with open(self.credentials_file, 'w') as f:
            json.dump({
                "username": "testuser",
                "servername": "testserver",
                "login_url": "http://fake-cm-server/login",
                "login_host": "fake-cm-server",
                "service_name": "test_service",
                "keyring_username": "test_keyring_user"
            }, f)
        
        # Patch get_token.py's DEFAULT_CREDENTIALS_PATH to use our test file path
        # This ensures get_token.load_credentials() reads our dummy file.
        self.credentials_patcher = mock.patch('get_token.DEFAULT_CREDENTIALS_PATH', self.credentials_file)
        self.mock_default_credentials_path = self.credentials_patcher.start()

    def tearDown(self):
        self.credentials_patcher.stop()
        # Clean up the dummy credentials file
        if os.path.exists(self.credentials_file):
            os.remove(self.credentials_file)
        # Attempt to remove directory only if it's the specific one we might have created
        # and it's empty. This is a simplified cleanup.
        if self.credentials_dir == os.path.join(project_root, 'config') and os.path.exists(self.credentials_dir) and not os.listdir(self.credentials_dir):
            try:
                os.rmdir(self.credentials_dir)
            except OSError:
                pass # Ignore if not empty, another test might be using it or left files.


    @mock.patch('get_token.requests.post')
    @mock.patch('get_token.keyring.get_password')
    def test_fetch_token_success_plain_text(self, mock_keyring_get_password, mock_post):
        mock_keyring_get_password.return_value = "dummy_keyring_password"
        mock_response = mock.Mock()
        # or ensure it can be influenced by environment for testing if needed.
        # For this test, we assume get_token.py constructs path like:
        # os.path.join(os.path.dirname(get_token.__file__), 'config', 'credentials.json')
        # which should work if get_token.py is in project_root.

        mock_response.status_code = 200
        mock_response.text = "Bearer test_token_123"
        mock_response.headers = {'Content-Type': 'text/plain'}
        def json_side_effect(*args, **kwargs): # Define side effect for .json()
            raise json.JSONDecodeError("Not JSON", "test", 0)
        mock_response.json.side_effect = json_side_effect
        mock_post.return_value = mock_response

        token = get_token.fetch_token()
        self.assertEqual(token, "test_token_123")
        mock_keyring_get_password.assert_called_once_with("test_service", "test_keyring_user")
        mock_post.assert_called_once_with(
            "http://fake-cm-server/login",
            headers={"Content-Type": "application/json", "Host": "fake-cm-server"},
            json={"username": "testuser", "password": "dummy_keyring_password", "servername": "testserver"},
            timeout=10 
        )

    @mock.patch('get_token.requests.post')
    @mock.patch('get_token.keyring.get_password')
    def test_fetch_token_success_json_response(self, mock_keyring_get_password, mock_post):
        mock_keyring_get_password.return_value = "dummy_keyring_password"
        mock_response = mock.Mock()
        mock_response.status_code = 200
        # Simulate a non "Bearer " prefixed body, forcing JSON parse
        mock_response.text = '{"token": "json_token_456"}' 
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.json.return_value = {"token": "json_token_456"}
        mock_post.return_value = mock_response

        token = get_token.fetch_token()
        self.assertEqual(token, "json_token_456")
        mock_keyring_get_password.assert_called_once_with("test_service", "test_keyring_user")
        mock_post.assert_called_once_with(
            "http://fake-cm-server/login",
            headers={"Content-Type": "application/json", "Host": "fake-cm-server"},
            json={"username": "testuser", "password": "dummy_keyring_password", "servername": "testserver"},
            timeout=10
        )

    @mock.patch('get_token.requests.post')
    @mock.patch('get_token.keyring.get_password')
    def test_fetch_token_http_error(self, mock_keyring_get_password, mock_post):
        mock_keyring_get_password.return_value = "dummy_keyring_password"
        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        token = get_token.fetch_token()
        self.assertIsNone(token)
        mock_keyring_get_password.assert_called_once_with("test_service", "test_keyring_user")


    @mock.patch('get_token.requests.post')
    @mock.patch('get_token.keyring.get_password')
    def test_fetch_token_request_exception(self, mock_keyring_get_password, mock_post):
        mock_keyring_get_password.return_value = "dummy_keyring_password"
        mock_post.side_effect = get_token.requests.exceptions.RequestException("Connection error")

        token = get_token.fetch_token()
        self.assertIsNone(token)
        mock_keyring_get_password.assert_called_once_with("test_service", "test_keyring_user")

    @mock.patch('get_token.requests.post')
    @mock.patch('get_token.keyring.get_password')
    def test_fetch_token_malformed_bearer(self, mock_keyring_get_password, mock_post):
        mock_keyring_get_password.return_value = "dummy_keyring_password"
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.text = "Bearer " # Empty token
        mock_response.headers = {'Content-Type': 'text/plain'}
        def json_side_effect(*args, **kwargs):
            raise json.JSONDecodeError("Not JSON", "test", 0)
        mock_response.json.side_effect = json_side_effect
        mock_post.return_value = mock_response
        
        token = get_token.fetch_token()
        self.assertIsNone(token)
        mock_keyring_get_password.assert_called_once_with("test_service", "test_keyring_user")

    @mock.patch('get_token.keyring.get_password')
    def test_fetch_token_keyring_password_not_found(self, mock_keyring_get_password):
        mock_keyring_get_password.return_value = None # Simulate password not in keyring
        
        # To capture stderr:
        # import io
        # captured_stderr = io.StringIO()
        # with mock.patch('sys.stderr', new=captured_stderr):
        #    token = get_token.fetch_token()
        # self.assertIn("Password not found in keyring", captured_stderr.getvalue())
        
        token = get_token.fetch_token()
        self.assertIsNone(token)
        mock_keyring_get_password.assert_called_once_with("test_service", "test_keyring_user")

    def test_load_credentials_missing_keyring_config(self):
        # Test what happens if service_name or keyring_username are missing from credentials file
        with open(self.credentials_file, 'w') as f:
            json.dump({
                "username": "testuser", # keyring_username will fall back to this
                # "service_name": "test_service", # Missing service_name
                "login_url": "http://fake-cm-server/login",
                "login_host": "fake-cm-server",
                "servername": "testserver"
            }, f)
        
        creds = get_token.load_credentials()
        self.assertIsNone(creds) # Should fail because service_name is missing

        with open(self.credentials_file, 'w') as f:
            json.dump({
                # "username": "testuser", # Missing username (and no keyring_username)
                "service_name": "test_service", 
                "login_url": "http://fake-cm-server/login",
                "login_host": "fake-cm-server",
                "servername": "testserver"
            }, f)
        creds = get_token.load_credentials()
        self.assertIsNone(creds) # Should fail because keyring_username (and fallback username) is missing


    @mock.patch('get_token.open', new_callable=mock.mock_open)
    def test_load_credentials_file_not_found(self, mock_open_custom):
        # This test uses the mocked DEFAULT_CREDENTIALS_PATH from setUp
        # We need to ensure the mock_open used by load_credentials raises FileNotFoundError
        mock_open_custom.side_effect = FileNotFoundError
        
        creds = get_token.load_credentials() # Uses the path patched in setUp
        self.assertIsNone(creds)
        mock_open_custom.assert_called_once_with(self.credentials_file, 'r')


    @mock.patch('get_token.open', new_callable=mock.mock_open, read_data="this is not json")
    def test_load_credentials_json_decode_error(self, mock_file_open_custom):
        # This test uses the mocked DEFAULT_CREDENTIALS_PATH from setUp
        creds = get_token.load_credentials()
        self.assertIsNone(creds)
        mock_file_open_custom.assert_called_once_with(self.credentials_file, 'r')


if __name__ == '__main__':
    unittest.main()
