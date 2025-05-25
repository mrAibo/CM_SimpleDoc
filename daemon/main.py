import json
import logging
import logging.handlers # Added
import os
import time
import shutil
import fnmatch
from .cm_client import CMClient, CMConnectionError
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global flag to indicate CM connection status
daemon_paused_due_to_cm_outage = False

# Determine the absolute path to the config file relative to this script
# __file__ is the path to the current script (daemon/main.py)
# os.path.dirname(__file__) is the directory of the current script (daemon/)
# os.path.join(os.path.dirname(__file__), '..', 'config', 'config.json') navigates
# up one level from 'daemon/' to the project root, then into 'config/config.json'
DEFAULT_CONFIG_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'config', 'config.json'
))

def move_to_failed_archive(file_path, failed_archive_root_dir, reason_subdir=None):
    if not os.path.exists(file_path):
        logging.warning(f"File {file_path} not found, cannot move to failed archive.")
        return

    if not failed_archive_root_dir:
        logging.error(f"Failed archive directory not configured. Cannot move {file_path}.")
        return

    target_dir = failed_archive_root_dir
    if reason_subdir:
        target_dir = os.path.join(failed_archive_root_dir, reason_subdir)

    try:
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
            logging.info(f"Created failed archive subdirectory: {target_dir}")
    except OSError as e:
        logging.error(f"Could not create failed archive directory {target_dir}: {e}. File {file_path} will not be moved.")
        return

    base_filename = os.path.basename(file_path)
    destination_path = os.path.join(target_dir, base_filename)

    # Handle potential naming conflicts by appending a timestamp
    if os.path.exists(destination_path):
        name, ext = os.path.splitext(base_filename)
        timestamp = time.strftime("%Y%m%d%H%M%S")
        destination_path = os.path.join(target_dir, f"{name}_{timestamp}{ext}")
        # If it STILL exists (highly unlikely for timestamped), log and skip or add counter
        if os.path.exists(destination_path):
            logging.warning(f"Timestamped file {destination_path} already exists in failed archive. Skipping move for {file_path}")
            return

    try:
        shutil.move(file_path, destination_path)
        logging.info(f"Moved file {file_path} to failed archive: {destination_path}")
    except (OSError, shutil.Error) as e:
        logging.error(f"Failed to move {file_path} to {destination_path}: {e}")

# Helper function for process_download_job_file
def _process_single_download(item_to_download, target_dir_base, job_name_for_logging, cm_client):
    doc_id = item_to_download.get("doc_id")
    target_filename = item_to_download.get("target_filename", doc_id) 
    
    if not doc_id:
        logging.warning(f"Download item in job '{job_name_for_logging}' missing 'doc_id'. Item: {item_to_download}")
        return {"status": "skipped_no_docid", "doc_id": None, "target_path": None, "item_data": item_to_download}
    if not target_filename: 
        logging.warning(f"Download item for DocID {doc_id} in job '{job_name_for_logging}' missing 'target_filename' and doc_id fallback failed.")
        return {"status": "skipped_no_filename", "doc_id": doc_id, "target_path": None, "item_data": item_to_download}

    full_target_path = os.path.join(target_dir_base, target_filename)
    
    result_payload = {"doc_id": doc_id, "target_path": full_target_path, "status": "pending_thread", "item_data": item_to_download}

    if os.path.exists(full_target_path):
        logging.warning(f"Target file {full_target_path} already exists. Skipping download for DocID {doc_id} in job '{job_name_for_logging}'.")
        result_payload["status"] = "skipped_exists"
        return result_payload
        
    logging.info(f"Thread: Attempting to download DocID {doc_id} to {full_target_path} for job '{job_name_for_logging}'.")
    try:
        if not cm_client:
            logging.error(f"CMClient not available (thread). Cannot download DocID {doc_id}.")
            result_payload["status"] = "failed_no_client"
            return result_payload

        if cm_client.download_document(doc_id, full_target_path):
            logging.info(f"Thread: Successfully downloaded DocID {doc_id} to {full_target_path}.")
            result_payload["status"] = "success"
        else:
            logging.warning(f"Thread: Download failed for DocID {doc_id} (CM operation returned False) to {full_target_path}.")
            result_payload["status"] = "failed_cm_operation"
        return result_payload
    except CMConnectionError:
        raise 
    except Exception as e: 
        logging.error(f"Thread: Unexpected error downloading DocID {doc_id} to {full_target_path}: {e}", exc_info=True)
        result_payload["status"] = "failed_unexpected_thread"
        result_payload["error_message"] = str(e)
        return result_payload

def process_download_job_file(job_file_path, cm_client, global_config, failed_archive_dir): # failed_archive_dir not directly used by this function
    logger.info(f"Processing download job file: {job_file_path}")
    try:
        with open(job_file_path, 'r') as f:
            job_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Download job file not found: {job_file_path}")
        return {"status": "error", "message": "Job file not found", "summary": {"successful_downloads": 0, "failed_downloads": 0, "skipped_downloads": 0}}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from job file {job_file_path}: {e}")
        return {"status": "error", "message": f"JSON decode error: {e}", "summary": {"successful_downloads": 0, "failed_downloads": 0, "skipped_downloads": 0}}

    job_name = job_data.get("job_name", os.path.basename(job_file_path))
    logger.info(f"Starting download job: {job_name}")

    target_dir_base = job_data.get("default_target_directory")
    if not target_dir_base:
        target_dir_base = global_config.get("download_settings", {}).get("default_target_directory")
    
    if not target_dir_base:
        logger.error(f"No target directory specified in job '{job_name}' or global config. Skipping job.")
        return {"status": "error", "message": "Target directory not configured", "summary": {"successful_downloads": 0, "failed_downloads": 0, "skipped_downloads": 0}}

    try:
        if not os.path.exists(target_dir_base):
            os.makedirs(target_dir_base, exist_ok=True)
            logger.info(f"Created target directory for job '{job_name}': {target_dir_base}")
    except OSError as e:
        logger.error(f"Could not create target directory {target_dir_base} for job '{job_name}': {e}")
        return {"status": "error", "message": f"Failed to create target directory: {e}", "summary": {"successful_downloads": 0, "failed_downloads": 0, "skipped_downloads": 0}}

    summary = {"successful_downloads": 0, "failed_downloads": 0, "skipped_downloads": 0}
    global daemon_paused_due_to_cm_outage # Ensure global flag is accessible

    items_to_download = job_data.get("downloads", [])
    if not items_to_download:
        logger.info(f"No items to download in job '{job_name}'.")
        return {"status": "success_empty_job", "message": "No items in job file.", "summary": summary}

    max_downloads = global_config.get("performance", {}).get("max_parallel_downloads", 1) 
    if not isinstance(max_downloads, int) or max_downloads <= 0:
        logging.warning(f"Invalid max_parallel_downloads value ({max_downloads}), defaulting to 1.")
        max_downloads = 1
    
    logging.info(f"Processing {len(items_to_download)} download items for job '{job_name}' using up to {max_downloads} worker(s).")

    with ThreadPoolExecutor(max_workers=max_downloads) as executor:
        futures = {}
        for item_idx, item_data in enumerate(items_to_download): # Using enumerate for better logging if needed
            if daemon_paused_due_to_cm_outage:
                logging.info(f"Daemon paused, stopping submission of new download tasks for job '{job_name}'.")
                # Update summary for remaining items that were not submitted
                # This assumes items not submitted are 'skipped' due to pause.
                summary["skipped_downloads"] += (len(items_to_download) - item_idx)
                break 
            
            if not cm_client: 
                logging.error(f"CMClient not available. Cannot submit download tasks for job '{job_name}'.")
                daemon_paused_due_to_cm_outage = True # Critical failure
                summary["failed_downloads"] += (len(items_to_download) - item_idx) # Mark remaining as failed
                break
            
            # Basic validation before submitting to thread
            doc_id_for_item = item_data.get("doc_id")
            if not doc_id_for_item:
                logging.warning(f"Skipping item in job '{job_name}' (index {item_idx}) due to missing 'doc_id': {item_data}")
                summary["skipped_downloads"] += 1
                continue
            
            # The helper _process_single_download will handle path construction and existence checks
            future = executor.submit(_process_single_download, item_data, target_dir_base, job_name, cm_client)
            futures[future] = doc_id_for_item # Use doc_id for tracking/logging

        for future in as_completed(futures):
            submitted_doc_id = futures[future] 
            try:
                result = future.result() # This will re-raise CMConnectionError if it occurred in the thread
                logging.debug(f"Thread download result for DocID {submitted_doc_id} (job: {job_name}): {result}")
                
                status = result.get("status", "failed_unexpected_result_format") # Default if result format is wrong
                if status == "success":
                    summary["successful_downloads"] += 1
                elif status in ["skipped_exists", "skipped_no_docid", "skipped_no_filename"]:
                    summary["skipped_downloads"] += 1
                else: # Covers "failed_cm_operation", "failed_no_client", "failed_unexpected_thread", etc.
                    summary["failed_downloads"] += 1
            except CMConnectionError as e:
                logging.error(f"CM connection error during threaded download for DocID {submitted_doc_id} (job: {job_name}): {e}. Pausing daemon.")
                daemon_paused_due_to_cm_outage = True
                summary["failed_downloads"] += 1 # Count this item as failed
                # No need to cancel other futures here, as_completed won't yield them if they raise.
                # The main pause check at the start of the outer loop will handle daemon pause.
                break # Stop processing further results for *this job file*
            except Exception as exc: 
                logging.error(f"Unexpected exception for DocID {submitted_doc_id} (job: {job_name}) during future.result(): {exc}", exc_info=True)
                summary["failed_downloads"] += 1 # Count as failed
            
            if daemon_paused_due_to_cm_outage: # If a parallel task (or this one) set the pause flag
                logging.warning(f"Daemon pause detected during future processing for download job '{job_name}'. Halting results processing.")
                break # Stop processing results for this job file.
    
    # Construct final status and message based on summary and pause state
    final_status = "success"
    message = f"Job '{job_name}' completed."
    if daemon_paused_due_to_cm_outage and (summary["failed_downloads"] > 0 or summary["skipped_downloads"] > 0): #Check if pause occurred AND there were issues
        final_status = "partial_error" 
        message = f"Job '{job_name}' processing interrupted by CM connection outage. Summary reflects tasks processed before or during interruption."
    elif summary["failed_downloads"] > 0 or summary["skipped_downloads"] > 0:
        final_status = "completed_with_issues"
        message = f"Job '{job_name}' completed with some issues. See summary."
    elif daemon_paused_due_to_cm_outage: # Pause occurred but no failures/skips recorded before pause (e.g. paused on first item)
        final_status = "partial_error"
        message = f"Job '{job_name}' processing interrupted by CM connection outage. No items were fully processed."


    logger.info(f"Finished processing download job '{job_name}'. Status: {final_status}. Summary: {summary}")
    return {"status": final_status, "message": message, "summary": summary}

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

# Helper function for process_metadata_update_job_file
def _process_single_metadata_update(item_to_update, job_name_for_logging, cm_client):
    doc_id = item_to_update.get("doc_id")
    object_id = item_to_update.get("object_id")
    object_id_field = item_to_update.get("object_id_field_name")
    item_type_ctx = item_to_update.get("item_type_context")
    metadata_to_update = item_to_update.get("metadata")

    item_identifier_log = doc_id if doc_id else f"ObjectID {object_id} (field: {object_id_field}, type: {item_type_ctx})"
    result_payload = {"identifier": item_identifier_log, "status": "pending_thread", "item_data": item_to_update}

    if not metadata_to_update or not isinstance(metadata_to_update, dict):
        logging.warning(f"Skipping metadata update in job '{job_name_for_logging}' for {item_identifier_log} due to missing or invalid 'metadata'.")
        result_payload["status"] = "skipped_no_metadata"
        return result_payload
    
    if not (doc_id or (object_id and object_id_field and item_type_ctx)):
        logging.warning(f"Skipping metadata update in job '{job_name_for_logging}' due to insufficient identifiers for item: {item_to_update}")
        result_payload["status"] = "skipped_no_identifier"
        return result_payload

    logging.info(f"Thread: Attempting to update metadata for {item_identifier_log} in job '{job_name_for_logging}'.")
    try:
        if not cm_client:
            logging.error(f"CMClient not available (thread). Cannot update metadata for {item_identifier_log}.")
            result_payload["status"] = "failed_no_client"
            return result_payload

        update_success = False
        if doc_id:
            update_success = cm_client.update_document_metadata(
                doc_id, metadata_to_update, id_is_object_id=False
            )
        else: # Must be object_id case based on earlier validation
            update_success = cm_client.update_document_metadata(
                object_id,
                metadata_to_update,
                id_is_object_id=True,
                object_id_field_name=object_id_field,
                item_type_context=item_type_ctx
            )
        
        if update_success:
            logging.info(f"Thread: Successfully updated metadata for {item_identifier_log}.")
            result_payload["status"] = "success"
        else:
            logging.warning(f"Thread: Failed to update metadata for {item_identifier_log} (CM operation returned False).")
            result_payload["status"] = "failed_cm_operation"
        return result_payload
    except CMConnectionError:
        raise
    except Exception as e:
        logging.error(f"Thread: Unexpected error updating metadata for {item_identifier_log}: {e}", exc_info=True)
        result_payload["status"] = "failed_unexpected_thread"
        result_payload["error_message"] = str(e)
        return result_payload

def process_metadata_update_job_file(job_file_path, cm_client, global_config):
    logger.info(f"Processing metadata update job file: {job_file_path}")
    try:
        with open(job_file_path, 'r') as f:
            job_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Metadata update job file not found: {job_file_path}")
        return {"status": "error", "message": "Job file not found", "summary": {"successful_updates": 0, "failed_updates": 0, "skipped_updates": 0}}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from job file {job_file_path}: {e}")
        return {"status": "error", "message": f"JSON decode error: {e}", "summary": {"successful_updates": 0, "failed_updates": 0, "skipped_updates": 0}}

    job_name = job_data.get("job_name", os.path.basename(job_file_path))
    logger.info(f"Starting metadata update job: {job_name}")

    summary = {"successful_updates": 0, "failed_updates": 0, "skipped_updates": 0}
    global daemon_paused_due_to_cm_outage

    items_to_update = job_data.get("updates", [])
    if not items_to_update:
        logger.info(f"No items for metadata update in job '{job_name}'.")
        return {"status": "success_empty_job", "message": "No items in job file.", "summary": summary}

    max_updates = global_config.get("performance", {}).get("max_parallel_metadata_updates", 1)
    if not isinstance(max_updates, int) or max_updates <= 0:
        logging.warning(f"Invalid max_parallel_metadata_updates value ({max_updates}), defaulting to 1.")
        max_updates = 1

    logging.info(f"Processing {len(items_to_update)} metadata update items for job '{job_name}' using up to {max_updates} worker(s).")

    with ThreadPoolExecutor(max_workers=max_updates) as executor:
        futures = {}
        for item_idx, item_data in enumerate(items_to_update):
            if daemon_paused_due_to_cm_outage:
                logging.info(f"Daemon paused, stopping submission of new metadata update tasks for job '{job_name}'.")
                summary["skipped_updates"] += (len(items_to_update) - item_idx)
                break
            
            if not cm_client:
                logging.error(f"CMClient not available. Cannot submit metadata update tasks for job '{job_name}'.")
                daemon_paused_due_to_cm_outage = True
                summary["failed_updates"] += (len(items_to_update) - item_idx)
                break

            # Basic validation before submitting
            if not item_data.get("metadata") or not isinstance(item_data.get("metadata"), dict):
                logging.warning(f"Skipping item in job '{job_name}' (index {item_idx}) due to missing or invalid 'metadata': {item_data.get('doc_id') or item_data.get('object_id')}")
                summary["skipped_updates"] += 1
                continue
            if not (item_data.get("doc_id") or (item_data.get("object_id") and item_data.get("object_id_field_name") and item_data.get("item_type_context"))):
                logging.warning(f"Skipping item in job '{job_name}' (index {item_idx}) due to insufficient identifiers: {item_data}")
                summary["skipped_updates"] += 1
                continue

            future = executor.submit(_process_single_metadata_update, item_data, job_name, cm_client)
            item_identifier = item_data.get("doc_id") or item_data.get("object_id", "unknown_identifier")
            futures[future] = item_identifier

        for future in as_completed(futures):
            submitted_identifier = futures[future]
            try:
                result = future.result()
                logging.debug(f"Thread metadata update result for {submitted_identifier} (job: {job_name}): {result}")
                status = result.get("status", "failed_unexpected_result_format")
                if status == "success":
                    summary["successful_updates"] += 1
                elif status.startswith("skipped_"):
                    summary["skipped_updates"] += 1
                else:
                    summary["failed_updates"] += 1
            except CMConnectionError as e:
                logging.error(f"CM connection error during threaded metadata update for {submitted_identifier} (job: {job_name}): {e}. Pausing daemon.")
                daemon_paused_due_to_cm_outage = True
                summary["failed_updates"] += 1
                break 
            except Exception as exc:
                logging.error(f"Unexpected exception for {submitted_identifier} (job: {job_name}) during future.result(): {exc}", exc_info=True)
                summary["failed_updates"] += 1
            
            if daemon_paused_due_to_cm_outage:
                logging.warning(f"Daemon pause detected during future processing for metadata update job '{job_name}'. Halting results processing.")
                break
    
    final_status = "success"
    message = f"Job '{job_name}' metadata update completed."
    total_items_in_job = len(items_to_update)
    processed_items_count = summary["successful_updates"] + summary["failed_updates"] + summary["skipped_updates"]

    if daemon_paused_due_to_cm_outage and processed_items_count < total_items_in_job:
        summary["skipped_updates"] += (total_items_in_job - processed_items_count)
        final_status = "partial_error"
        message = f"Job '{job_name}' metadata update processing interrupted by CM connection outage. Summary reflects tasks processed."
    elif summary["failed_updates"] > 0 or summary["skipped_updates"] > 0:
        final_status = "completed_with_issues"
        message = f"Job '{job_name}' metadata update completed with some issues. See summary."
    elif daemon_paused_due_to_cm_outage: # Pause occurred but all submitted items were processed
        final_status = "partial_error" # Still partial as daemon is now paused
        message = f"Job '{job_name}' metadata update completed, but a CM connection outage occurred, pausing the daemon."

    logger.info(f"Finished processing metadata update job '{job_name}'. Status: {final_status}. Summary: {summary}")
    return {"status": final_status, "message": message, "summary": summary}

def setup_logging(logging_config):
    log_file_path = logging_config.get("log_file_path", "logs/daemon.log")
    log_level_str = logging_config.get("log_level", "INFO").upper()
    # Ensure max_bytes and backup_count are integers, with defaults
    try:
        max_bytes = int(logging_config.get("log_rotation_max_bytes", 10*1024*1024)) 
    except ValueError:
        max_bytes = 10*1024*1024 # Default 10MB
        logging.warning(f"Invalid value for log_rotation_max_bytes. Defaulting to {max_bytes} bytes.")
    try:
        backup_count = int(logging_config.get("log_rotation_backup_count", 5))
    except ValueError:
        backup_count = 5 # Default 5 backups
        logging.warning(f"Invalid value for log_rotation_backup_count. Defaulting to {backup_count} backups.")


    # Ensure log directory exists
    log_dir = os.path.dirname(log_file_path)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            # Fallback to basic console logging if directory creation fails
            logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
            logging.error(f"Failed to create log directory {log_dir}: {e}. Logging may not work as configured.")
            return False # Exit setup if dir fails

    numeric_level = getattr(logging, log_level_str, None)
    if not isinstance(numeric_level, int):
        # Use basicConfig for this warning as full logging isn't set up yet.
        logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.warning(f"Invalid log level: {log_level_str}. Defaulting to INFO.")
        numeric_level = logging.INFO

    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s')

    # Rotating File Handler
    try:
        # Use 'utf-8' encoding for log files
        handler = logging.handlers.RotatingFileHandler(
            log_file_path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
        )
        handler.setFormatter(formatter)
        handler.setLevel(numeric_level) # Set level on handler too
    except Exception as e:
        # Fallback to basic console logging if handler setup fails
        logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.error(f"Failed to setup RotatingFileHandler for {log_file_path}: {e}. Logging may not work as configured.")
        return False

    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level) # Set overall level for the root logger

    # Remove any existing handlers from the root logger
    if root_logger.hasHandlers():
        for h_existing in list(root_logger.handlers): # Iterate over a copy
            root_logger.removeHandler(h_existing)
            if hasattr(h_existing, 'close'): # Check if handler has close method
                 h_existing.close()
    
    root_logger.addHandler(handler)

    # Log confirmation using the newly configured logger
    logging.info(f"Logging configured: level={log_level_str}, file={log_file_path}, rotation(maxBytes={max_bytes}, backups={backup_count})")
    return True

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

    cm_client = None # Initialize to None
    if config:
        # ... (logging setup should have already happened if config is loaded) ...
        if 'ibm_cm_api_base_url' in config and 'authentication' in config:
            cm_client = CMClient(config['ibm_cm_api_base_url'], config['authentication'])
            logging.info("CMClient initialized.")
        else:
            logging.error("IBM CM API base URL or authentication details missing in config. Cannot initialize CMClient.")
            # Depending on policy, could exit or run in a degraded mode if other functionalities exist

    if cm_client: # Proceed only if CMClient is initialized
        # Initial connection test
        global daemon_paused_due_to_cm_outage # Required to modify the global variable
        try:
            if not cm_client.test_connection():
                logging.warning("Initial connection test to CM failed. Daemon will be paused.")
                daemon_paused_due_to_cm_outage = True
            else:
                logging.info("Successfully connected to CM on initial test.")
        except CMConnectionError as e:
            logging.error(f"Initial CM connection failed critically: {e}. Daemon is paused.")
            daemon_paused_due_to_cm_outage = True
        except Exception as e: # Catch any other unexpected error during initial test
            logging.error(f"Unexpected error during initial CM connection test: {e}. Daemon is paused.")
            daemon_paused_due_to_cm_outage = True
            
        failed_archive_dir = config.get("download_settings", {}).get("failed_archive_directory", "failed_archive")
        if not os.path.exists(failed_archive_dir):
            try:
                os.makedirs(failed_archive_dir, exist_ok=True) # Ensure it exists
                logging.info(f"Ensured failed_archive_directory exists at: {failed_archive_dir}")
            except OSError as e:
                logging.error(f"Failed to create failed_archive_directory {failed_archive_dir}: {e}. Failed files may not be archived.")
                # This might be a critical error depending on requirements.

        # This is a very basic continuous loop for demonstration.
        try:
            while True: # Main daemon loop
                global daemon_paused_due_to_cm_outage # Required to modify the global variable

                if daemon_paused_due_to_cm_outage:
                    logging.info("Daemon is paused due to CM connection outage. Attempting to reconnect...")
                    retry_interval = config.get("daemon_settings", {}).get("cm_connection_retry_interval_seconds", 60)
                    try:
                        if cm_client and cm_client.test_connection():
                            daemon_paused_due_to_cm_outage = False
                            logging.info("CM connection restored. Resuming normal operations.")
                        else:
                            # test_connection returning False (but not raising CMConnectionError)
                            # is handled as still down.
                            logging.warning(f"CM connection still down (test_connection returned False). Retrying in {retry_interval} seconds.")
                    except CMConnectionError as e:
                        logging.error(f"CM reconnection attempt failed with CMConnectionError: {e}. Retrying in {retry_interval} seconds.")
                    except Exception as e: # Catch any other unexpected error during test_connection
                        logging.error(f"Unexpected error during CM reconnection attempt: {e}. Retrying in {retry_interval} seconds.")
                    
                    time.sleep(retry_interval)
                    continue # Skip the rest of the loop and retry connection test

                scan_configs_from_file = config.get("scan_directories", [])
                # Create a deep copy for in-session modification (like disabling one-time scans)
                # Note: json.loads(json.dumps(obj)) is a common way for deep copy of simple dicts/lists
                current_scan_configs = json.loads(json.dumps(scan_configs_from_file))

                active_scan_configs = [sc for sc in current_scan_configs if sc.get("enabled", True)]

                if not active_scan_configs:
                    logging.info("No active scan directories currently configured or enabled. Sleeping for 60s.")
                    time.sleep(60)
                    continue # Re-evaluate after sleep, in case config changed (not implemented yet)

                min_scan_interval = float('inf')
                processed_paths_in_cycle = set() # Keep track of paths processed in this cycle

                for dir_conf in active_scan_configs:
                    path_to_scan = dir_conf.get('path')
                    if path_to_scan in processed_paths_in_cycle: # Avoid processing same path multiple times if config has duplicates
                        continue
                    
                    logging.info(f"Processing scan configuration for: {path_to_scan}")
                    scan_directory(dir_conf, cm_client, failed_archive_dir) 
                    processed_paths_in_cycle.add(path_to_scan)

                    scan_interval = dir_conf.get("scan_interval_seconds", 0)
                    if scan_interval > 0:
                        min_scan_interval = min(min_scan_interval, scan_interval)
                    else: 
                        # For one-time scans (interval <= 0), disable them in the current_scan_configs copy
                        # This ensures they don't run again in this session unless config is reloaded.
                        # Find the corresponding entry in current_scan_configs to modify its 'enabled' status.
                        # This relies on path_to_scan being a unique identifier for a scan config entry.
                        for current_sc_entry in current_scan_configs:
                            if current_sc_entry.get("path") == path_to_scan:
                                current_sc_entry["enabled"] = False
                                logging.info(f"One-time scan for {path_to_scan} complete. Disabling for this session.")
                                break 
                
                # Determine sleep time based on remaining active configurations
                # Re-filter active_scan_configs from the potentially modified current_scan_configs
                active_scan_configs = [sc for sc in current_scan_configs if sc.get("enabled", True)]
                
                active_recurring_configs_exist = any(sc.get("scan_interval_seconds", 0) > 0 for sc in active_scan_configs)

                if not active_scan_configs: # No scans left enabled (all were one-time and now disabled)
                    logging.info("All scan tasks completed (all were one-time or no scans configured/enabled initially). Daemon will idle (sleep 300s).")
                    sleep_duration = 300
                elif not active_recurring_configs_exist: # No recurring scans left, but some non-recurring might still be (e.g. if one failed before being disabled)
                    logging.info("No active recurring scans. All remaining enabled scans are one-time (or have 0 interval). Processing done for this cycle. Sleeping for 60s.")
                    # This state implies that any remaining enabled scans are one-time scans that perhaps failed
                    # or were not processed in this cycle for some reason. Or, all were one-time and are now disabled.
                    # If all one-time scans were successfully processed and disabled, this branch might not be hit
                    # if the one above (not active_scan_configs) is hit first.
                    sleep_duration = 60
                else: # At least one active recurring scan exists
                    sleep_duration = min_scan_interval if min_scan_interval != float('inf') else 60
                    logging.info(f"Next scan cycle in approximately {sleep_duration} seconds.")
                
                time.sleep(sleep_duration)

        except KeyboardInterrupt:
            logging.info("Daemon shutting down due to KeyboardInterrupt.")
        finally:
            logging.info("Daemon has shut down.")
    else:
        logging.error("CMClient not initialized. Daemon cannot proceed with scanning tasks.")

# Helper function for scan_directory
def _process_single_file_upload(file_path, item_type, dir_config, cm_client, failed_archive_dir):
    # Note: global_config (or parts of it) might be needed if helper makes decisions based on it.
    # For now, assuming dir_config and direct params are sufficient for this helper.
    filename = os.path.basename(file_path)
    action_after_upload = dir_config.get("action_after_upload")
    move_target_dir = dir_config.get("move_target_directory")
    scan_root_path = dir_config.get("path") 
    current_file_root = os.path.dirname(file_path)

    try:
        if not cm_client: # Should be checked before submitting task ideally
            logging.error(f"CMClient not available (thread). Cannot process file {file_path}.")
            return {"status": "error_no_client", "file_path": file_path, "message": "CMClient not available"}

        upload_metadata = {"source_filename": filename, "original_path": file_path}
        logging.debug(f"Thread uploading {file_path} with metadata {upload_metadata}")
        doc_id = cm_client.upload_document(file_path, item_type, metadata=upload_metadata)

        if doc_id:
            logging.info(f"Successfully uploaded {filename} (from {file_path}), received DocID: {doc_id}")
            if action_after_upload == "delete":
                try:
                    os.remove(file_path)
                    logging.info(f"Deleted file after upload: {file_path}")
                except OSError as e:
                    logging.error(f"Failed to delete file {file_path} after upload: {e}")
                    return {"status": "error_post_upload_delete", "file_path": file_path, "doc_id": doc_id, "message": str(e)}
            elif action_after_upload == "move":
                if not move_target_dir:
                    logging.warning(f"Move action specified for {scan_root_path} but no move_target_directory configured. File {file_path} remains.")
                    return {"status": "success_upload_only_no_move_dir", "file_path": file_path, "doc_id": doc_id, "message": "Move skipped, no target dir"}

                effective_move_target_dir = move_target_dir
                if dir_config.get("recursive_scan", False) and scan_root_path != current_file_root:
                    relative_path = os.path.relpath(current_file_root, scan_root_path)
                    if relative_path and relative_path != '.':
                        effective_move_target_dir = os.path.join(move_target_dir, relative_path)
                
                if not os.path.exists(effective_move_target_dir):
                    try:
                        os.makedirs(effective_move_target_dir, exist_ok=True)
                    except OSError as e:
                        logging.error(f"Failed to create move target directory {effective_move_target_dir}: {e}. Attempting to move to root archive.")
                        effective_move_target_dir = move_target_dir 
                        if not os.path.exists(effective_move_target_dir):
                            try:
                                os.makedirs(effective_move_target_dir, exist_ok=True)
                            except OSError as e_root:
                                logging.error(f"Root move target directory {effective_move_target_dir} also not creatable: {e_root}. Skipping move for {file_path}")
                                return {"status": "error_post_upload_move_dir_creation", "file_path": file_path, "doc_id": doc_id, "message": f"Cannot create move dir {effective_move_target_dir}"}
                try:
                    destination_path = os.path.join(effective_move_target_dir, filename)
                    shutil.move(file_path, destination_path)
                    logging.info(f"Moved file {file_path} to {destination_path}")
                except (OSError, shutil.Error) as e:
                    logging.error(f"Failed to move file {file_path} to {effective_move_target_dir}: {e}")
                    return {"status": "error_post_upload_move_failed", "file_path": file_path, "doc_id": doc_id, "message": str(e)}
            return {"status": "success", "file_path": file_path, "doc_id": doc_id}
        else: 
            logging.warning(f"Upload of {filename} from {file_path} returned no DocID. Moving to failed archive.")
            if os.path.exists(file_path):
                move_to_failed_archive(file_path, failed_archive_dir, reason_subdir="upload_failure_no_docid")
            return {"status": "failed_upload_no_docid", "file_path": file_path}
    except CMConnectionError: 
        raise 
    except OSError as e: 
        logging.error(f"OS error during file processing for {file_path} in thread: {e}")
        return {"status": "error_os_level", "file_path": file_path, "message": str(e)}
    except Exception as e:
        logging.error(f"Unexpected error processing file {file_path} in thread: {e}", exc_info=True)
        if os.path.exists(file_path): 
            move_to_failed_archive(file_path, failed_archive_dir, reason_subdir="unexpected_processing_error_thread")
        return {"status": "error_unexpected_thread", "file_path": file_path, "message": str(e)}

def scan_directory(dir_config, cm_client, failed_archive_dir, global_config): # Added global_config
    global daemon_paused_due_to_cm_outage 

    path = dir_config.get("path")
    item_type = dir_config.get("target_itemtype_cm")
    file_pattern = dir_config.get("file_pattern", "*")
    recursive_scan = dir_config.get("recursive_scan", False)

    if not os.path.isdir(path):
        logging.warning(f"Scan path {path} does not exist or is not a directory. Skipping.")
        return

    logging.info(f"Scanning directory: {path} (Recursive: {recursive_scan}, Pattern: {file_pattern}) for item type: {item_type}")
    
    max_uploads = global_config.get("performance", {}).get("max_parallel_uploads", 1) 
    if not isinstance(max_uploads, int) or max_uploads <= 0:
        logging.warning(f"Invalid max_parallel_uploads value ({max_uploads}), defaulting to 1.")
        max_uploads = 1
    
    files_to_process = []
    if recursive_scan:
        for root, _, files in os.walk(path):
            if daemon_paused_due_to_cm_outage: 
                logging.info(f"Daemon paused, stopping file collection for recursive scan of {path}")
                return # Return early if daemon is paused
            for filename in files:
                if fnmatch.fnmatch(filename, file_pattern):
                    files_to_process.append(os.path.join(root, filename))
    else: 
        for filename in os.listdir(path):
            if daemon_paused_due_to_cm_outage: 
                logging.info(f"Daemon paused, stopping file collection for non-recursive scan of {path}")
                return # Return early if daemon is paused
            file_path_item = os.path.join(path, filename)
            if os.path.isfile(file_path_item) and fnmatch.fnmatch(filename, file_pattern):
                files_to_process.append(file_path_item)

    if not files_to_process:
        logging.info(f"No files matching criteria found in {path} for this scan cycle.")
        return
    
    logging.info(f"Found {len(files_to_process)} files to potentially process in {path} using up to {max_uploads} worker(s).")
    
    successful_uploads_count = 0
    submitted_files_count = 0

    with ThreadPoolExecutor(max_workers=max_uploads) as executor:
        futures = {}
        for fp in files_to_process:
            if daemon_paused_due_to_cm_outage: # Check before submitting new tasks
                logging.info(f"Daemon paused, stopping submission of new upload tasks for scan of {path}.")
                break 
            
            if not cm_client: # Check if cm_client is available
                logging.error(f"CMClient not available. Cannot submit task for file {fp}.")
                daemon_paused_due_to_cm_outage = True # Critical issue, pause daemon
                break
            
            # Submit task to the executor
            future = executor.submit(_process_single_file_upload, fp, item_type, dir_config, cm_client, failed_archive_dir)
            futures[future] = fp # Store future to map back to file_path if needed
            submitted_files_count += 1

        for future in as_completed(futures):
            file_path_submitted = futures[future]
            try:
                result = future.result() # This will re-raise CMConnectionError if it occurred in the thread
                logging.debug(f"Thread processing result for {file_path_submitted}: {result}")
                if result and result.get("status") == "success":
                    successful_uploads_count += 1
            except CMConnectionError as e:
                logging.error(f"CM connection error during threaded operation for {file_path_submitted}: {e}. Pausing daemon.")
                daemon_paused_due_to_cm_outage = True
                # Python 3.9+ allows executor.shutdown(cancel_futures=True)
                # For broader compatibility, we break and rely on the main loop's pause logic.
                # Any already running tasks will complete or error out.
                # New tasks are not submitted due to the check in the submission loop.
                break # Stop processing further results for this scan_directory call
            except Exception as exc: # Catch other exceptions from future.result()
                logging.error(f"Unexpected exception for file {file_path_submitted} during future.result(): {exc}", exc_info=True)
                # Attempt to move the original file if it still exists and wasn't handled by the thread's own error handling
                if os.path.exists(file_path_submitted):
                     move_to_failed_archive(file_path_submitted, failed_archive_dir, reason_subdir="executor_exception")
            
            if daemon_paused_due_to_cm_outage: # If a parallel task set the pause flag
                logging.warning("Daemon pause detected during future processing. Halting results processing for current scan of {path}.")
                break # Stop processing results for this scan directory

    if submitted_files_count > 0:
        logging.info(f"Finished scanning {path}. Submitted {submitted_files_count} files for processing, {successful_uploads_count} successful uploads confirmed in this cycle.")
    elif not daemon_paused_due_to_cm_outage : # Avoid logging "no files submitted" if paused mid-collection
        logging.info(f"Finished scanning {path}. No files were submitted for processing in this cycle (either none found or daemon was already paused).")
