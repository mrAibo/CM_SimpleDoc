import logging
import os
from pathlib import Path

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def setup_logging(log_file_path_str: str, log_level_str: str, log_format: str = None):
    """
    Configures logging for the application.

    Args:
        log_file_path_str (str): The path to the log file.
        log_level_str (str): The desired logging level (e.g., "INFO", "DEBUG").
        log_format (str, optional): The log message format. Defaults to DEFAULT_LOG_FORMAT.
    """
    if not log_format:
        log_format = DEFAULT_LOG_FORMAT

    logger = logging.getLogger() # Get the root logger

    # Set level
    level = getattr(logging, log_level_str.upper(), logging.INFO)
    logger.setLevel(level)

    # Clear existing handlers from the root logger to avoid duplicate logs
    # and to ensure old file handlers are closed if re-configuring.
    if logger.hasHandlers():
        for handler in list(logger.handlers):  # Iterate over a copy
            logger.removeHandler(handler)
            if hasattr(handler, 'close'):
                try:
                    handler.close()
                except Exception:
                    # Ignore errors during close, not much can be done here
                    pass

    # File Handler
    try:
        log_file_path = Path(log_file_path_str)
        log_file_path.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        file_handler = logging.FileHandler(log_file_path)
    except Exception as e:
        # Fallback to logging to console if file handler fails (e.g. permission denied)
        # This is more for robustness during initial setup or unexpected issues.
        # In a daemon, if logging to file is critical, this might need different handling.
        print(f"Warning: Could not create file handler for {log_file_path_str}. Error: {e}. Logging to console.")
        stream_handler = logging.StreamHandler()
        formatter = logging.Formatter(log_format)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
        return

    formatter = logging.Formatter(log_format)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Optional: Console handler for easier debugging (especially if not run as a strict daemon)
    # For now, let's add it by default but make its level potentially higher than file log.
    # Or, it could be controlled by a separate flag/env var.
    # For this task, let's add a console logger that also respects the passed log_level_str
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter) # Use the same formatter
    # console_handler.setLevel(level) # Respect the same level for console
    logger.addHandler(console_handler)


if __name__ == '__main__':
    # Example Usage:
    # This part would typically be in your main application script.

    # 1. Load configuration (example)
    # from config_loader import load_config
    # config = load_config('../config/settings.json') # Adjust path as needed

    # if config and 'logging' in config:
    #     log_settings = config['logging']
    #     log_file = log_settings.get('log_file_path', 'logs/app.log') # Default if not in config
    #     log_level = log_settings.get('level', 'INFO') # Default if not in config

    #     # Ensure log_file path is relative to some base or absolute
    #     # For this example, assume it's relative to the script's parent's parent if logs/app.log
    #     if log_file.startswith('logs/'):
    #         # This is a placeholder for actual path resolution needed in a real app
    #         # In a real app, config paths might be relative to a project root.
    #         example_base_dir = Path(__file__).parent.parent
    #         log_file = example_base_dir / log_file
    #     else:
    #         log_file = Path(log_file) # If it's specific like /var/log/app.log

    #     print(f"Setting up logging. File: {log_file}, Level: {log_level}")
    #     setup_logging(str(log_file), log_level)
    # else:
    #     print("Logging configuration not found or failed to load. Using defaults.")
    #     # Fallback to basic logging setup
    #     default_log_path = Path(__file__).parent.parent / "logs" / "default_app.log"
    #     setup_logging(str(default_log_path), "INFO")

    # Test logging after setup (example)
    # logger_instance = logging.getLogger(__name__) # Get a logger for the current module
    # logger_instance.debug("This is a debug message.")
    # logger_instance.info("This is an info message.")
    # logger_instance.warning("This is a warning message.")
    # logger_instance.error("This is an error message.")
    # logger_instance.critical("This is a critical message.")

    # print(f"Check log file at specified path (e.g., {log_file or default_log_path})")
    print("log_setup.py executed. Example usage is commented out.")
    print("To test, you would typically import and call setup_logging from your main application entry point.")
