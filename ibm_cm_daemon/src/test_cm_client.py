import unittest
from unittest.mock import patch, MagicMock
import requests # Import requests for requests.exceptions
import io # For BytesIO
import json # For json.dumps
from cm_client import CMClient, CMClientException, CMClientAuthenticationError, CMClientNotFoundError, CMClientServerError

class TestCMClient(unittest.TestCase):

    def setUp(self):
        self.api_config = {
            "endpoint": "http://fake-cm-api.com/cm8rest/v1",
            "servername": "test_server",
            "username": "test_user",
            "password": "test_password"
        }
        self.client = CMClient(self.api_config)

    @patch('cm_client.requests.request')
    def test_login_successful(self, mock_request):
        """Test successful login and token storage."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "test_token_123"}
        mock_request.return_value = mock_response

        self.assertTrue(self.client.login())
        self.assertEqual(self.client.token, "test_token_123")

        expected_login_url = self.api_config['endpoint'] + "/login"
        mock_request.assert_called_once_with(
            "POST",
            expected_login_url,
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            json={
                "servername": self.api_config['servername'],
                "username": self.api_config['username'],
                "password": self.api_config['password']
            },
            data=None,
            files=None,
            timeout=30
        )

    @patch('cm_client.requests.request')
    def test_login_failed_auth_error(self, mock_request):
        """Test failed login due to authentication error."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_request.return_value = mock_response

        with self.assertRaises(CMClientAuthenticationError) as context:
            self.client.login()

        self.assertIn("401", str(context.exception))
        self.assertIsNone(self.client.token)

    @patch('cm_client.requests.request')
    def test_login_failed_server_error(self, mock_request):
        """Test failed login due to server error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_request.return_value = mock_response

        with self.assertRaises(CMClientServerError) as context:
            self.client.login()

        self.assertIn("500", str(context.exception))
        self.assertIsNone(self.client.token)

    @patch('cm_client.requests.request')
    def test_login_successful_but_no_token_in_response(self, mock_request):
        """Test login appearing successful (200) but no token in response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Login OK, but no token field"}
        mock_request.return_value = mock_response

        with self.assertRaises(CMClientException) as context:
            self.client.login()

        self.assertIn("token not found in response", str(context.exception))
        self.assertIsNone(self.client.token)

    @patch('cm_client.requests.request')
    def test_ping_successful(self, mock_request):
        """Test successful ping."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "OK"} # Example response
        mock_request.return_value = mock_response

        # First, login to get a token (though ping might not need it)
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.json.return_value = {"token": "test_token_ping"}
        # Side effect allows different return values for multiple calls
        mock_request.side_effect = [login_response, mock_response]

        self.client.login()
        self.assertTrue(self.client.ping())

        ping_url = self.api_config['endpoint'] + "/ping"
        # mock_request.assert_any_call checks if ping_url was called at some point
        calls = mock_request.call_args_list
        self.assertTrue(any(call[0][1] == ping_url for call in calls))


    @patch('cm_client.requests.request')
    def test_ping_failed_server_down(self, mock_request):
        """Test failed ping when server is down (e.g., connection error)."""
        mock_request.side_effect = requests.exceptions.ConnectionError("Failed to connect")

        with self.assertRaises(CMClientException) as context:
            self.client.ping()
        self.assertIn("Connection error", str(context.exception))

    @patch('cm_client.requests.request')
    def test_ping_failed_server_error(self, mock_request):
        """Test failed ping due to server error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_request.return_value = mock_response

        # Ping will now raise CMClientServerError
        with self.assertRaises(CMClientServerError) as context:
            self.client.ping()
        self.assertIn("Server error: 500", str(context.exception))


    @patch('cm_client.requests.request')
    def test_authorization_header_added(self, mock_request):
        """Test that Authorization header is added correctly after login."""
        # Mock login
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.json.return_value = {"token": "auth_header_token"}

        # Mock response for a generic authed call
        authed_call_response = MagicMock()
        authed_call_response.status_code = 200
        authed_call_response.json.return_value = {"data": "some_data"}

        mock_request.side_effect = [login_response, authed_call_response]

        self.client.login()
        self.assertEqual(self.client.token, "auth_header_token")

        # Make a call that should use the token (e.g., a hypothetical get_items)
        # For this test, we can just call ping as it uses _make_request
        self.client.ping()

        # Check the headers of the second call (the ping call)
        args, kwargs = mock_request.call_args_list[1] # Get the arguments for the second call
        self.assertIn('headers', kwargs)
        self.assertIn('Authorization', kwargs['headers'])
        self.assertEqual(kwargs['headers']['Authorization'], "Bearer auth_header_token")

    @patch('cm_client.requests.request')
    def test_token_cleared_on_auth_error(self, mock_request):
        """Test that token is cleared if a non-login request gets 401/403."""
        # Mock login
        login_response = MagicMock()
        login_response.status_code = 200
        login_response.json.return_value = {"token": "token_to_be_cleared"}

        # Mock response for a generic authed call that fails with 401
        authed_call_response = MagicMock()
        authed_call_response.status_code = 401
        authed_call_response.text = "Unauthorized"

        mock_request.side_effect = [login_response, authed_call_response]

        self.client.login()
        self.assertIsNotNone(self.client.token)

        # Attempt a call that will fail with 401 (e.g., ping)
        with self.assertRaises(CMClientAuthenticationError):
            self.client.ping() # ping uses _make_request which should clear token

        self.assertIsNone(self.client.token, "Token should be cleared after a 401 error on a non-login request.")

    def test_constructor_missing_config(self):
        """Test CMClient constructor with missing API configuration keys."""
        with self.assertRaises(ValueError) as context:
            CMClient({})
        self.assertIn("'endpoint', 'servername', 'username', and 'password'", str(context.exception))

        with self.assertRaises(ValueError) as context:
            CMClient({"endpoint": "val", "servername": "val", "username": "val"}) # Missing password
        self.assertIn("'endpoint', 'servername', 'username', and 'password'", str(context.exception))

    # --- Tests for get_item_type_details ---
    @patch('cm_client.requests.request')
    def test_get_item_type_details_successful(self, mock_request):
        """Test successful retrieval of item type details."""
        item_type_name = "TestDoc"
        expected_url = f"{self.api_config['endpoint']}/itemtypes/{item_type_name}?include=attributes"
        expected_response_data = {"name": item_type_name, "attributes": [{"name": "Attr1"}]}

        # Simulate login first, then the actual call
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "item_type_token"}

        mock_item_type_response = MagicMock()
        mock_item_type_response.status_code = 200
        mock_item_type_response.json.return_value = expected_response_data

        mock_request.side_effect = [mock_login_response, mock_item_type_response]

        details = self.client.get_item_type_details(item_type_name)
        self.assertEqual(details, expected_response_data)

        # Check that login was called, then the get_item_type_details call
        self.assertEqual(mock_request.call_count, 2)
        args, kwargs = mock_request.call_args_list[1] # Second call
        self.assertEqual(args[0], "GET")
        self.assertEqual(args[1], expected_url)
        self.assertIn('Authorization', kwargs['headers'])
        self.assertEqual(kwargs['headers']['Authorization'], "Bearer item_type_token")

    @patch('cm_client.requests.request')
    def test_get_item_type_details_not_found(self, mock_request):
        """Test item type not found (404) for get_item_type_details."""
        item_type_name = "NonExistentType"

        mock_login_response = MagicMock() # For auto-login
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "test_token"}

        mock_item_type_response = MagicMock()
        mock_item_type_response.status_code = 404
        mock_item_type_response.text = "Item type not found"

        mock_request.side_effect = [mock_login_response, mock_item_type_response]

        with self.assertRaises(CMClientNotFoundError):
            self.client.get_item_type_details(item_type_name)

        self.assertEqual(mock_request.call_count, 2) # Login + actual call

    # --- Tests for create_document ---
    @patch('cm_client.requests.request')
    def test_create_document_successful(self, mock_request):
        # Imports io and json are now at the top of the file

        item_type_name = "MyDocument"
        attributes = [{"name": "Title", "value": "Test Document"}]
        parts_metadata = {"template": "ICMDRPROXY", "parts": [{"label": "doc", "mimetype": "application/pdf"}]}
        file_content = b"dummy PDF content"
        file_streams = [('contentParts1', ('test.pdf', io.BytesIO(file_content), 'application/pdf'))]

        expected_url = f"{self.api_config['endpoint']}/itemtypes/{item_type_name}/items"
        expected_response_data = {"pid": "new_doc_pid_123"}

        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "create_doc_token"}

        mock_create_response = MagicMock()
        mock_create_response.status_code = 201 # Typically 201 for created
        mock_create_response.json.return_value = expected_response_data

        mock_request.side_effect = [mock_login_response, mock_create_response]

        response = self.client.create_document(item_type_name, attributes, parts_metadata, file_streams)
        self.assertEqual(response, expected_response_data)

        self.assertEqual(mock_request.call_count, 2)
        args, kwargs = mock_request.call_args_list[1] # The actual create document call
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], expected_url)

        # Verify multipart payload structure (simplified check)
        self.assertIn('files', kwargs)
        sent_files = dict(kwargs['files']) # Convert list of tuples to dict for easier checking
        self.assertIn('attributes', sent_files)
        self.assertEqual(sent_files['attributes'][1], json.dumps(attributes))
        self.assertIn('parts', sent_files)
        self.assertEqual(sent_files['parts'][1], json.dumps(parts_metadata))
        self.assertIn('contentParts1', sent_files)
        self.assertEqual(sent_files['contentParts1'][0], 'test.pdf')
        # self.assertEqual(sent_files['contentParts1'][1].read(), file_content) # BytesIO needs reset or careful read
        self.assertEqual(sent_files['contentParts1'][2], 'application/pdf')


    @patch('cm_client.requests.request')
    def test_create_document_invalid_item_type(self, mock_request):
        item_type_name = "InvalidType"
        attributes = [{"name": "Title", "value": "Test Document"}]
        parts_metadata = {"template": "ICMDRPROXY", "parts": [{"label": "doc", "mimetype": "text/plain"}]}
        file_streams = [('contentParts1', ('test.txt', io.BytesIO(b"text"), 'text/plain'))]

        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "test_token"}

        mock_create_response = MagicMock()
        mock_create_response.status_code = 404 # Or other error like 400
        mock_create_response.text = "Item type not found or invalid"

        mock_request.side_effect = [mock_login_response, mock_create_response]

        with self.assertRaises(CMClientNotFoundError): # Assuming 404 maps to this
            self.client.create_document(item_type_name, attributes, parts_metadata, file_streams)

    # --- Tests for update_item_attributes ---
    @patch('cm_client.requests.request')
    def test_update_item_attributes_successful(self, mock_request):
        pid = "doc_pid_abc"
        attributes = [{"name": "Status", "value": "Approved"}]
        expected_url = f"{self.api_config['endpoint']}/items/{pid}?newVersion=false&checkin=implicit"
        expected_response_data = {"pid": pid, "attributes": attributes}

        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "update_token"}

        mock_update_response = MagicMock()
        mock_update_response.status_code = 200
        mock_update_response.json.return_value = expected_response_data

        mock_request.side_effect = [mock_login_response, mock_update_response]

        response = self.client.update_item_attributes(pid, attributes)
        self.assertEqual(response, expected_response_data)

        self.assertEqual(mock_request.call_count, 2)
        args, kwargs = mock_request.call_args_list[1]
        self.assertEqual(args[0], "PATCH")
        self.assertEqual(args[1], expected_url)
        self.assertEqual(kwargs['json'], attributes)

    @patch('cm_client.requests.request')
    def test_update_item_attributes_new_version(self, mock_request):
        pid = "doc_pid_xyz"
        attributes = [{"name": "VersionLabel", "value": "2.0"}]
        expected_url = f"{self.api_config['endpoint']}/items/{pid}?newVersion=true&checkin=explicit"

        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "update_token_nv"}

        mock_update_response = MagicMock()
        mock_update_response.status_code = 200
        mock_update_response.json.return_value = {"pid": pid, "version": "2"}

        mock_request.side_effect = [mock_login_response, mock_update_response]

        self.client.update_item_attributes(pid, attributes, new_version=True, checkin='explicit')

        self.assertEqual(mock_request.call_count, 2)
        args, kwargs = mock_request.call_args_list[1]
        self.assertEqual(args[0], "PATCH")
        self.assertEqual(args[1], expected_url)

    @patch('cm_client.requests.request')
    def test_update_item_attributes_not_found(self, mock_request):
        pid = "non_existent_pid"
        attributes = [{"name": "Status", "value": "Archived"}]

        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "test_token"}

        mock_update_response = MagicMock()
        mock_update_response.status_code = 404
        mock_update_response.text = "Item not found"

        mock_request.side_effect = [mock_login_response, mock_update_response]

        with self.assertRaises(CMClientNotFoundError):
            self.client.update_item_attributes(pid, attributes)

    @patch('cm_client.requests.request')
    def test_auto_login_feature(self, mock_request):
        """Test that a method requiring auth attempts login if no token."""
        self.client.token = None # Ensure no token initially
        item_type_name = "AutoLoginTest"
        expected_url = f"{self.api_config['endpoint']}/itemtypes/{item_type_name}?include=attributes"

        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.json.return_value = {"token": "auto_login_token"}

        mock_api_call_response = MagicMock()
        mock_api_call_response.status_code = 200
        mock_api_call_response.json.return_value = {"name": item_type_name}

        mock_request.side_effect = [mock_login_response, mock_api_call_response]

        self.client.get_item_type_details(item_type_name)

        self.assertEqual(mock_request.call_count, 2)
        # First call is login
        login_args, login_kwargs = mock_request.call_args_list[0]
        self.assertEqual(login_args[1], self.client.login_url)
        # Second call is the actual API method
        api_args, api_kwargs = mock_request.call_args_list[1]
        self.assertEqual(api_args[1], expected_url)
        self.assertIn('Authorization', api_kwargs['headers'])
        self.assertEqual(api_kwargs['headers']['Authorization'], "Bearer auto_login_token")
        self.assertEqual(self.client.token, "auto_login_token")

    @patch('cm_client.requests.request')
    def test_auto_login_failure_propagates(self, mock_request):
        """Test that if auto-login fails, the exception propagates."""
        self.client.token = None # Ensure no token initially
        item_type_name = "AutoLoginFailTest"

        mock_login_response = MagicMock()
        mock_login_response.status_code = 401 # Login fails
        mock_login_response.text = "Unauthorized login attempt"
        mock_request.return_value = mock_login_response # Only one call expected: the failed login

        with self.assertRaises(CMClientAuthenticationError):
            self.client.get_item_type_details(item_type_name)

        self.assertEqual(mock_request.call_count, 1) # Only login attempt should happen
        self.assertIsNone(self.client.token)

if __name__ == '__main__':
    unittest.main()
