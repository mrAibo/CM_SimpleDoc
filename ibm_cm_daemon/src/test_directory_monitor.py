import unittest
from unittest.mock import MagicMock, patch, call
import logging
import tempfile
from pathlib import Path
import time # For creating distinct modification times if needed for advanced tests

# Assuming directory_monitor.py is in the same directory or accessible via PYTHONPATH
from directory_monitor import DocEventHandler, DirectoryMonitor
from watchdog.events import FileSystemEvent, FileCreatedEvent, FileModifiedEvent, DirCreatedEvent, DirModifiedEvent


# Suppress logging from the module during most tests to keep test output clean
# You can enable it for specific debugging if needed.
logging.disable(logging.CRITICAL)
# To re-enable for debugging a specific test:
# logging.disable(logging.NOTSET)

class TestDocEventHandler(unittest.TestCase):

    def setUp(self):
        self.mock_processing_callback = MagicMock()
        self.monitored_path = "/test/monitored/path"
        self.handler = DocEventHandler(self.mock_processing_callback, self.monitored_path)

    def test_on_created_file_event(self):
        """Test on_created calls callback for file creation."""
        file_path = Path(self.monitored_path) / "new_file.txt"
        event = FileCreatedEvent(str(file_path))

        self.handler.on_created(event)

        self.mock_processing_callback.assert_called_once_with(str(file_path), 'created', self.monitored_path)

    def test_on_created_directory_event(self):
        """Test on_created does NOT call callback for directory creation."""
        dir_path = Path(self.monitored_path) / "new_subdir"
        event = DirCreatedEvent(str(dir_path)) # is_directory will be True

        self.handler.on_created(event)

        self.mock_processing_callback.assert_not_called()

    def test_on_modified_file_event(self):
        """Test on_modified calls callback for file modification."""
        file_path = Path(self.monitored_path) / "existing_file.txt"
        event = FileModifiedEvent(str(file_path))

        self.handler.on_modified(event)

        self.mock_processing_callback.assert_called_once_with(str(file_path), 'modified', self.monitored_path)

    def test_on_modified_directory_event(self):
        """Test on_modified does NOT call callback for directory modification."""
        dir_path = Path(self.monitored_path) / "existing_subdir"
        event = DirModifiedEvent(str(dir_path)) # is_directory will be True

        self.handler.on_modified(event)

        self.mock_processing_callback.assert_not_called()

    # Example of testing with a temporary file if needed (more integration-like for the handler)
    def test_on_created_with_temp_file(self):
        # This is a slightly more integration-style test for the handler itself.
        # Requires actual file system interaction.
        logging.disable(logging.NOTSET) # Enable logging for this test if you want to see output

        with tempfile.TemporaryDirectory() as tmpdir_path_str:
            monitored_temp_path = Path(tmpdir_path_str)

            callback_mock = MagicMock()
            specific_handler = DocEventHandler(callback_mock, str(monitored_temp_path))

            test_file = monitored_temp_path / "temp_test_file.txt"

            # Simulate event by actually creating the file
            with open(test_file, "w") as f:
                f.write("test")

            # Manually create an event object for it
            event = FileCreatedEvent(str(test_file))
            specific_handler.on_created(event) # Call the handler method

            callback_mock.assert_called_once_with(str(test_file), 'created', str(monitored_temp_path))
        logging.disable(logging.CRITICAL) # Disable logging again


class TestDirectoryMonitor(unittest.TestCase):

    def setUp(self):
        self.mock_processing_callback = MagicMock()
        # Use patch for Observer to prevent actual observer from starting
        self.observer_patcher = patch('directory_monitor.Observer')
        self.MockObserverClass = self.observer_patcher.start()
        self.mock_observer_instance = self.MockObserverClass.return_value # Instance of Observer

        # Mock DocEventHandler to verify its instantiation and usage
        self.doc_event_handler_patcher = patch('directory_monitor.DocEventHandler')
        self.MockDocEventHandlerClass = self.doc_event_handler_patcher.start()
        self.mock_doc_event_handler_instance = self.MockDocEventHandlerClass.return_value

    def tearDown(self):
        self.observer_patcher.stop()
        self.doc_event_handler_patcher.stop()

    def test_init_no_directories(self):
        """Test DirectoryMonitor initializes with no directories to scan."""
        monitor = DirectoryMonitor([], self.mock_processing_callback)
        self.MockObserverClass.assert_called_once() # Observer is always instantiated
        self.mock_observer_instance.schedule.assert_not_called()
        self.assertEqual(len(monitor._event_handlers), 0)

    def test_init_with_valid_directories(self):
        """Test DirectoryMonitor schedules handlers for valid directories."""
        dir_configs = [
            {"path": "/monitored/data1"},
            {"path": "/monitored/data2"}
        ]
        monitor = DirectoryMonitor(dir_configs, self.mock_processing_callback)

        self.MockObserverClass.assert_called_once()

        # Check DocEventHandler instantiation
        expected_doc_event_handler_calls = [
            call(self.mock_processing_callback, "/monitored/data1"),
            call(self.mock_processing_callback, "/monitored/data2")
        ]
        self.MockDocEventHandlerClass.assert_has_calls(expected_doc_event_handler_calls, any_order=False)

        # Check observer.schedule calls
        # Since DocEventHandler instance is mocked, we use the instance for schedule
        expected_schedule_calls = [
            call(self.mock_doc_event_handler_instance, "/monitored/data1", recursive=True),
            call(self.mock_doc_event_handler_instance, "/monitored/data2", recursive=True)
        ]
        # The mock_doc_event_handler_instance will be the same mock object for all calls if not configured otherwise.
        # So, we expect it to be called with this instance.
        self.assertEqual(self.mock_observer_instance.schedule.call_count, 2)
        # self.mock_observer_instance.schedule.assert_has_calls(expected_schedule_calls, any_order=False)
        # The above assert_has_calls is tricky if the instance is always the same mock.
        # Let's check call args one by one if needed or ensure distinct mock instances per call.

        # For simplicity, check args of each call
        args_list = self.mock_observer_instance.schedule.call_args_list
        self.assertEqual(args_list[0][0][1], "/monitored/data1") # path for first call
        self.assertEqual(args_list[0][0][0], self.mock_doc_event_handler_instance) # handler instance
        self.assertEqual(args_list[1][0][1], "/monitored/data2") # path for second call
        self.assertEqual(args_list[1][0][0], self.mock_doc_event_handler_instance)

        self.assertEqual(len(monitor._event_handlers), 2)


    def test_init_skips_missing_path_config(self):
        """Test DirectoryMonitor skips configurations with missing 'path'."""
        dir_configs = [
            {"name": "valid_dir_config_but_no_path_key"}, # Missing 'path'
            {"path": "/monitored/data1"}
        ]
        monitor = DirectoryMonitor(dir_configs, self.mock_processing_callback)

        self.MockDocEventHandlerClass.assert_called_once_with(self.mock_processing_callback, "/monitored/data1")
        self.mock_observer_instance.schedule.assert_called_once_with(
            self.mock_doc_event_handler_instance, "/monitored/data1", recursive=True
        )
        self.assertEqual(len(monitor._event_handlers), 1)

    def test_init_handles_scheduling_exception(self):
        """Test DirectoryMonitor handles exceptions during observer.schedule."""
        dir_configs = [{"path": "/problematic/path"}]
        # Simulate an error during scheduling (e.g., path does not exist for real observer)
        self.mock_observer_instance.schedule.side_effect = Exception("Test scheduling error")

        # Expect this not to raise an unhandled exception due to try-except in DirectoryMonitor
        monitor = DirectoryMonitor(dir_configs, self.mock_processing_callback)

        self.MockDocEventHandlerClass.assert_called_once_with(self.mock_processing_callback, "/problematic/path")
        self.mock_observer_instance.schedule.assert_called_once()
        self.assertEqual(len(monitor._event_handlers), 0) # Handler not added if schedule fails

    def test_start_calls_observer_start(self):
        """Test start method calls observer.start()."""
        dir_configs = [{"path": "/monitored/data1"}]
         # Simulate that schedule was successful, so observer has emitters
        self.mock_observer_instance.emitters = [MagicMock()] # Non-empty list

        monitor = DirectoryMonitor(dir_configs, self.mock_processing_callback)
        monitor.start()

        self.mock_observer_instance.start.assert_called_once()

    def test_start_does_not_call_observer_start_if_no_emitters(self):
        """Test start method does not call observer.start() if no emitters are scheduled."""
        self.mock_observer_instance.emitters = [] # Empty list
        monitor = DirectoryMonitor([], self.mock_processing_callback) # No dirs, so no emitters
        monitor.start()
        self.mock_observer_instance.start.assert_not_called()


    def test_stop_calls_observer_stop_and_join_if_alive(self):
        """Test stop method calls observer.stop() and observer.join() if observer is alive."""
        dir_configs = [{"path": "/monitored/data1"}]
        monitor = DirectoryMonitor(dir_configs, self.mock_processing_callback)

        self.mock_observer_instance.is_alive.return_value = True # Simulate observer is running
        monitor.stop()

        self.mock_observer_instance.stop.assert_called_once()
        self.mock_observer_instance.join.assert_called_once()

    def test_stop_does_not_call_if_not_alive(self):
        """Test stop method does not call stop/join if observer is not alive."""
        dir_configs = [{"path": "/monitored/data1"}]
        monitor = DirectoryMonitor(dir_configs, self.mock_processing_callback)

        self.mock_observer_instance.is_alive.return_value = False # Simulate observer is not running
        monitor.stop()

        self.mock_observer_instance.stop.assert_not_called()
        self.mock_observer_instance.join.assert_not_called()


if __name__ == '__main__':
    # Re-enable logging for direct script execution if needed for debugging
    # logging.disable(logging.NOTSET)
    unittest.main()
