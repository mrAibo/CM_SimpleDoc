# Linux Daemon for IBM Content Manager 8.7 REST API Integration

This project implements a Linux daemon in Python 3.x to interact with the IBM Content Manager (CM) 8.7 REST API. It includes a core daemon for document and metadata management, a web dashboard for monitoring, and a web GUI for configuration.

## Project Goals
- Automate document operations (upload, download, update, delete) with IBM CM.
- Scan local directories for new documents to archive.
- Manage metadata associated with documents in CM.
- Provide a web-based dashboard for monitoring daemon status and statistics.
- Offer a web-based GUI for easy configuration of the daemon.

## Current Status
**Parallel Processing**: Directory scanning for uploads is parallelized for improved performance. Processing of download job files and metadata update job files is currently serial (one item after another within each job file). Future enhancements may introduce parallel processing for these job types as well.

## Configuration

The primary configuration for the daemon is managed through the `config/config.json` file. It is recommended to copy `config/config.json.example` to `config/config.json` and then customize it for your environment.

### Daemon Configuration (`config/config.json`)

The `config.json` file has the following main sections and keys:

-   **`ibm_cm_api_base_url`**: (String) The base URL for the IBM Content Manager REST API. Example: `"https://your-cm-api-host/api"`
-   **`authentication`**: (Object) Contains authentication details.
    -   `bearer_token`: (String) Your initial or long-lived bearer token if applicable. Placeholder: `"YOUR_INITIAL_BEARER_TOKEN"`
    -   `token_renewal_url`: (String) The full URL to the token renewal endpoint. Example: `"https://your-cm-api-host/auth/renew"`
    -   `token_expiry_threshold_seconds`: (Integer) Seconds before actual token expiry when a renewal attempt should be made. Default: `300`
-   **`scan_directories`**: (Array of Objects) Defines directories to scan for files to upload. Each object has:
    -   `path`: (String) Absolute path to the directory to scan.
    -   `scan_interval_seconds`: (Integer) How often to scan this directory. `0` means scan only once.
    -   `target_itemtype_cm`: (String) The IBM CM ItemType to assign to uploaded documents from this directory.
    -   `recursive_scan`: (Boolean) `true` to scan subdirectories, `false` for top-level only.
    -   `action_after_upload`: (String) What to do after successful upload: `"move"` or `"delete"`.
    -   `move_target_directory`: (String) Absolute path to move files to if `action_after_upload` is `"move"`. Subdirectory structure from recursive scans is preserved.
    -   `file_pattern`: (String) Glob pattern for files to include (e.g., `*.pdf`, `image_*.jpg`). Default is `*`.
    -   `enabled`: (Boolean) `true` to enable scanning for this configuration, `false` to disable.
-   **`download_settings`**: (Object) Settings for download operations (primarily for download jobs).
    -   `default_target_directory`: (String) Default base directory for downloaded files if not specified in a job.
    -   `failed_archive_directory`: (String) Directory where files that fail to upload during scans are moved. Subdirectories `upload_failure`, `unexpected_error` may be created here.
-   **`logging`**: (Object) Configuration for logging.
    -   `log_file_path`: (String) Path to the daemon's log file (e.g., `logs/daemon.log`). Relative paths are typically relative to `WorkingDirectory`.
    -   `log_level`: (String) Logging level (e.g., `"INFO"`, `"DEBUG"`, `"WARNING"`, `"ERROR"`).
    -   `log_rotation_max_bytes`: (Integer) Maximum size in bytes for a log file before rotation.
    -   `log_rotation_backup_count`: (Integer) Number of backup log files to keep.
-   **`performance`**: (Object) Settings related to parallel processing.
    -   `max_parallel_uploads`: (Integer) Maximum number of concurrent file uploads during directory scanning. (Currently implemented)
    -   `max_parallel_downloads`: (Integer) Maximum number of concurrent downloads when processing download jobs. (Currently serial, placeholder for future use)
    -   `max_parallel_metadata_updates`: (Integer) Maximum number of concurrent metadata updates when processing update jobs. (Currently serial, placeholder for future use)
-   **`daemon_settings`**: (Object) General daemon operational settings.
    -   `cm_connection_retry_interval_seconds`: (Integer) How long to wait in seconds before retrying connection to CM if it's lost.
    -   `internal_api_port_for_config_reload`: (Integer, Placeholder) Port for an internal API to trigger configuration reloads (not fully implemented).

## Setup and Running

### Prerequisites
- Python 3.x (Python 3.8+ recommended)
- Docker (for containerized deployment)

### Running with Docker

This method is suitable for development, testing, or containerized deployments.

1.  **Configuration**:
    *   Copy `config/config.json.example` to `config/config.json`.
    *   Update `config/config.json` with your IBM Content Manager API details, paths, and other settings as described in the "Daemon Configuration" section.
2.  **Building the Docker Image**:
    Navigate to the project root directory (where the `Dockerfile` is located) and run:
    ```bash
    docker build -t cm-daemon .
    ```
3.  **Running the Application (Daemon & Web UI via Docker)**:
    The current Docker `CMD` in the `Dockerfile` starts the web application (`web/app.py`). The daemon (`daemon/main.py`) is *not* automatically started by this command. For a full deployment including the daemon, the Docker entrypoint or CMD would need to be adjusted (e.g., using a supervisor process to manage both daemon and web app, or separate Docker services).

    To run the container (primarily for the web UI at this stage):
    ```bash
    # Ensure your config/config.json is populated.
    # Create a 'logs' directory in your project root if it doesn't exist for volume mounting.
    mkdir -p logs
    docker run -d -p 5000:5000 \
      -v $(pwd)/config:/app/config \
      -v $(pwd)/logs:/app/logs \
      --name cm-daemon-container \
      cm-daemon
    ```
    - Access the web interface (if used) at `http://localhost:5000`.
    - To run the daemon manually within this container (for testing):
      ```bash
      docker exec -it cm-daemon-container python daemon/main.py
      ```

### Running Directly (without Docker)

This method is suitable for running the daemon directly on a host, often for production or specific environments.

1.  **Ensure Python**: Make sure Python 3.x (e.g., 3.8 or newer) is installed on your system.
2.  **Clone Repository**: If you haven't already, clone the project repository:
    ```bash
    git clone <repository_url>
    cd <project_directory>
    ```
3.  **Create Virtual Environment** (recommended):
    ```bash
    python3 -m venv .venv
    ```
4.  **Activate Virtual Environment**:
    ```bash
    source .venv/bin/activate
    ```
    (On Windows, use `.venv\Scripts\activate`)
5.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
6.  **Configure**:
    *   Copy `config/config.json.example` to `config/config.json`.
    *   Edit `config/config.json` with your specific IBM CM API details, paths, logging, and performance settings as detailed in the "Daemon Configuration" section.
7.  **Run the Daemon**:
    ```bash
    python daemon/main.py
    ```
    The daemon will start, log to the configured file (and console if not fully set up for file logging initially), and begin its operations.
8.  **Deactivate Virtual Environment** (when done):
    ```bash
    deactivate
    ```

### Running as a systemd Service

This allows the daemon to run as a background service on Linux systems managed by systemd.

1.  **Deploy Application**:
    *   Ensure the entire application (the project directory) is deployed to a stable location on your server, for example, `/opt/cm-daemon`.
    *   Ensure Python 3.x and all dependencies from `requirements.txt` are available in the environment where the service will run (either system-wide or in a virtual environment accessible by the service user). If using a virtual environment, the `ExecStart` path below will need to point to the python interpreter within that venv.
2.  **Customize `scripts/cm-daemon.service`**:
    *   Open `scripts/cm-daemon.service` in a text editor.
    *   **`User`**: Change `your_user` to the Linux user the daemon should run as (e.g., `cmdaemonuser`). This user needs read/write access to scan directories, move targets, log directories, and the config directory.
    *   **`Group`**: Change `your_group` to the corresponding group for the user.
    *   **`WorkingDirectory`**: Update this to the absolute path where you deployed the application (e.g., `/opt/cm-daemon`).
    *   **`ExecStart`**:
        *   Ensure the path to `python3` is correct for your system (e.g., `/usr/bin/python3`, or `/opt/cm-daemon/.venv/bin/python3` if using a venv within the deployment).
        *   Ensure the path to `daemon/main.py` is correct relative to `WorkingDirectory` (e.g., `/opt/cm-daemon/daemon/main.py`).
3.  **Install and Manage Service**:
    *   Copy the customized service file to the systemd directory:
        ```bash
        sudo cp scripts/cm-daemon.service /etc/systemd/system/cm-daemon.service
        ```
    *   Reload the systemd manager configuration:
        ```bash
        sudo systemctl daemon-reload
        ```
    *   Enable the service to start automatically on boot:
        ```bash
        sudo systemctl enable cm-daemon.service
        ```
    *   Start the service immediately:
        ```bash
        sudo systemctl start cm-daemon.service
        ```
    *   Check the status of the service:
        ```bash
        sudo systemctl status cm-daemon.service
        ```
    *   View logs (daemon's own logs are in `logs/daemon.log` as per config; systemd journal might also capture initial stdout/stderr):
        ```bash
        sudo journalctl -u cm-daemon.service -f 
        ```
        (Or check the file specified in `log_file_path` in `config/config.json`)

### Running the Daemon (Placeholder - Old Section, to be removed if covered above)
Detailed instructions for running the daemon process (potentially in a separate container or directly on a host) will be added here.
(This section seems redundant now with "Running Directly" and "Running as a systemd Service")
