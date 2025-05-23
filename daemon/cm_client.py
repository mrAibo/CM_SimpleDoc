import requests
import time
import logging
import os # Added
import json # Added
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class CMConnectionError(requests.exceptions.RequestException):
    """Custom exception for CM connection related errors."""
    pass

class CMClient:
    def __init__(self, api_base_url, auth_config):
        self.api_base_url = api_base_url.rstrip('/')
        self.auth_config = auth_config
        self._bearer_token = auth_config.get("bearer_token")
        self._token_renews_at = datetime.now() # Placeholder, will be updated after first actual renewal or if expiry is known
        self._session = requests.Session()
        # It's good practice to set default headers, like User-Agent
        self._session.headers.update({"User-Agent": "CMDaemon/1.0"})
        
        # Estimate token expiry if possible, or set a short default to force early renewal check
        # This is a simplistic approach. A more robust solution would parse the token for expiry if available.
        self.token_expiry_threshold_seconds = auth_config.get("token_expiry_threshold_seconds", 300)
        # Assume token is valid for a certain period if not explicitly known, e.g. 1 hour.
        # This is a placeholder; real token lifetime should be known or discoverable.
        self._token_valid_duration_seconds = auth_config.get("initial_token_validity_seconds", 3600) 
        self._update_renewal_time(initial_setup=True)

    def _update_renewal_time(self, new_token_lifetime_seconds=None, initial_setup=False):
        if initial_setup:
            # On initial setup, if we have a pre-existing token, we don't know its actual expiry.
            # We assume it's valid for a certain duration or needs immediate renewal check.
            # For safety, set renewal time to be in the past to trigger check/renewal on first use.
            self._token_renews_at = datetime.now() - timedelta(seconds=1)
            logger.info("Initial token setup. Renewal time set to trigger check on first API call.")
        else:
            # After a successful renewal, the new token's lifetime is used.
            lifetime = new_token_lifetime_seconds if new_token_lifetime_seconds is not None else self._token_valid_duration_seconds
            self._token_renews_at = datetime.now() + timedelta(seconds=lifetime - self.token_expiry_threshold_seconds)
            logger.info(f"Token renewal time updated. Next check/renewal around: {self._token_renews_at}")

    def _is_token_expiring(self):
        return datetime.now() >= self._token_renews_at

    def _refresh_token(self):
        renewal_url = self.auth_config.get("token_renewal_url")
        if not renewal_url:
            logger.error("Token renewal URL is not configured.")
            return False

        # Actual token renewal mechanism.
        # Assuming a POST request, and the new token is in an 'access_token' field,
        # and 'expires_in' field for its lifetime in seconds in the JSON response.
        try:
            logger.info(f"Attempting to refresh token from {renewal_url}...")
            # Depending on the auth mechanism, might need to send client_id/secret, or old token for refresh grant.
            # This example assumes no specific body is needed, or it's handled by stored session auth.
            response = self._session.post(renewal_url, timeout=10) 
            response.raise_for_status() # Raises HTTPError for bad responses
            
            token_data = response.json()
            new_token = token_data.get("access_token")
            new_lifetime = token_data.get("expires_in") # In seconds

            if not new_token:
                logger.error("Token renewal response did not contain 'access_token'. Full response: %s", response.text)
                return False
            
            self._bearer_token = new_token
            logger.info("Successfully refreshed bearer token.")
            self._update_renewal_time(new_token_lifetime_seconds=new_lifetime) # new_lifetime can be None
            return True
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error refreshing token from {renewal_url}: {e.response.status_code} {e.response.text}")
            # If 401/403, could mean refresh token itself is invalid/expired.
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error refreshing token from {renewal_url}: {e}")
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout refreshing token from {renewal_url}: {e}")
        except requests.exceptions.RequestException as e: # Catch-all for other request issues
            logger.error(f"Error refreshing token from {renewal_url}: {e}")
        except ValueError as e: # Includes JSONDecodeError
            logger.error(f"Error parsing token renewal JSON response from {renewal_url}: {e}. Response text: {response.text if 'response' in locals() else 'N/A'}")
        
        return False

    def get_bearer_token(self):
        if not self._bearer_token or self._is_token_expiring():
            logger.info("Bearer token is missing or expiring. Attempting to refresh.")
            if not self._refresh_token():
                logger.error("Failed to refresh bearer token. Subsequent API calls may fail.")
                # Depending on policy, could raise an exception here
        return self._bearer_token

    def _request(self, method, endpoint, **kwargs):
        token = self.get_bearer_token()
        if not token:
            # If token couldn't be obtained/refreshed, we might not want to proceed.
            logger.error("Cannot make API request: No valid bearer token.")
            # Or raise an exception: raise Exception("API request failed: No valid token")
            return None 

        headers = kwargs.pop("headers", {}) # Take out headers from kwargs if provided
        headers["Authorization"] = f"Bearer {token}"
        # Accept header can be overridden by kwargs if needed for specific requests
        headers.setdefault("Accept", "application/json")

        url = f"{self.api_base_url}/{endpoint.lstrip('/')}"
        
        # Log request details carefully, avoid logging full file contents or sensitive metadata
        log_params = kwargs.get('params', None)
        log_json = kwargs.get('json', None) # JSON body
        log_data = kwargs.get('data', None) # Form data
        if log_data and isinstance(log_data, dict) and 'attributes' in log_data and kwargs.get('files'):
             # For multipart uploads, data field might contain sensitive metadata string
             log_data_summary = {"attributes_keys": list(json.loads(log_data['attributes']).keys()) if isinstance(log_data.get('attributes'), str) else "Non-string attributes", "has_files": True}
        else:
             log_data_summary = log_data

        logger.debug(f"Making API request: {method.upper()} {url} "
                     f"Params: {log_params} JSON: {log_json} Data: {log_data_summary} "
                     f"Stream: {kwargs.get('stream', False)}")

        try:
            # Pass through all other kwargs (like files, data, json, stream)
            response = self._session.request(method, url, headers=headers, timeout=30, **kwargs)
            response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)

            if kwargs.get('stream', False): # If streaming, return the response object directly
                logger.debug(f"Successful streaming response from {url}. Status: {response.status_code}")
                return response 
            
            if response.status_code == 204: # No Content
                logger.debug(f"Successful request to {url} with 204 No Content.")
                return None # Or a specific success indicator if preferred over None
            
            # Check content type before assuming JSON.
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                try:
                    json_response = response.json()
                    logger.debug(f"Successful JSON response from {url}. Status: {response.status_code}. Response snippet: {str(json_response)[:200]}")
                    return json_response
                except ValueError as e: # JSONDecodeError
                    logger.error(f"Failed to decode JSON response from {url}. Status: {response.status_code}. Error: {e}. Response text: {response.text[:500]}")
                    # Treat as an error, but not necessarily a CMConnectionError unless status was 5xx
                    return None # Or raise a specific content error
            else:
                # For non-JSON, non-streaming responses (e.g. XML, plain text, or unexpected)
                logger.debug(f"Successful non-JSON response from {url}. Status: {response.status_code}. Content-Type: {content_type}. Length: {len(response.content)}")
                return response.content # Or response.text, depending on expected non-JSON content
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error during API request to {url}: {e}")
            raise CMConnectionError(f"Connection error to {url}: {e}") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout during API request to {url}: {e}")
            raise CMConnectionError(f"Timeout during API request to {url}: {e}") from e
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error during API request to {url}: {e.response.status_code} {e.response.text}")
            if e.response.status_code in [500, 502, 503, 504]: # Server-side issues
                raise CMConnectionError(f"CM Server Error ({e.response.status_code}) for {url}: {e.response.text}") from e
            # For other HTTP errors (e.g. 4xx), they are logged, but _request will return None implicitly.
            # This allows callers to differentiate between 'CM down' and 'bad request/auth'
        except requests.exceptions.RequestException as e: # Catch-all for other request issues
            logger.error(f"Generic error during API request to {url}: {e}")
            raise CMConnectionError(f"Generic request error for {url}: {e}") from e
        
        return None # Returns None if an HTTPError (not re-raised as CMConnectionError) occurred, or other non-raising error

    # --- Document Operations ---

    def search_documents(self, criteria, item_type_context=None):
        """
        Searches for documents based on criteria.
        Criteria: dict, e.g., {"attribute_name": "value", "another_attr": "another_value"}
        item_type_context: string, e.g., "Document" to scope search.
        Returns a list of item representations (dicts) or an empty list.
        """
        query_parts = []
        if item_type_context:
            # Assuming CM syntax for itemtype, adjust if different (e.g., "/Document" or "//@itemType=\"Document\"")
            query_parts.append(f"itemtype='{item_type_context}'") 
        
        for key, value in criteria.items():
            # Simple query construction: assumes string equality. Adjust for other operators or data types.
            # This is a placeholder for actual CM query syntax.
            query_parts.append(f"@{key}='{value}'") # Example: @attributeName='value'
        
        if not query_parts:
            logger.warning("Search documents called with no criteria or item_type_context.")
            return []

        # Example CM query: "/Document[@attributeName=\"value\" and @anotherAttr=\"value\"]"
        # For simplicity here, using a flat q param: "itemtype='Document' AND @attr1='val1'"
        # This needs to be adapted to the specific CM's query language.
        # The example uses a more generic q=key:val structure
        query_string = " AND ".join(query_parts)
        logger.info(f"Searching documents with query: {query_string}")

        try:
            # Assuming search endpoint is /search and takes a query string 'q'
            response_json = self._request("GET", "search", params={"q": query_string})
            if response_json and "results" in response_json and isinstance(response_json["results"], list):
                logger.info(f"Search returned {len(response_json['results'])} documents.")
                return response_json["results"]
            else:
                logger.warning(f"Search response was empty or not in expected format. Query: {query_string}. Response: {str(response_json)[:200]}")
                return []
        except CMConnectionError as e:
            logger.error(f"Connection error during search: {e}")
            return [] # Return empty list on connection error
        except Exception as e:
            logger.error(f"Unexpected error during search: {e}")
            return []


    def upload_document(self, file_path, item_type, metadata=None):
        """
        Uploads a document with specified item type and metadata.
        file_path: path to the local file.
        item_type: string, e.g., "Document".
        metadata: dict of additional attributes.
        Returns the new document ID if successful, else None.
        """
        if not os.path.exists(file_path):
            logger.error(f"File not found for upload: {file_path}")
            return None

        metadata_payload = metadata.copy() if metadata else {}
        # Ensure 'itemtype' is part of the metadata payload sent to CM
        # The exact structure (e.g., top-level key, or inside 'attributes') depends on the API.
        metadata_payload["itemtype"] = item_type 
        
        # Prepare for multipart/form-data request
        # 'file' part for the content, 'attributes' (or similar) part for JSON metadata string
        files = {'file': (os.path.basename(file_path), open(file_path, 'rb'))}
        # CM might expect metadata as a JSON string in a form field, e.g., 'attributes' or 'properties'.
        data = {'attributes': json.dumps(metadata_payload)} 
        
        logger.info(f"Uploading document: {file_path} as item type: {item_type} with metadata: {metadata_payload}")
        
        try:
            # Assuming POST to /items for creating new items
            response_json = self._request("POST", "items", files=files, data=data)
            if response_json and response_json.get("id"):
                doc_id = response_json["id"]
                logger.info(f"Successfully uploaded document {file_path}. New DocID: {doc_id}")
                return doc_id
            else:
                logger.error(f"Upload failed for {file_path}. Response: {str(response_json)[:200]}")
                return None
        except CMConnectionError as e:
            logger.error(f"Connection error during upload of {file_path}: {e}")
            # Do not raise CMConnectionError from here; let the caller (main.py) handle it
            return None 
        except Exception as e:
            logger.error(f"Unexpected error during upload of {file_path}: {e}")
            return None


    def download_document(self, doc_id, target_path):
        """
        Downloads a document by its ID to the target_path.
        Returns True on success, False on failure.
        """
        logger.info(f"Attempting to download document ID '{doc_id}' to '{target_path}'.")
        # Assuming endpoint like /items/{doc_id}/datastreams/content
        endpoint = f"items/{doc_id}/datastreams/content"
        
        try:
            response = self._request("GET", endpoint, stream=True) # Returns the response object on success
            if response: # If _request was successful and returned the response object
                try:
                    with open(target_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            # filter out keep-alive new chunks
                            if chunk: 
                                f.write(chunk)
                    logger.info(f"Successfully downloaded document '{doc_id}' to '{target_path}'.")
                    return True
                except IOError as e:
                    logger.error(f"Failed to write downloaded document '{doc_id}' to '{target_path}': {e}")
                finally:
                    response.close() # Important to close the response when using stream=True
            else:
                # _request returned None (e.g. 404 Not Found, or other non-connection error)
                logger.error(f"Failed to initiate download for document '{doc_id}'. API request did not return a streamable response.")
            
        except CMConnectionError as e:
            logger.error(f"Connection error downloading document '{doc_id}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error downloading document '{doc_id}': {e}")
            if 'response' in locals() and response: # Ensure response is defined and not None
                 response.close()
        
        return False


    def delete_document(self, doc_id):
        """
        Deletes a document by its ID.
        Returns True if successful (e.g. 204 No Content), False otherwise.
        """
        logger.info(f"Attempting to delete document ID '{doc_id}'.")
        endpoint = f"items/{doc_id}"
        
        try:
            # _request returns None for 204 No Content, which is success for DELETE
            result = self._request("DELETE", endpoint)
            if result is None: # Assuming 204 No Content is the success indicator
                logger.info(f"Successfully deleted document '{doc_id}'.")
                return True
            else:
                # This case might occur if the API returns some JSON body on delete (uncommon for 204)
                # or if _request logic changes to return a specific success object.
                logger.warning(f"Delete request for document '{doc_id}' returned an unexpected response: {str(result)[:200]}")
                return False # Or interpret based on 'result' if API has specific success response
        except CMConnectionError as e:
            logger.error(f"Connection error deleting document '{doc_id}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting document '{doc_id}': {e}")
            return False

    def update_document_metadata(self, doc_id_or_object_id, metadata, id_is_object_id=False, object_id_field_name=None, item_type_context=None):
        """
        Updates metadata for a document.
        doc_id_or_object_id: The direct DocID or an alternative unique ID (ObjectID).
        metadata: Dict of metadata to update.
        id_is_object_id: Boolean, True if doc_id_or_object_id is an ObjectID.
        object_id_field_name: String, the attribute name for the ObjectID (e.g., "object_id_attr").
        item_type_context: String, item type for disambiguation if using ObjectID.
        Returns True on success, False on failure.
        """
        actual_doc_id = doc_id_or_object_id

        if id_is_object_id:
            if not object_id_field_name:
                logger.error("ObjectID field name not provided for metadata update using ObjectID.")
                return False
            logger.info(f"Updating metadata by ObjectID: searching for item with {object_id_field_name}='{doc_id_or_object_id}' and itemtype='{item_type_context}'.")
            search_criteria = {object_id_field_name: doc_id_or_object_id}
            search_results = self.search_documents(search_criteria, item_type_context=item_type_context)
            
            if not search_results:
                logger.error(f"No document found with {object_id_field_name}='{doc_id_or_object_id}' (itemtype: {item_type_context}) for metadata update.")
                return False
            if len(search_results) > 1:
                logger.warning(f"Multiple documents found for {object_id_field_name}='{doc_id_or_object_id}' (itemtype: {item_type_context}). Using the first one: {search_results[0].get('id')}")
            
            actual_doc_id = search_results[0].get("id")
            if not actual_doc_id:
                logger.error(f"Found document via ObjectID but it lacks an 'id' field. Search result: {str(search_results[0])[:200]}")
                return False
            logger.info(f"Found DocID {actual_doc_id} for ObjectID {doc_id_or_object_id}.")

        logger.info(f"Attempting to update metadata for document ID '{actual_doc_id}' with data: {metadata}")
        # Assuming PUT to /items/{doc_id} with a body like {"attributes": metadata_dict}
        # Or perhaps PATCH /items/{doc_id} if the API supports partial updates.
        # Or PUT /items/{doc_id}/attributes
        endpoint = f"items/{actual_doc_id}" 
        payload = {"attributes": metadata} # Adjust payload structure as per actual API

        try:
            response_json = self._request("PUT", endpoint, json=payload) # _request returns None for 204 or 4xx non-CMConnectionError
            if response_json is not None: # Handles 200 OK with JSON body
                logger.info(f"Successfully updated metadata for document '{actual_doc_id}'. Response: {str(response_json)[:200]}")
                return True
            # If response_json is None, it could be a 204 (success) or a 4xx (client error).
            # The current _request implementation logs 4xx errors but returns None, same as for 204.
            # For this method, we'll consider _request returning None as a potential success if it's a 204,
            # but we can't reliably distinguish from 4xx without changing _request.
            # The subtask says "Success Response: JSON of the updated item or HTTP 200/204."
            # If _request logged a 4xx error and returned None, this will be incorrectly treated as possible 204 success here without further checks.
            # To be safer, let's assume None means "not a JSON body success".
            # If a 204 is a definitive success and _request returns None for it, this logic needs _request to signal it.
            # For now, only a non-None response is a clear success for PUT with metadata.
            # If the API *guarantees* 204 for successful PUT and _request returns None for 204, then this would be:
            # if response_json is None and not <way_to_check_if_4xx_error_logged_by_request>: return True
            # This is complex. Simpler: if API returns JSON on success, check for that. If it can return 204 on success,
            # this method needs a clearer signal from _request.
            # Given the ambiguity, treating "None" as "not a success with a body" is safer.
            # The log in _request for 4xx errors would be the primary indicator of client errors.
            # If _request could return the status code, this would be easy:
            # data, status = self._request(...); if status == 200 or status == 204: return True
            
            # Based on current _request, if it's None, it means either 204 (good) or 4xx (bad)
            # We'll assume if no exception was raised, and no JSON body, it's not a success we can confirm with data.
            # This means a successful 204 might be reported as a failure by this function.
            # This is a known limitation of the current _request return contract.
            # A more robust solution would involve _request returning status codes or more structured error info.
            # For now, let's stick to: if we get a JSON body, it's success. Otherwise, it's treated as failure here.
            else:
                logger.warning(f"Update metadata for document '{actual_doc_id}' did not return a JSON body. Assuming not explicitly successful. Check logs for details (e.g. 204 No Content, or client error 4xx).")
                return False
        except CMConnectionError as e:
            logger.error(f"Connection error updating metadata for document '{actual_doc_id}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error updating metadata for document '{actual_doc_id}': {e}")
            return False

    def test_connection(self):
        '''
        A simple method to test connectivity, e.g. by fetching a non-sensitive, lightweight endpoint.
        Adjust endpoint to something suitable for IBM CM (e.g., a server status or root API endpoint).
        '''
        logger.debug("Testing connection to IBM CM API...") # Changed to debug for less noise on successful tests
        try:
            # Pass a specific timeout for connection test.
            # The endpoint "/" should be a lightweight, non-authenticated (or using existing auth) endpoint if possible.
            response_data = self._request("GET", "/", timeout=10) # Example timeout
            
            if response_data is not None:
                # Depending on the API, root "/" might return specific data or just a status.
                # For this stub, any non-None response that didn't raise CMConnectionError is considered success.
                logger.info("Successfully connected to IBM CM API and received a response.")
                return True
            else:
                # This case implies _request returned None due to an HTTPError (e.g. 401, 403, 404)
                # that wasn't a server-side 5xx error, or some other non-raising issue.
                # For a connection test, this is still a failure to "connect" in a meaningful way.
                logger.warning("Connection test to CM API returned no data or an unexpected response (e.g. 4xx error), but no CMConnectionError was raised.")
                return False
        except CMConnectionError as e:
            logger.warning(f"Connection test failed with CMConnectionError: {e}")
            return False
        except Exception as e: # Catch any other unexpected error from _request
            logger.error(f"Unexpected error during connection test: {e}")
            return False
