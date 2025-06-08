import json

def load_config(config_path):
    """
    Loads a JSON configuration file.

    Args:
        config_path (str): The path to the JSON configuration file.

    Returns:
        dict: A dictionary representing the configuration.
              Returns None if the file is not found or if the JSON is invalid.
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print(f"Error: Configuration file not found at '{config_path}'")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in configuration file at '{config_path}'")
        return None

if __name__ == '__main__':
    # Example usage (optional)
    config = load_config('../config/settings.json')
    if config:
        print("Configuration loaded successfully:")
        print(config)
    else:
        print("Failed to load configuration.")
