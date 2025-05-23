import unittest
from unittest.mock import patch, Mock, mock_open
from datetime import datetime, timedelta
import os # Needed for os.path.basename if testing upload
import json # For metadata in upload

# Adjust import path if your project structure requires it (e.g., if 'daemon' is a top-level dir)
# Assuming 'daemon' is in the python path or this test is run from project root.
from daemon.cm_client import CMClient, CMConnectionError
# If requests is used directly by CMClient for some reason (it shouldn't be, should use self._session)
import requests 

class TestCMClient(unittest.TestCase):
    def setUp(self):
        self.mock_config_dict = {
            "ibm_cm_api_base_url": "http://fake-cm-api.com/api",
            "authentication": {
                "bearer_token": "initial_token",
                "token_renewal_url": "http://fake-cm-api.com/auth/renew",
                "token_expiry_threshold_seconds": 300,
                "initial_token_validity_seconds": 3600
            }
        }
        # Create client instance
        self.client = CMClient(
            self.mock_config_dict["ibm_cm_api_base_url"],
            self.mock_config_dict["authentication"]
        )

        # Patch the '_session.request' method of this specific client instance
        self.mock_session_request_patcher = patch.object(self.client._session, 'request')
        self.mock_session_request = self.mock_session_request_patcher.start()
        self.addCleanup(self.mock_session_request_patcher.stop) # Stop patch after test method

    def test_initial_token_present(self):
        self.assertEqual(self.client._bearer_token, "initial_token")

    def test_refresh_token_success(self):
        # Simulate token expiration
        self.client._token_renews_at = datetime.now() - timedelta(seconds=10)

        # Configure mock response for token renewal
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "new_refreshed_token", "expires_in": 1800}
        self.mock_session_request.return_value = mock_response

        self.assertTrue(self.client._refresh_token())
        self.assertEqual(self.client._bearer_token, "new_refreshed_token")
        # Check if the renewal time was updated (approximate check)
        self.assertTrue(self.client._token_renews_at > datetime.now() + timedelta(seconds=1800 - self.client.token_expiry_threshold_seconds - 60)) # -60 for buffer
        self.mock_session_request.assert_called_once_with(
            "POST", self.mock_config_dict["authentication"]["token_renewal_url"], timeout=10
        )
    
    def test_refresh_token_failure_api_error(self):
        self.client._token_renews_at = datetime.now() - timedelta(seconds=10)
        mock_response = Mock()
        mock_response.status_code = 500
        # Simulate the behavior of response.raise_for_status() for a 500 error
        mock_response.raise_for_status.side_effect = CMConnectionError("Server Error") # Simulate HTTPError leading to CMConnectionError
        # For the actual _refresh_token error handling, it expects requests.exceptions.HTTPError
        # and then checks status code. Let's align with that.
        mock_http_error = requests.exceptions.HTTPError("Server Error", response=mock_response)
        mock_http_error.response = mock_response # Ensure response attribute is set
        mock_response.raise_for_status.side_effect = mock_http_error
        mock_response.text = "Internal Server Error Text"


        self.mock_session_request.return_value = mock_response
        
        self.assertFalse(self.client._refresh_token())
        self.assertEqual(self.client._bearer_token, "initial_token") # Should not change

    @patch('builtins.open', new_callable=mock_open, read_data=b"file_content")
    @patch('os.path.basename', return_value="test_file.txt")
    def test_upload_document_success(self, mock_basename, mock_file_open):
        # Mock successful response for upload
        mock_upload_response = Mock()
        mock_upload_response.status_code = 201 # Typically 201 Created
        mock_upload_response.json.return_value = {"id": "doc123_uploaded", "version": "1"}
        
        # Ensure the token is considered valid and doesn't need refresh
        self.client._bearer_token = "valid_token_for_upload"
        self.client._token_renews_at = datetime.now() + timedelta(hours=1)
        
        self.mock_session_request.return_value = mock_upload_response

        doc_id = self.client.upload_document("dummy/path/test_file.txt", "TestItemType", {"custom_attr": "value"})
        
        self.assertEqual(doc_id, "doc123_uploaded")
        # Check that self.mock_session_request was called correctly for the upload
        args, kwargs = self.mock_session_request.call_args
        self.assertEqual(args[0], "POST") # Method
        self.assertTrue(args[1].endswith("/items")) # URL
        self.assertIn("files", kwargs)
        self.assertIn("data", kwargs)
        self.assertIn("attributes", kwargs["data"])
        # Can add more assertions on kwargs['files'] and kwargs['data'] structure
        attributes_json = json.loads(kwargs["data"]["attributes"]) # Ensure metadata is JSON string
        self.assertEqual(attributes_json["itemtype"], "TestItemType")
        self.assertEqual(attributes_json["custom_attr"], "value")


    def test_upload_document_connection_error(self):
        # Ensure the token is considered valid to avoid refresh attempt
        self.client._bearer_token = "valid_token_for_upload"
        self.client._token_renews_at = datetime.now() + timedelta(hours=1)

        # Simulate a connection error during the request for upload
        self.mock_session_request.side_effect = CMConnectionError("Network issue")

        with patch("builtins.open", mock_open(read_data=b"file_content")):
            with patch("os.path.basename", return_value="test_file.txt"):
                # CMClient.upload_document catches CMConnectionError and returns None
                result = self.client.upload_document("dummy/path/test_file.txt", "TestItemType")
                self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
