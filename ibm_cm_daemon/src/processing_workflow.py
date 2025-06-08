import os
import shutil
import logging
import datetime
import mimetypes # For guessing mimetype

# Assuming cm_client and its exceptions are in src directory and accessible
from cm_client import CMClient, CMClientException, CMClientAuthenticationError, CMClientNotFoundError, CMClientServerError

# Initialize mimetypes database
mimetypes.init()

def handle_file_event(file_path: str, event_type: str, monitored_dir_config: dict, cm_client: CMClient, config: dict):
    """
    Handles a file event (creation or modification) by processing the file
    and interacting with the CM system.

    Args:
        file_path (str): Absolute path to the detected file.
        event_type (str): 'created' or 'modified'.
        monitored_dir_config (dict): The configuration for the monitored directory
                                     where the event occurred.
        cm_client (CMClient): An initialized instance of CMClient.
        config (dict): The global application configuration.
    """
    logger = logging.getLogger(__name__)
    base_file_name = os.path.basename(file_path)

    # Ensure failed_archive_path is available from global config
    failed_archive_base_path = config.get('failed_archive_path')
    if not failed_archive_base_path:
        logger.error("Configuration missing 'failed_archive_path'. Cannot proceed with error handling for file movements.")
        # Depending on desired strictness, could return or raise an error here.
        # For now, we'll log and proceed, but file moving on error will fail.
        # return # Or raise ConfigurationError("Missing 'failed_archive_path'")

    def _move_to_failed_archive(current_path, reason_prefix=""):
        if not failed_archive_base_path:
            logger.error(f"Cannot move {current_path} to failed archive: 'failed_archive_path' not configured.")
            return

        try:
            # Ensure the base failed_archive_path directory exists
            os.makedirs(failed_archive_base_path, exist_ok=True)

            # Add a timestamp to the archived filename to prevent overwrites
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            archive_filename = f"{timestamp}_{base_file_name}"
            failed_archive_filepath = os.path.join(failed_archive_base_path, archive_filename)

            shutil.move(current_path, failed_archive_filepath)
            logger.info(f"{reason_prefix}Moved '{current_path}' to failed archive: '{failed_archive_filepath}'")
        except Exception as e_move:
            logger.error(f"Critical error: Failed to move '{current_path}' to failed archive path '{failed_archive_base_path}'. Error: {e_move}", exc_info=True)


    if event_type == 'created':
        logger.info(f"Processing new file (created): {file_path}")
        item_type_name = monitored_dir_config.get('item_type_name_create')
        if not item_type_name:
            logger.error(f"Configuration for monitored directory '{monitored_dir_config.get('path')}' "
                         f"is missing 'item_type_name_create'. Cannot process '{file_path}'.")
            _move_to_failed_archive(file_path, "Config error: ")
            return

        try:
            # --- Metadata Preparation (Simplified) ---
            logger.debug(f"Fetching item type details for: {item_type_name}")
            # item_type_attrs_details = cm_client.get_item_type_details(item_type_name) # Not strictly needed for basic attributes
            # logger.debug(f"Item type details for {item_type_name}: {item_type_attrs_details}")

            # Construct basic attributes list
            attributes = [{'name': 'SOURCEFILENAME', 'value': base_file_name}]
            # Example: Add more attributes based on item_type_attrs_details if needed
            # for attr_def in item_type_attrs_details.get('attributes', []):
            #     if attr_def.get('name') == 'Title' and not any(a['name'] == 'Title' for a in attributes):
            #         attributes.append({'name': 'Title', 'value': base_file_name}) # Default title

            # --- Content Preparation ---
            file_size = os.path.getsize(file_path)
            guessed_mimetype, _ = mimetypes.guess_type(file_path)
            mimetype = guessed_mimetype if guessed_mimetype else 'application/octet-stream'

            parts_metadata = {
                "template": monitored_dir_config.get("cm_template_name", "ICMDRPROXY"), # Default template
                "parts": [{
                    "label": base_file_name, # Or a more generic label like "PRIMARYDOCUMENT"
                    "mimetype": mimetype,
                    # "partType": "ICMBASE", # partType is often determined by template or server
                    "size": file_size,
                    "originalFileName": base_file_name
                }]
            }

            logger.debug(f"Prepared parts metadata: {parts_metadata}")

            with open(file_path, 'rb') as f:
                # The 'name' in the tuple for file_streams is the form field name for that part.
                # It should match what the API expects, e.g., 'contentParts1', 'contentParts2', etc.
                # If 'parts_metadata' describes one part, then 'contentParts1' is typical.
                file_streams = [('contentParts1', (base_file_name, f, mimetype))]

                logger.info(f"Attempting to create document in CM for: {file_path} with item type: {item_type_name}")
                created_item_info = cm_client.create_document(item_type_name, attributes, parts_metadata, file_streams)

                pid = created_item_info.get('pid', 'Unknown PID')
                logger.info(f"Successfully created document for '{file_path}'. PID: {pid}")

                # Optional: Delete local file if upload is successful
                try:
                    # os.remove(file_path)
                    # logger.info(f"Successfully removed local file: {file_path} after CM ingestion.")
                    pass # Placeholder for now - make this configurable
                except OSError as e_remove:
                    logger.warning(f"Failed to remove local file {file_path} after successful CM ingestion: {e_remove}", exc_info=True)

        except CMClientAuthenticationError as e_auth:
            logger.error(f"Authentication error while processing '{file_path}' for item type '{item_type_name}'. Error: {e_auth}", exc_info=True)
            # Token might be invalid, CMClient's auto-login should handle re-login if possible.
            # If it still fails, it's a persistent auth issue.
            _move_to_failed_archive(file_path, "Auth error: ")
        except (CMClientNotFoundError, CMClientServerError, CMClientException) as e_cm:
            logger.error(f"CM Client error while processing '{file_path}' for item type '{item_type_name}'. Error: {e_cm}", exc_info=True)
            _move_to_failed_archive(file_path, "CM Client error: ")
        except FileNotFoundError:
            logger.error(f"File not found during processing (possibly moved or deleted externally): {file_path}", exc_info=True)
            # No file to move to failed_archive if it's already gone.
        except Exception as e_general:
            logger.error(f"Unexpected error while processing '{file_path}' for item type '{item_type_name}'. Error: {e_general}", exc_info=True)
            if os.path.exists(file_path): # Check if file still exists before moving
                 _move_to_failed_archive(file_path, "Unexpected error: ")


    elif event_type == 'modified':
        logger.info(f"Received 'modified' event for file: {file_path}. Full update logic is pending.")
        item_type_name_update = monitored_dir_config.get('item_type_name_update')
        if not item_type_name_update:
            logger.warning(f"Configuration for monitored directory '{monitored_dir_config.get('path')}' "
                           f"is missing 'item_type_name_update'. Cannot process modification for '{file_path}'.")
            # Not moving to failed_archive for modify events yet unless clearly defined.
            return

        # Placeholder logic for 'modified'
        # Determining the PID of the existing document based on file_path is a complex
        # problem that usually requires an external mapping database or querying CM
        # with some unique attribute derived from file_path or its content.

        # Example: if a PID could be determined:
        # pid_to_update = "SOME_DETERMINED_PID"
        # if pid_to_update:
        #     try:
        #         attributes_to_update = [
        #             {'name': 'LAST_MODIFIED_LOCALLY', 'value': datetime.datetime.now().isoformat()},
        #             {'name': 'MODIFICATION_TRIGGER_FILE', 'value': base_file_name}
        #         ]
        #         logger.info(f"Attempting to update attributes for PID '{pid_to_update}' due to modification of '{file_path}'.")
        #         cm_client.update_item_attributes(pid_to_update, attributes_to_update, new_version=True) # Example: create new version
        #         logger.info(f"Successfully updated attributes for PID '{pid_to_update}'.")
        #         # What to do with the local file after update? Re-upload content? Delete?
        #     except Exception as e:
        #         logger.error(f"Failed to update attributes for PID '{pid_to_update}'. Error: {e}", exc_info=True)
        # else:
        # logger.warning(f"Cannot process 'modified' event for '{file_path}': PID determination logic not implemented.")
        pass # End of placeholder 'modified' logic

    else:
        logger.warning(f"Received unhandled event type '{event_type}' for file: {file_path}")


if __name__ == '__main__':
    # This section is for example usage and basic manual testing.
    # It requires setting up a mock CMClient, config, etc.

    # Setup basic logging for example
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger_main = logging.getLogger(__name__)

    # --- Mock objects and Config for example ---
    class MockCMClient:
        def __init__(self):
            self.token = "mock_token" # Simulate logged-in state for get_item_type_details

        def get_item_type_details(self, item_type_name):
            logger_main.info(f"[MockCMClient] get_item_type_details called for {item_type_name}")
            if item_type_name == "TestDocCreate":
                return {"name": item_type_name, "attributes": [{"name": "SOURCEFILENAME"}, {"name": "Title"}]}
            raise CMClientNotFoundError(f"Item type {item_type_name} not found.", 404)

        def create_document(self, item_type_name, attributes, parts_metadata, file_streams):
            logger_main.info(f"[MockCMClient] create_document called for {item_type_name}")
            logger_main.info(f"  Attributes: {attributes}")
            logger_main.info(f"  Parts Metadata: {parts_metadata}")
            # Simulate consuming file streams
            for _, (fname, fobj, _) in file_streams:
                fobj.read() # Read the content
                logger_main.info(f"  Processed file stream for: {fname}")

            if item_type_name == "TestDocCreate":
                return {"pid": "mock_pid_12345", "status": "created"}
            elif item_type_name == "TestDocFail":
                raise CMClientServerError("Failed to create document due to server error", 500)
            return {}

        def update_item_attributes(self, pid, attributes, new_version=False, checkin='implicit'):
            logger_main.info(f"[MockCMClient] update_item_attributes called for PID {pid}")
            logger_main.info(f"  Attributes: {attributes}, newVersion: {new_version}, checkin: {checkin}")
            return {"pid": pid, "status": "updated"}

    mock_client = MockCMClient()

    # Create temporary directories for testing
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="processtest_")
    temp_monitored_dir = Path(temp_dir_obj.name) / "source_docs"
    temp_failed_archive_dir = Path(temp_dir_obj.name) / "failed_archive"

    os.makedirs(temp_monitored_dir, exist_ok=True)
    # temp_failed_archive_dir is created by the handler if needed

    global_config = {
        "failed_archive_path": str(temp_failed_archive_dir),
        # other global settings...
    }

    dir_scan_config_create = {
        "path": str(temp_monitored_dir), # This is the path being monitored
        "item_type_name_create": "TestDocCreate",
        "item_type_name_update": "TestDocUpdate", # For modified events
        "cm_template_name": "MyDefaultTemplate"
    }
    dir_scan_config_create_fail = {
        "path": str(temp_monitored_dir),
        "item_type_name_create": "TestDocFail", # Will cause CMClient error
    }
    dir_scan_config_no_item_type = {
        "path": str(temp_monitored_dir),
        # Missing item_type_name_create
    }

    # --- Example: Test 'created' event ---
    logger_main.info("\n--- Testing CREATED event (success case) ---")
    test_file_name = "example_doc.txt"
    test_file_path = temp_monitored_dir / test_file_name
    with open(test_file_path, "w") as f:
        f.write("This is a test document for 'created' event.")

    handle_file_event(str(test_file_path), 'created', dir_scan_config_create, mock_client, global_config)
    if test_file_path.exists(): # Should be removed if successful and uncommented
        logger_main.info(f"File {test_file_path} still exists (as expected if removal is off).")
    if not (temp_failed_archive_dir / f"{os.path.basename(test_file_path)}").exists(): # Name will have timestamp
        logger_main.info(f"File {test_file_path} was not moved to failed archive (as expected).")

    # --- Example: Test 'created' event with CMClient error ---
    logger_main.info("\n--- Testing CREATED event (CMClient create_document error) ---")
    test_file_fail_name = "example_doc_fail.txt"
    test_file_fail_path = temp_monitored_dir / test_file_fail_name
    with open(test_file_fail_path, "w") as f:
        f.write("This document will cause a CMClient error.")

    handle_file_event(str(test_file_fail_path), 'created', dir_scan_config_create_fail, mock_client, global_config)
    if not test_file_fail_path.exists():
        logger_main.info(f"File {test_file_fail_path} was moved (as expected).")
        # Check if it's in failed_archive (name will be timestamped)
        archived_files = list(temp_failed_archive_dir.glob(f"*_{test_file_fail_name}"))
        if archived_files:
            logger_main.info(f"File {test_file_fail_path} was moved to {archived_files[0]} (as expected).")
        else:
            logger_main.error(f"File {test_file_fail_path} was expected in failed_archive but not found.")


    # --- Example: Test 'created' event with missing item_type_name_create config ---
    logger_main.info("\n--- Testing CREATED event (config error: missing item_type_name_create) ---")
    test_file_config_error_name = "example_doc_config_error.txt"
    test_file_config_error_path = temp_monitored_dir / test_file_config_error_name
    with open(test_file_config_error_path, "w") as f:
        f.write("This document has a config error (missing item_type_name_create).")

    handle_file_event(str(test_file_config_error_path), 'created', dir_scan_config_no_item_type, mock_client, global_config)
    if not test_file_config_error_path.exists():
        logger_main.info(f"File {test_file_config_error_path} was moved (as expected due to config error).")
        archived_files_cfg = list(temp_failed_archive_dir.glob(f"*_{test_file_config_error_name}"))
        if archived_files_cfg:
            logger_main.info(f"File {test_file_config_error_path} was moved to {archived_files_cfg[0]} (as expected).")
        else:
            logger_main.error(f"File {test_file_config_error_path} was expected in failed_archive but not found.")


    # --- Example: Test 'modified' event (placeholder) ---
    logger_main.info("\n--- Testing MODIFIED event (placeholder) ---")
    test_file_modified_name = "example_doc_modified.txt"
    test_file_modified_path = temp_monitored_dir / test_file_modified_name
    with open(test_file_modified_path, "w") as f:
        f.write("This is for 'modified' event.")

    handle_file_event(str(test_file_modified_path), 'modified', dir_scan_config_create, mock_client, global_config)
    # Add assertions based on expected placeholder behavior if any (e.g., logging)

    # Cleanup
    logger_main.info("\n--- Example run finished. Cleaning up temp directory. ---")
    try:
        temp_dir_obj.cleanup()
        logger_main.info(f"Temporary directory {temp_dir_obj.name} cleaned up.")
    except Exception as e:
        logger_main.error(f"Error cleaning up temp directory: {e}")

    logger_main.info("To see detailed logs, check console output if basicConfig was used, or configured log file.")
