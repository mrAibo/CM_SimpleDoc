import unittest
from unittest.mock import MagicMock, patch, call, ANY
import os
import shutil
import tempfile
import logging
from pathlib import Path
import datetime

# Assuming processing_workflow.py and cm_client.py are in the same directory or accessible
from processing_workflow import handle_file_event
from cm_client import CMClient, CMClientException, CMClientAuthenticationError, CMClientNotFoundError, CMClientServerError

# Suppress all logging for cleaner test output, can be enabled for debugging.
# logging.disable(logging.CRITICAL)


class TestProcessingWorkflow(unittest.TestCase):

    def setUp(self):
        self.mock_cm_client = MagicMock(spec=CMClient)

        self.temp_dir_obj = tempfile.TemporaryDirectory(prefix="proc_test_")
        self.temp_dir_path = Path(self.temp_dir_obj.name)

        self.source_file_path = self.temp_dir_path / "source_file.txt"
        with open(self.source_file_path, "w") as f:
            f.write("Test content.")

        self.failed_archive_path = self.temp_dir_path / "failed_archive"
        # This directory will be created by the workflow if needed

        self.global_config = {
            "failed_archive_path": str(self.failed_archive_path)
        }
        self.monitored_dir_config_create = {
            "path": str(self.temp_dir_path), # Path being monitored
            "item_type_name_create": "TestDocItemType",
            "item_type_name_update": "TestDocItemTypeUpdate",
            "cm_template_name": "DefaultTemplate"
        }

        # Patch external modules used by the workflow
        self.mock_shutil_move = patch('processing_workflow.shutil.move').start()
        self.mock_os_path_getsize = patch('processing_workflow.os.path.getsize').start()
        self.mock_os_path_basename = patch('processing_workflow.os.path.basename').start()
        self.mock_os_makedirs = patch('processing_workflow.os.makedirs').start()
        self.mock_mimetypes_guess_type = patch('processing_workflow.mimetypes.guess_type').start()

        # Configure return values for mocks
        self.mock_os_path_basename.return_value = os.path.basename(self.source_file_path)
        self.mock_os_path_getsize.return_value = 123 # Dummy size
        self.mock_mimetypes_guess_type.return_value = ("text/plain", None)

        # Patching logger within the module to check log calls
        self.logger_patch = patch('processing_workflow.logging.getLogger')
        self.mock_get_logger = self.logger_patch.start()
        self.mock_logger = MagicMock()
        self.mock_get_logger.return_value = self.mock_logger

        # Ensure file exists for most tests
        if not self.source_file_path.exists():
            self.source_file_path.write_text("Test content for setup.")


    def tearDown(self):
        patch.stopall() # Stops all patchers started with patch().start()
        self.temp_dir_obj.cleanup()
        # Ensure logging is re-enabled if it was disabled for a specific test
        # logging.disable(logging.NOTSET)

    def test_handle_created_event_success(self):
        """Test successful processing of a 'created' event."""
        self.mock_cm_client.create_document.return_value = {"pid": "new_pid_123"}

        handle_file_event(
            str(self.source_file_path),
            'created',
            self.monitored_dir_config_create,
            self.mock_cm_client,
            self.global_config
        )

        self.mock_cm_client.create_document.assert_called_once()
        args, _ = self.mock_cm_client.create_document.call_args
        self.assertEqual(args[0], "TestDocItemType") # item_type_name
        # Further checks on attributes, parts_metadata, file_streams can be added here
        # For example, check if 'SOURCEFILENAME' is in attributes (args[1])
        self.assertTrue(any(attr['name'] == 'SOURCEFILENAME' and attr['value'] == os.path.basename(self.source_file_path) for attr in args[1]))

        self.mock_logger.info.assert_any_call(f"Successfully created document for '{self.source_file_path}'. PID: new_pid_123")
        self.mock_shutil_move.assert_not_called() # File should not be moved on success

    def test_handle_created_event_missing_item_type_config(self):
        """Test 'created' event when item_type_name_create is missing."""
        invalid_dir_config = self.monitored_dir_config_create.copy()
        del invalid_dir_config['item_type_name_create']

        handle_file_event(str(self.source_file_path), 'created', invalid_dir_config, self.mock_cm_client, self.global_config)

        self.mock_cm_client.create_document.assert_not_called()
        self.mock_logger.error.assert_any_call(
            f"Configuration for monitored directory '{str(self.temp_dir_path)}' "
            f"is missing 'item_type_name_create'. Cannot process '{self.source_file_path}'."
        )
        self.mock_shutil_move.assert_called_once() # File should be moved
        self.mock_os_makedirs.assert_called_with(str(self.failed_archive_path), exist_ok=True)


    def test_handle_created_event_create_document_fails_cm_error(self):
        """Test 'created' event when cm_client.create_document raises a CMClientException."""
        self.mock_cm_client.create_document.side_effect = CMClientServerError("Server is down", 500)

        handle_file_event(
            str(self.source_file_path),
            'created',
            self.monitored_dir_config_create,
            self.mock_cm_client,
            self.global_config
        )

        self.mock_logger.error.assert_any_call(
            f"CM Client error while processing '{self.source_file_path}' for item type 'TestDocItemType'. Error: Server is down",
            exc_info=True
        )
        self.mock_shutil_move.assert_called_once()
        self.mock_os_makedirs.assert_called_with(str(self.failed_archive_path), exist_ok=True)


    def test_handle_created_event_create_document_fails_auth_error(self):
        """Test 'created' event with CMClientAuthenticationError."""
        self.mock_cm_client.create_document.side_effect = CMClientAuthenticationError("Auth failed", 401)

        handle_file_event(str(self.source_file_path), 'created', self.monitored_dir_config_create, self.mock_cm_client, self.global_config)

        self.mock_logger.error.assert_any_call(
            f"Authentication error while processing '{self.source_file_path}' for item type 'TestDocItemType'. Error: Auth failed",
            exc_info=True
        )
        self.mock_shutil_move.assert_called_once()


    def test_handle_created_event_general_exception(self):
        """Test 'created' event with an unexpected general exception during CM call."""
        self.mock_cm_client.create_document.side_effect = Exception("Something broke badly")

        handle_file_event(str(self.source_file_path), 'created', self.monitored_dir_config_create, self.mock_cm_client, self.global_config)

        self.mock_logger.error.assert_any_call(
            f"Unexpected error while processing '{self.source_file_path}' for item type 'TestDocItemType'. Error: Something broke badly",
            exc_info=True
        )
        self.mock_shutil_move.assert_called_once()

    def test_failed_archive_path_creation_and_timestamped_filename(self):
        """Test that failed_archive_path is created and filename is timestamped."""
        self.mock_cm_client.create_document.side_effect = Exception("Simulated failure")

        # Ensure failed_archive_path does not exist to test os.makedirs
        if self.failed_archive_path.exists():
            shutil.rmtree(self.failed_archive_path)
        self.mock_os_makedirs.reset_mock() # Reset from potential previous calls in other tests

        handle_file_event(
            str(self.source_file_path),
            'created',
            self.monitored_dir_config_create,
            self.mock_cm_client,
            self.global_config
        )

        self.mock_os_makedirs.assert_called_once_with(str(self.failed_archive_path), exist_ok=True)
        self.mock_shutil_move.assert_called_once()

        # Check the destination path for the timestamp pattern
        args, _ = self.mock_shutil_move.call_args
        destination_path = Path(args[1])
        self.assertEqual(destination_path.parent, self.failed_archive_path)
        # Example: 20231027123456123456_source_file.txt
        self.assertTrue(destination_path.name.endswith(f"_{os.path.basename(self.source_file_path)}"))
        self.assertTrue(len(destination_path.name) > len(os.path.basename(self.source_file_path)) + 1 + 20) # Timestamp length check


    def test_handle_created_event_file_not_found_during_processing(self):
        """Test 'created' event if file is gone before open()."""
        # Simulate file disappearing after event, before open()
        # For this, we need to make open() raise FileNotFoundError
        # We can patch the `open` builtin for the scope of this test
        with patch('processing_workflow.open', side_effect=FileNotFoundError("File vanished!")) as mock_open:
            handle_file_event(
                str(self.source_file_path),
                'created',
                self.monitored_dir_config_create,
                self.mock_cm_client,
                self.global_config
            )
            mock_open.assert_called_once_with(str(self.source_file_path), 'rb')
            self.mock_logger.error.assert_any_call(
                f"File not found during processing (possibly moved or deleted externally): {self.source_file_path}",
                exc_info=True
            )
            self.mock_shutil_move.assert_not_called() # Cannot move a non-existent file


    def test_handle_modified_event_placeholder_logging(self):
        """Test 'modified' event logs placeholder message and gets item_type_name_update."""
        handle_file_event(str(self.source_file_path), 'modified', self.monitored_dir_config_create, self.mock_cm_client, self.global_config)

        self.mock_logger.info.assert_any_call(
            f"Received 'modified' event for file: {self.source_file_path}. Full update logic is pending."
        )
        # Check if it tried to get item_type_name_update (which is 'TestDocItemTypeUpdate')
        # This implies it looked at monitored_dir_config['item_type_name_update']
        # No direct call to assert this, but absence of error related to it is a partial check.
        # If we had update logic, we'd mock cm_client.update_item_attributes.
        self.mock_cm_client.update_item_attributes.assert_not_called() # As it's placeholder

    def test_handle_modified_event_missing_item_type_update_config(self):
        """Test 'modified' event when item_type_name_update is missing."""
        invalid_dir_config = self.monitored_dir_config_create.copy()
        del invalid_dir_config['item_type_name_update']

        handle_file_event(str(self.source_file_path), 'modified', invalid_dir_config, self.mock_cm_client, self.global_config)

        self.mock_logger.warning.assert_any_call(
            f"Configuration for monitored directory '{str(self.temp_dir_path)}' "
            f"is missing 'item_type_name_update'. Cannot process modification for '{self.source_file_path}'."
        )
        self.mock_shutil_move.assert_not_called() # Not moving for modify config errors currently


    def test_handle_unhandled_event_type(self):
        """Test that an unhandled event type is logged."""
        handle_file_event(str(self.source_file_path), 'deleted', self.monitored_dir_config_create, self.mock_cm_client, self.global_config)
        self.mock_logger.warning.assert_any_call(
            f"Received unhandled event type 'deleted' for file: {self.source_file_path}"
        )

    def test_missing_failed_archive_path_in_global_config(self):
        """Test behavior when failed_archive_path is missing from global_config."""
        current_global_config = {} # Missing 'failed_archive_path'
        self.mock_cm_client.create_document.side_effect = Exception("Simulated failure")

        handle_file_event(
            str(self.source_file_path),
            'created',
            self.monitored_dir_config_create,
            self.mock_cm_client,
            current_global_config # Pass the config without failed_archive_path
        )

        self.mock_logger.error.assert_any_call(
            "Configuration missing 'failed_archive_path'. Cannot proceed with error handling for file movements."
        )
        # Crucially, shutil.move should not be called if failed_archive_path is not set
        self.mock_shutil_move.assert_not_called()


if __name__ == '__main__':
    logging.disable(logging.NOTSET) # Enable logging for direct script execution if needed
    unittest.main()
