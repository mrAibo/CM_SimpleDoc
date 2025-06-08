import logging
import time # For potential use in start/stop or main loop
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, LoggingEventHandler # LoggingEventHandler is useful for debugging

logger = logging.getLogger(__name__)

class DocEventHandler(FileSystemEventHandler):
    """
    Handles file system events and triggers a processing callback.
    """
    def __init__(self, processing_callback, monitored_path: str):
        super().__init__()
        self.processing_callback = processing_callback
        self.monitored_path = monitored_path # Store path for context if needed
        logger.info(f"DocEventHandler initialized for path: {self.monitored_path}")

    def on_created(self, event):
        super().on_created(event)
        if not event.is_directory:
            logger.info(f"File created: {event.src_path} in {self.monitored_path}")
            # Potentially add more context, like which monitored_path triggered this
            self.processing_callback(event.src_path, 'created', self.monitored_path)

    def on_modified(self, event):
        super().on_modified(event)
        if not event.is_directory:
            # For modified, especially with large files or complex save operations,
            # events might fire multiple times. Some debouncing or delay might be needed
            # in the processing_callback or a queueing mechanism.
            # For now, directly call back.
            logger.info(f"File modified: {event.src_path} in {self.monitored_path}")
            self.processing_callback(event.src_path, 'modified', self.monitored_path)

    def on_moved(self, event):
        super().on_moved(event)
        # A move can be a create at the destination if it's into our watched folder,
        # or a delete if out of it. Or a rename.
        # If a file is renamed within the monitored directory, it's a modify from watchdog's view (src + dest)
        # If moved into the directory, on_created handles it at event.dest_path.
        # If moved out, on_deleted handles event.src_path.
        # If renamed within, on_modified is often triggered for the old path, then on_created for new, or on_moved.
        if not event.is_directory:
            logger.info(f"File moved: from {event.src_path} to {event.dest_path} within {self.monitored_path}")
            # Decide how to handle moves:
            # - If dest_path is what matters (file now exists here):
            # self.processing_callback(event.dest_path, 'created', self.monitored_path)
            # - Or if you need to track the move specifically:
            # self.processing_callback(event.dest_path, 'moved', self.monitored_path, source_path=event.src_path)
            # For simplicity, we'll assume on_created/on_modified will handle the states we care about.
            # If a file is moved into the monitored dir, on_created fires for dest_path.
            # If a file is renamed within the dir, often an on_modified or on_created for the new name.
            # No specific callback for 'moved' for now to avoid duplicate processing if on_created/on_modified cover it.
            pass


class DirectoryMonitor:
    """
    Monitors specified directories for file changes.
    """
    def __init__(self, directories_to_scan_configs, processing_callback):
        """
        Args:
            directories_to_scan_configs (list of dict): A list of directory configurations.
                Each dict should have a "path" key. Example: [{"path": "/path/to/dir1"}, {"path": "/path/to/dir2"}]
            processing_callback: The function to call when files are created/modified.
                                 Expected signature: callback(file_path, event_type, monitored_dir_path)
        """
        self.directories_to_scan_configs = directories_to_scan_configs
        self.processing_callback = processing_callback
        self.observer = Observer()
        self._event_handlers = [] # Keep a reference to handlers

        if not directories_to_scan_configs:
            logger.warning("DirectoryMonitor initialized with no directories to scan.")
            return

        for dir_config in self.directories_to_scan_configs:
            path_to_scan = dir_config.get("path")
            if not path_to_scan:
                logger.warning(f"Missing 'path' in directory configuration: {dir_config}. Skipping.")
                continue

            # Here, we pass the specific path_to_scan to DocEventHandler
            # so it knows its context, which can be useful for the callback.
            event_handler = DocEventHandler(self.processing_callback, path_to_scan)
            try:
                # Ensure directory exists before scheduling, watchdog might not create it.
                # Although for monitoring, it should ideally exist.
                # Path(path_to_scan).mkdir(parents=True, exist_ok=True) # Optional: create if not exists
                # For now, assume directories exist as per typical use case.
                self.observer.schedule(event_handler, path_to_scan, recursive=True)
                self._event_handlers.append(event_handler) # Store handler
                logger.info(f"Scheduled monitoring for directory: {path_to_scan}")
            except Exception as e:
                # This can happen if path does not exist or permissions are wrong
                logger.error(f"Failed to schedule monitoring for directory {path_to_scan}: {e}", exc_info=True)


    def start(self):
        if not self.observer.emitters: # Check if any emitters were scheduled
            logger.warning("DirectoryMonitor has no directories scheduled. Nothing to start.")
            return
        try:
            self.observer.start()
            logger.info("Directory monitoring started.")
        except Exception as e:
            logger.error(f"Failed to start directory monitoring: {e}", exc_info=True)
            # Potentially re-raise or handle as a critical failure
            raise

    def stop(self):
        if not self.observer.is_alive():
            logger.info("Directory monitoring is not running or already stopped.")
            return
        try:
            self.observer.stop()
            logger.info("Directory monitoring stopping...")
            self.observer.join()
            logger.info("Directory monitoring stopped successfully.")
        except Exception as e:
            logger.error(f"Error during directory monitoring stop: {e}", exc_info=True)


if __name__ == '__main__':
    # Example Usage (requires log_setup and config_loader to be available and configured)

    # 1. Setup logging (example - assuming log_setup.py is in the same directory)
    try:
        from log_setup import setup_logging
        # In a real app, these would come from config
        setup_logging("logs/monitor_example.log", "INFO")
    except ImportError:
        print("log_setup not found, using basic logging for example.")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


    # 2. Define a processing callback
    def my_file_processor(file_path, event_type, monitored_dir):
        logger.info(f"Callback: File '{file_path}' event '{event_type}' in monitored dir '{monitored_dir}'. Processing...")
        # Add actual processing logic here (e.g., add to a queue, call CMClient)

    # 3. Configuration (example - normally from settings.json)
    # Ensure these directories exist on your system for the example to work
    # Or use tempfile to create them for a self-contained example
    import tempfile

    temp_dirs_to_monitor_paths = []
    temp_dir_objects = []

    for i in range(2): # Create 2 temp dirs for monitoring
        td = tempfile.TemporaryDirectory(prefix=f"monitored_dir_{i}_")
        temp_dir_objects.append(td)
        temp_dirs_to_monitor_paths.append({"path": td.name})
        logger.info(f"Example: Using temporary directory for monitoring: {td.name}")

    if not temp_dirs_to_monitor_paths:
        logger.error("Example: No temporary directories created. Exiting.")
        exit()

    # 4. Initialize and start the monitor
    monitor = DirectoryMonitor(temp_dirs_to_monitor_paths, my_file_processor)

    try:
        monitor.start()
        logger.info("Example: Monitoring started. Create or modify files in the temp directories to see events.")
        logger.info(f"Monitored directories: {[d.name for d in temp_dir_objects]}")

        # Keep the main thread alive to allow observer to work
        # In a real daemon, this would be the main loop or a service manager
        keep_running = True
        while keep_running:
            try:
                time.sleep(1)
                # Create a dummy file in one of the monitored directories to test
                if temp_dir_objects:
                    test_file_path = Path(temp_dir_objects[0].name) / "test_file.txt"
                    with open(test_file_path, "a") as f:
                        f.write(f"Modified at {time.time()}\n")
                    logger.info(f"Example: Touched {test_file_path}")
                    # os.remove(test_file_path) # Optional: remove to see create events again if script is rerun
                    time.sleep(2) # Give some time for event to be processed

            except KeyboardInterrupt:
                logger.info("Example: Keyboard interrupt received. Stopping monitor.")
                keep_running = False
            except Exception as e:
                logger.error(f"Example: An error occurred in the main loop: {e}", exc_info=True)
                # Decide if this should stop the monitor or try to recover
                # keep_running = False
    finally:
        logger.info("Example: Stopping monitor...")
        monitor.stop()
        logger.info("Example: Cleaning up temporary directories...")
        for td in temp_dir_objects:
            td.cleanup()
        logger.info("Example: Finished.")
