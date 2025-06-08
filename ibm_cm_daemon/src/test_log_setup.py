import unittest
import logging
import os
import tempfile
from pathlib import Path
import shutil # For cleaning up directories

# Assuming log_setup.py is in the same directory or accessible via PYTHONPATH
from log_setup import setup_logging, DEFAULT_LOG_FORMAT

class TestLogSetup(unittest.TestCase):

    def setUp(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir_obj.name)
        self.log_file_path = self.temp_dir_path / "test_app.log"

        # Ensure a clean logging environment for each test
        # Clear handlers from root logger
        root_logger = logging.getLogger()
        if root_logger.hasHandlers():
            for handler in list(root_logger.handlers): # Iterate over a copy
                root_logger.removeHandler(handler)
                handler.close() # Important to close file handlers
        # Reset level if necessary, though setup_logging should handle it
        # root_logger.setLevel(logging.NOTSET)


    def tearDown(self):
        # Clean up: close handlers and remove temporary directory
        root_logger = logging.getLogger()
        if root_logger.hasHandlers():
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                if isinstance(handler, logging.FileHandler): # Make sure it's a file handler
                    handler.close()

        self.temp_dir_obj.cleanup()
        # Just in case cleanup isn't perfect with open files, though it should be.
        if self.temp_dir_path.exists():
            shutil.rmtree(self.temp_dir_path, ignore_errors=True)


    def test_setup_logging_creates_file_handler(self):
        """Test that a FileHandler is added to the root logger."""
        setup_logging(str(self.log_file_path), "INFO")
        root_logger = logging.getLogger()
        self.assertTrue(any(isinstance(h, logging.FileHandler) for h in root_logger.handlers))
        # Check if the log file was created
        self.assertTrue(self.log_file_path.exists())

    def test_setup_logging_creates_log_directory(self):
        """Test that the log directory is created if it doesn't exist."""
        non_existent_subdir = self.temp_dir_path / "new_logs_dir" / "another_level"
        log_file_in_new_dir = non_existent_subdir / "app.log"

        self.assertFalse(non_existent_subdir.exists()) # Ensure it doesn't exist before call

        setup_logging(str(log_file_in_new_dir), "INFO")

        self.assertTrue(non_existent_subdir.exists())
        self.assertTrue(log_file_in_new_dir.exists())

    def test_setup_logging_sets_level(self):
        """Test that the logger level is set correctly."""
        setup_logging(str(self.log_file_path), "DEBUG")
        root_logger = logging.getLogger()
        self.assertEqual(root_logger.getEffectiveLevel(), logging.DEBUG)

        setup_logging(str(self.log_file_path), "WARNING")
        self.assertEqual(root_logger.getEffectiveLevel(), logging.WARNING)

        # Test invalid level defaults to INFO
        setup_logging(str(self.log_file_path), "INVALID_LEVEL_XYZ")
        self.assertEqual(root_logger.getEffectiveLevel(), logging.INFO)


    def test_setup_logging_sets_formatter(self):
        """Test that the formatter is set correctly for the FileHandler."""
        custom_format = "%(levelname)s - %(message)s"
        setup_logging(str(self.log_file_path), "INFO", log_format=custom_format)
        root_logger = logging.getLogger()

        file_handler_found = False
        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                file_handler_found = True
                self.assertIsInstance(handler.formatter, logging.Formatter)
                self.assertEqual(handler.formatter._fmt, custom_format)
                break
        self.assertTrue(file_handler_found, "FileHandler not found on root logger.")

    def test_log_messages_written_to_file(self):
        """Test that log messages are actually written to the log file."""
        setup_logging(str(self.log_file_path), "INFO")

        logger = logging.getLogger("my_test_module") # Get a named logger
        test_message_info = "This is an INFO test message."
        test_message_warning = "This is a WARNING test message."

        logger.info(test_message_info)
        logger.warning(test_message_warning)

        # Critical: Ensure handlers are flushed before reading the file
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            handler.flush()
            if isinstance(handler, logging.FileHandler): # Explicitly close to ensure write through
                 handler.close()
                 root_logger.removeHandler(handler) # Remove to reopen cleanly if needed or avoid issues in tearDown

        self.assertTrue(self.log_file_path.exists())
        with open(self.log_file_path, 'r') as f:
            log_content = f.read()

        self.assertIn(test_message_info, log_content)
        self.assertIn("INFO", log_content) # Check level name
        self.assertIn("my_test_module", log_content) # Check logger name

        self.assertIn(test_message_warning, log_content)
        self.assertIn("WARNING", log_content)

    def test_multiple_calls_to_setup_logging_no_duplicate_handlers(self):
        """Test that multiple calls to setup_logging don't add duplicate handlers."""
        setup_logging(str(self.log_file_path), "INFO")
        initial_handler_count = len(logging.getLogger().handlers)

        # Call setup_logging again with potentially different config
        other_log_file = self.temp_dir_path / "other_log.log"
        setup_logging(str(other_log_file), "DEBUG")

        # The number of handlers should ideally be the same as after the first call (e.g., 1 File, 1 Stream)
        # because setup_logging now clears existing handlers.
        current_handler_count = len(logging.getLogger().handlers)
        self.assertEqual(current_handler_count, initial_handler_count,
                         "Handler count changed unexpectedly after second setup_logging call.")

        # Verify the new configuration is active
        self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.DEBUG)
        self.assertTrue(other_log_file.exists())


if __name__ == '__main__':
    unittest.main()
