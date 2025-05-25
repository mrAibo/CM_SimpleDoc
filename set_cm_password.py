#!/usr/bin/env python
import keyring
import getpass
import json
import os
import sys

# Path to the credentials configuration file
DEFAULT_CREDENTIALS_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'config', 'credentials.json'
))

def load_keyring_config(config_path=DEFAULT_CREDENTIALS_PATH):
    """Loads service_name and keyring_username from credentials.json."""
    try:
        with open(config_path, 'r') as f:
            creds_config = json.load(f)
        
        service_name = creds_config.get("service_name")
        keyring_username = creds_config.get("keyring_username")

        if not service_name or not keyring_username:
            print(f"Error: 'service_name' or 'keyring_username' not found in {config_path}", file=sys.stderr)
            return None, None
        return service_name, keyring_username
    except FileNotFoundError:
        print(f"Error: Credentials file not found at {config_path}", file=sys.stderr)
        return None, None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {config_path}", file=sys.stderr)
        return None, None
    except Exception as e:
        print(f"An unexpected error occurred while loading keyring config: {e}", file=sys.stderr)
        return None, None

def main():
    print("CM Password Setup for Keyring")
    print("-----------------------------")
    
    script_dir = os.path.dirname(__file__)
    default_config_path = os.path.join(script_dir, 'config', 'credentials.json')
    
    config_file_path = input(f"Enter path to credentials config file (default: {default_config_path}): ").strip()
    if not config_file_path:
        config_file_path = default_config_path
    
    config_file_path = os.path.abspath(config_file_path)

    if not os.path.exists(config_file_path):
        print(f"Error: Configuration file not found at {config_file_path}", file=sys.stderr)
        sys.exit(1)

    service_name, keyring_username = load_keyring_config(config_file_path)

    if not service_name or not keyring_username:
        sys.exit(1)

    print(f"Service Name: {service_name}")
    print(f"Keyring Username: {keyring_username}")

    try:
        # Check if password already exists
        existing_password = keyring.get_password(service_name, keyring_username)
        if existing_password:
            print("\nWarning: A password already exists for this service and username.")
            overwrite = input("Do you want to overwrite it? (yes/no) [no]: ").strip().lower()
            if overwrite != 'yes':
                print("Password not changed.")
                sys.exit(0)
        
        password = getpass.getpass(f"Enter password for '{keyring_username}' on service '{service_name}': ")
        if not password:
            print("Password cannot be empty. Aborting.")
            sys.exit(1)
            
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("Passwords do not match. Aborting.")
            sys.exit(1)

        keyring.set_password(service_name, keyring_username, password)
        print("\nPassword stored successfully in the system keyring!")
        print("You can verify by trying to retrieve it (e.g., using 'python -m keyring get {} {}')".format(service_name, keyring_username))

    except keyring.errors.NoKeyringError:
        print("\nError: No suitable keyring backend found. Please ensure you have a keyring service (like GNOME Keyring, KWallet, or macOS Keychain) installed and running.", file=sys.stderr)
        print("You might need to install a package like 'gnome-keyring' or 'python3-keyrings-alt'.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
