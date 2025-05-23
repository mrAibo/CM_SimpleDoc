#!/usr/bin/env python
import requests
import json
import os
import re # For token extraction

# Script is expected to be in the project root. Config is in ./config/credentials.json
DEFAULT_CREDENTIALS_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'config', 'credentials.json'
))

def load_credentials(credentials_path=DEFAULT_CREDENTIALS_PATH):
    """Loads login credentials from a JSON file."""
    try:
        with open(credentials_path, 'r') as f:
            credentials = json.load(f)
        print(f"Credentials loaded successfully from {credentials_path}")
        return credentials
    except FileNotFoundError:
        print(f"ERROR: Credentials file not found: {credentials_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Error decoding JSON from {credentials_path}: {e}")
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while loading credentials from {credentials_path}: {e}")
        return None

def fetch_token():
    """
    Fetches the bearer token from the CM8 server using credentials from config/credentials.json.
    Prints status code, response text, and the extracted token.
    Returns the token if successful, None otherwise.
    """
    credentials = load_credentials()
    if not credentials:
        return None

    required_keys = ["login_url", "login_host", "username", "password", "servername"]
    if not all(key in credentials for key in required_keys):
        print(f"ERROR: Credentials file is missing one or more required keys: {required_keys}")
        return None

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
