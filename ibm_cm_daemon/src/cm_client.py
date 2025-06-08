import requests
import json

class CMClientException(Exception):
    """Base exception for CMClient errors."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code

class CMClientAuthenticationError(CMClientException):
    """Raised for authentication failures (401, 403)."""
    pass

class CMClientNotFoundError(CMClientException):
    """Raised when a resource is not found (404)."""
    pass

class CMClientServerError(CMClientException):
    """Raised for server-side errors (5xx)."""
    pass


class CMClient:
    def __init__(self, api_config):
        """
        Initializes the CMClient.
        Args:
            api_config (dict): A dictionary containing API configuration:
                               - endpoint (str): The base API endpoint.
                               - servername (str): The CM server name.
                               - username (str): The username for authentication.
                               - password (str): The password for authentication.
        """
        if not all(key in api_config for key in ['endpoint', 'servername', 'username', 'password']):
            raise ValueError("api_config must contain 'endpoint', 'servername', 'username', and 'password'.")

        self.api_config = api_config
        self.token = None
        self.login_url = self.api_config['endpoint'].strip('/') + "/login"

    def _make_request(self, method, url, headers=None, json_data=None, data=None, files=None):
        """
        Makes an HTTP request.
        Args:
            method (str): HTTP method (GET, POST, PUT, DELETE).
            url (str): The URL for the request.
            headers (dict, optional): Additional headers.
            json_data (dict, optional): JSON payload for the request.
            data (dict, optional): Form data payload.
            files (dict, optional): Files for multipart upload.
        Returns:
            requests.Response: The response object.
        Raises:
            CMClientAuthenticationError: For 401 or 403 errors.
            CMClientNotFoundError: For 404 errors.
            CMClientServerError: For 5xx errors.
            CMClientException: For other request-related errors or unexpected status codes.
        """
        if headers is None:
            headers = {}

        # Auto-login if no token and not already trying to login
        if not self.token and url != self.login_url:
            # print(f"No token found for URL {url}, attempting login...") # Debugging
            self.login() # This will raise an exception if login fails

        if self.token and url != self.login_url: # Check token again, login() might have set it
            headers['Authorization'] = f"Bearer {self.token}"

        headers.setdefault('Accept', 'application/json')
        if json_data and 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json_data,
                data=data,
                files=files,
                timeout=30 # Default timeout
            )

            if 200 <= response.status_code < 300:
                return response
            elif response.status_code in (401, 403):
                if url != self.login_url: # If not a login attempt that failed
                    self.token = None # Clear token on auth error
                raise CMClientAuthenticationError(f"Authentication error: {response.status_code} - {response.text}", response.status_code)
            elif response.status_code == 404:
                raise CMClientNotFoundError(f"Resource not found: {response.status_code} - {response.text}", response.status_code)
            elif response.status_code >= 500:
                raise CMClientServerError(f"Server error: {response.status_code} - {response.text}", response.status_code)
            else:
                # Handle other client errors or unexpected statuses
                raise CMClientException(f"Unexpected HTTP status code: {response.status_code} - {response.text}", response.status_code)

        except requests.exceptions.Timeout:
            raise CMClientException(f"Request timed out: {method} {url}")
        except requests.exceptions.ConnectionError:
            raise CMClientException(f"Connection error: {method} {url}")
        except requests.exceptions.RequestException as e:
            raise CMClientException(f"Request failed: {method} {url} - {e}")

    def login(self):
        """
        Logs into the CM server and stores the session token.
        Returns:
            bool: True if login was successful, False otherwise.
        Raises:
            CMClientException or subclasses for request errors.
        """
        payload = {
            "servername": self.api_config['servername'],
            "username": self.api_config['username'],
            "password": self.api_config['password']
        }

        try:
            response = self._make_request("POST", self.login_url, json_data=payload)
            # Assuming the token is in the JSON response body, e.g., {"token": "actual_token_value"}
            # Adjust based on actual API response structure
            response_json = response.json()
            if 'token' in response_json:
                self.token = response_json['token']
                return True
            else:
                # If token is not in the expected place, even with a 2xx response
                raise CMClientException("Login successful but token not found in response.")
        except CMClientException as e:
            self.token = None # Ensure token is cleared on any login failure
            # Re-raise the caught exception to propagate the error details
            raise e
        return False # Should not be reached if exceptions are raised correctly

    def ping(self):
        """
        Pings the CM server to check connectivity.
        Returns:
            bool: True if the server responds successfully, False otherwise.
        Raises:
            CMClientException or subclasses for request errors if critical.
        """
        ping_url = self.api_config['endpoint'].strip('/') + "/ping"
        ping_url = self.api_config['endpoint'].strip('/') + "/ping"
        # Let _make_request handle exceptions. If it succeeds, status_code will be 2xx.
        response = self._make_request("GET", ping_url)
        # Consider a successful ping if status_code is 200 and no exceptions were raised.
        return response.status_code == 200

    def get_item_type_details(self, item_type_name: str) -> dict:
        """
        Retrieves details for a specific item type, including attributes.
        Args:
            item_type_name (str): The symbolic name of the item type.
        Returns:
            dict: Parsed JSON response containing item type details.
        Raises:
            CMClientException or subclasses for request errors.
        """
        url = f"{self.api_config['endpoint'].strip('/')}/itemtypes/{item_type_name}?include=attributes"
        response = self._make_request("GET", url)
        return response.json()

    def create_document(self, item_type_name: str, attributes: list, parts_metadata: dict, file_streams: list) -> dict:
        """
        Creates a new document item in CM.
        Args:
            item_type_name (str): The symbolic name of the item type for the new document.
            attributes (list): A list of attribute dictionaries, e.g.,
                               [{"name": "AttributeName1", "value": "Value1"}, ...].
            parts_metadata (dict): A dictionary describing the content parts, which will be sent as a JSON string
                                   for the 'parts' form field. e.g.,
                                   {"template": "ICMDRPROXY", "parts": [{"label": "part1", "mimetype": "application/pdf"}]}
            file_streams (list): A list of tuples for file parts. Each tuple should be in the format:
                                 ('form_field_name', ('filename.ext', file_object, 'mimetype')).
                                 Example: [('contentParts1', ('mydoc.pdf', open('mydoc.pdf', 'rb'), 'application/pdf'))]
        Returns:
            dict: Parsed JSON response, typically containing the PID of the created item.
        Raises:
            CMClientException or subclasses for request errors.
        """
        url = f"{self.api_config['endpoint'].strip('/')}/itemtypes/{item_type_name}/items"

        # The 'requests' library expects 'files' to be a list of tuples or a dictionary.
        # For multipart/form-data with JSON parts and file parts:
        # - JSON parts are passed as (name, (None, json_string, 'application/json'))
        # - File parts are passed as (name, (filename, file_object, mimetype))

        multipart_payload = [
            ('attributes', (None, json.dumps(attributes), 'application/json')),
            ('parts', (None, json.dumps(parts_metadata), 'application/json'))
        ]

        # Add file streams to the payload
        # Example: file_streams = [('contentParts1', ('report.pdf', BytesIO(b"pdf content"), 'application/pdf'))]
        if file_streams:
            for fs_item in file_streams:
                multipart_payload.append(fs_item)

        # _make_request will handle headers like Authorization.
        # For multipart/form-data, 'requests' sets Content-Type automatically when 'files' is used.
        # We should not set json_data or data if files is used for multipart.
        response = self._make_request("POST", url, files=multipart_payload)
        return response.json()

    def update_item_attributes(self, pid: str, attributes: list, new_version: bool = False, checkin: str = 'implicit') -> dict:
        """
        Updates attributes of an existing item.
        Args:
            pid (str): The Persistent Identifier (PID) of the item to update.
            attributes (list): A list of attribute dictionaries for update, e.g.,
                               [{"name": "AttributeName1", "value": "NewValue1"}, ...].
            new_version (bool): If True, creates a new version of the item. Defaults to False.
            checkin (str): Check-in mode. Can be 'implicit', 'explicit', or 'always'. Defaults to 'implicit'.
        Returns:
            dict: Parsed JSON response from the server.
        Raises:
            CMClientException or subclasses for request errors.
        """
        url = f"{self.api_config['endpoint'].strip('/')}/items/{pid}"
        params = {
            "newVersion": str(new_version).lower(), # API expects 'true' or 'false'
            "checkin": checkin
        }

        # Add params to URL
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        full_url = f"{url}?{query_string}"

        response = self._make_request("PATCH", full_url, json_data=attributes)
        return response.json()

if __name__ == '__main__':
    # Example Usage (requires a running CM mock server or actual server)
    print("This is a client library, typically not run directly.")
    print("See unit tests for usage examples with mocks, or use in your application.")
    # Example:
    # try:
    #     config = {"endpoint": "http://localhost:8080/cm8rest/v1",
    #               "servername": "myserver", "username": "user", "password": "password"}
    #     client = CMClient(api_config=config)
    #     if client.login():
    #         print(f"Login successful. Token: {client.token}")
    #         if client.ping():
    #             print("Ping successful.")
    #         else:
    #             print("Ping failed.")
    #     else:
    #         print("Login failed.")
    # except CMClientException as e:
    #     print(f"An error occurred: {e}")
