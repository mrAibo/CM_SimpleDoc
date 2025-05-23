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
                "password": "testpassword",
                "servername": "testserver",
                "login_url": "http://fake-cm-server/login",
                "login_host": "fake-cm-server"
            }, f)
        
        # Patch get_token.py's CREDENTIALS_FILE_PATH if it uses a global for it,
        # or ensure it can be influenced by environment for testing if needed.
        # For this test, we assume get_token.py constructs path like:
        # os.path.join(os.path.dirname(get_token.__file__), 'config', 'credentials.json')
        # which should work if get_token.py is in project_root.

    def tearDown(self):
        # Clean up the dummy credentials file
        if os.path.exists(self.credentials_file):
            os.remove(self.credentials_file)
        if os.path.exists(self.credentials_dir) and not os.listdir(self.credentials_dir):
            # Only remove if empty and it's the one we might have created parts of
            # Be cautious if other tests might use this directory concurrently
            if self.credentials_dir == os.path.join(project_root, 'config'): # Basic safety check
                 try: # Attempt to remove, but don't fail test if it's not empty due to other files
                     os.rmdir(self.credentials_dir)
                 except OSError:
                     pass


    @mock.patch('get_token.requests.post')
    def test_fetch_token_success_plain_text(self, mock_post):
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.text = "Bearer test_token_123"
        mock_response.headers = {'Content-Type': 'text/plain'}
        def json_side_effect(*args, **kwargs): # Define side effect for .json()
            raise json.JSONDecodeError("Not JSON", "test", 0)
        mock_response.json.side_effect = json_side_effect
        mock_post.return_value = mock_response

        token = get_token.fetch_token()
        self.assertEqual(token, "test_token_123")
        mock_post.assert_called_once_with(
            "http://fake-cm-server/login",
            headers={"Content-Type": "application/json", "Host": "fake-cm-server"},
            json={"username": "testuser", "password": "testpassword", "servername": "testserver"},
            timeout=10 
        )

    @mock.patch('get_token.requests.post')
    def test_fetch_token_success_json_response(self, mock_post):
        mock_response = mock.Mock()
        mock_response.status_code = 200
        # Simulate a non "Bearer " prefixed body, forcing JSON parse
        mock_response.text = '{"token": "json_token_456"}' 
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.json.return_value = {"token": "json_token_456"}
        mock_post.return_value = mock_response

        token = get_token.fetch_token()
        self.assertEqual(token, "json_token_456")

    @mock.patch('get_token.requests.post')
    def test_fetch_token_http_error(self, mock_post):
        mock_response = mock.Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        token = get_token.fetch_token()
        self.assertIsNone(token)

    @mock.patch('get_token.requests.post')
    def test_fetch_token_request_exception(self, mock_post):
        mock_post.side_effect = get_token.requests.exceptions.RequestException("Connection error")

        token = get_token.fetch_token()
        self.assertIsNone(token)

    @mock.patch('get_token.requests.post')
    def test_fetch_token_malformed_bearer(self, mock_post):
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

    @mock.patch('get_token.json.load') # Mock json.load in get_token's scope
    @mock.patch('get_token.open', new_callable=mock.mock_open) # Mock open globally for this test
    def test_load_credentials_file_not_found(self, mock_open_global, mock_json_load_get_token):
        # Simulate FileNotFoundError when open is called by load_credentials
        mock_open_global.side_effect = FileNotFoundError
        
        # We need to pass a path to load_credentials, even though open is mocked
        # The path doesn't have to exist because open is mocked.
        creds = get_token.load_credentials(credentials_path="dummy/path/credentials.json")
        self.assertIsNone(creds)


    @mock.patch('get_token.open', new_callable=mock.mock_open, read_data="invalid json")
    @mock.patch('get_token.os.path.exists') # Ensure exists returns true for the invalid json test
    def test_load_credentials_json_decode_error(self, mock_exists, mock_file_open):
        mock_exists.return_value = True # Assume file exists
        # The mock_open is already configured to return "invalid json"
        creds = get_token.load_credentials()
        self.assertIsNone(creds)

if __name__ == '__main__':
    unittest.main()
