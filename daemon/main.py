import json
import logging
import os

# Determine the absolute path to the config file relative to this script
# __file__ is the path to the current script (daemon/main.py)
# os.path.dirname(__file__) is the directory of the current script (daemon/)
# os.path.join(os.path.dirname(__file__), '..', 'config', 'config.json') navigates
# up one level from 'daemon/' to the project root, then into 'config/config.json'
DEFAULT_CONFIG_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'config', 'config.json'
))

def load_config(config_path=DEFAULT_CONFIG_PATH):
    """Loads the configuration from a JSON file."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logging.info(f"Configuration loaded successfully from {config_path}")
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found: {config_path}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from {config_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred while loading config from {config_path}: {e}")
        return None

def setup_logging(logging_config):
    """Configures logging based on the provided configuration."""
    try:
        log_file_path = logging_config.get("log_file_path")
        log_level_str = logging_config.get("log_level", "INFO").upper()
        
        if not log_file_path:
            # This print will go to console if called before logging is fully set up.
            print("ERROR: 'log_file_path' not found in logging configuration (setup_logging).")
            return False

        # Ensure the log directory exists
        log_dir = os.path.dirname(log_file_path)
        if log_dir: # Create directory only if log_file_path includes a directory
             os.makedirs(log_dir, exist_ok=True)

        log_level = getattr(logging, log_level_str, logging.INFO)
        
        # Get the root logger
        logger = logging.getLogger()
        logger.setLevel(log_level) # Set level on the root logger
        
        # Remove any existing handlers to avoid duplicate logs
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close() # Close handler before removing

        # Create file handler
        file_handler = logging.FileHandler(log_file_path, mode='a')
        # No need to setLevel on handler if root logger's level is set, 
        # but can be done for more granular control if needed.
        # file_handler.setLevel(log_level) 
        
        # Create formatter and add it to the handler
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        
        # Add the handler to the logger
        logger.addHandler(file_handler)
        
        # Test log message to confirm file logging is working
        logging.info(f"Logging configured. Level: {log_level_str}, File: {log_file_path}")
        return True
    except Exception as e:
        # Use basic print here as logging might not be set up
        print(f"ERROR: Failed to configure logging (setup_logging): {e}")
        return False

if __name__ == "__main__":
    # No initial basicConfig here. load_config will use root logger which has no handlers yet,
    # so its messages won't appear on console unless setup_logging fails and adds a console handler.
    # Or, if load_config itself fails catastrophically before logging can be set up.

    config = load_config()

    if config:
        # Check for 'logging' key and that it's a dictionary.
        # Also check for 'log_file_path' as it's essential.
        if 'logging' in config and \
           isinstance(config['logging'], dict) and \
           'log_file_path' in config['logging']:
            if setup_logging(config['logging']):
                logging.info(f"Daemon starting up with configuration: {config}")
                # Placeholder for daemon's main loop or further initialization
                logging.info("Daemon initialized. Placeholder for main logic.")
            else:
                # setup_logging failed, it should have printed an error.
                # Configure basic console logging for any subsequent errors.
                print("ERROR: Logging setup failed. Daemon continues with basic console logging for errors.")
                logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")
                logging.error("Logging setup failed after attempting to configure from file.")
        else:
            # Logging configuration is missing or incomplete.
            print("ERROR: Logging configuration ('logging' section or 'log_file_path') is missing or invalid in config.json. Daemon continues with basic console logging for errors.")
            logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")
            logging.error("Logging configuration is missing or invalid in config.json.")
    else:
        # config is None, meaning load_config() failed.
        # load_config() should have logged/printed an error.
        # Configure basic console logging for this critical failure message.
        print("ERROR: Failed to load configuration. Daemon cannot start.")
        logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s")
        logging.error("Failed to load configuration. Daemon cannot start.")

    # Example: Accessing other parts of the config
    # if config and 'daemon_settings' in config:
    #     logging.info(f"Daemon settings: {config['daemon_settings']}")
