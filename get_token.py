#!/usr/bin/env python
import requests
import json
import os
import re # For token extraction
import keyring
import sys # For stderr

# Script is expected to be in the project root. Config is in ./config/credentials.json
DEFAULT_CREDENTIALS_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'config', 'credentials.json'
))

def load_credentials(credentials_path=DEFAULT_CREDENTIALS_PATH):
    """Loads login credentials from a JSON file and retrieves password from keyring."""
    try:
        with open(credentials_path, 'r') as f:
            loaded_creds = json.load(f)
        # print(f"Credentials JSON part loaded successfully from {credentials_path}") # Less verbose for script use
    except FileNotFoundError:
        print(f"ERROR: Credentials file not found: {credentials_path}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Error decoding JSON from {credentials_path}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while loading credentials JSON from {credentials_path}: {e}", file=sys.stderr)
        return None

    # Check for keys needed for keyring lookup
    keyring_related_keys = ["service_name", "keyring_username", "username"] # username from JSON is used if keyring_username is missing
    if not all(key in loaded_creds for key in keyring_related_keys[:2]): # service_name and keyring_username are essential for keyring
        print(f"ERROR: Credentials file {credentials_path} is missing 'service_name' or 'keyring_username'. Required for keyring lookup.", file=sys.stderr)
        return None
    
    service_name = loaded_creds["service_name"]
    # Use keyring_username if present, otherwise fall back to the main 'username' from JSON for keyring.
    keyring_username_to_use = loaded_creds.get("keyring_username", loaded_creds.get("username"))

    if not keyring_username_to_use: # Ensure we have a username for keyring.
        print(f"ERROR: 'keyring_username' (or fallback 'username') not found in credentials for service '{service_name}'.", file=sys.stderr)
        return None

    print(f"Attempting to retrieve password from keyring for service '{service_name}' and username '{keyring_username_to_use}'...")
    password = keyring.get_password(service_name, keyring_username_to_use)

    if password is None or password == "":
        print(f"ERROR: Password not found in keyring for service '{service_name}' and username '{keyring_username_to_use}'. Please store it first using 'keyring set {service_name} {keyring_username_to_use}'.", file=sys.stderr)
        return None
    
    loaded_creds["password"] = password
    # print("Password successfully retrieved from keyring.") # Less verbose

    # Validate all required keys for the application are now present
    # Note: 'password' is now populated from keyring.
    # 'service_name' and 'keyring_username' were checked before keyring call.
    final_required_keys = ["login_url", "login_host", "username", "password", "servername", "service_name"]
    # keyring_username is optional if username is used as fallback, but its presence was effectively checked.
    
    missing_keys = [key for key in final_required_keys if key not in loaded_creds or not loaded_creds[key]]
    if missing_keys:
        print(f"ERROR: Credentials configuration is missing one or more required values after keyring lookup: {missing_keys}", file=sys.stderr)
        return None
        
    return loaded_creds

def fetch_token():
    """
    Fetches the bearer token from the CM8 server using credentials from config/credentials.json
    and password from the system keyring.
    Prints status code, response text, and the extracted token.
    Returns the token if successful, None otherwise.
    """
    credentials = load_credentials()
    if not credentials:
        # load_credentials already printed specific errors to stderr
        return None

    # All required keys, including 'password', should be present if load_credentials succeeded.
    # The check in load_credentials is now the primary validation point for required fields.
    # No need for another required_keys check here if load_credentials guarantees them.

    login_url_dynamic = credentials["login_url"]
    login_headers_dynamic = {
        "Content-Type": "application/json",
        "Host": credentials["login_host"]
    }
    login_data_dynamic = {
        "username": credentials["username"],
        "password": credentials["password"],
        "servername": credentials["servername"]
    }

    print(f"Attempting to fetch token from: {login_url_dynamic}")
    try:
        response = requests.post(login_url_dynamic, headers=login_headers_dynamic, json=login_data_dynamic, timeout=10)
        
        print(f"Response Status Code: {response.status_code}")
        print("Response Headers:")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")
        print("Response Body (text):")
        print(response.text)

        if response.status_code == 200:
            # The token is directly in the body, prefixed by "Bearer "
            # Example response body: "Bearer eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..."
            response_body = response.text.strip()
            if response_body.startswith("Bearer "):
                token = response_body[len("Bearer "):].strip()
                if token:
                    print(f"Successfully extracted Bearer Token: {token}")
                    return token
                else:
                    print("Error: 'Bearer ' prefix found but token is empty.")
                    return None
            else:
                # Fallback for JSON response, though the primary expectation is plain text "Bearer <token>"
                try:
                    json_response = response.json()
                    if "token" in json_response:
                        token = json_response["token"]
                        print(f"Successfully extracted Bearer Token from JSON response: {token}")
                        return token
                    else:
                        print("Error: Token not found in JSON response. 'token' key missing.")
                        return None
                except json.JSONDecodeError:
                    print("Error: Response body does not start with 'Bearer ' and is not valid JSON.")
                    return None
        else:
            print(f"Error: Failed to fetch token. Status code: {response.status_code}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error: An exception occurred while requesting the token: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

if __name__ == "__main__":
    token = fetch_token()
    if token:
        # In a real scenario, this token would be used by another part of the application.
        # For this script, just printing it is sufficient for verification.
        pass 
    else:
        print("Failed to retrieve token.")
        # Potentially exit with an error code if this script is meant to be called by others
        # import sys
        # sys.exit(1)
