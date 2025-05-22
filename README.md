# Linux Daemon for IBM Content Manager 8.7 REST API Integration

This project implements a Linux daemon in Python 3.x to interact with the IBM Content Manager (CM) 8.7 REST API. It includes a core daemon for document and metadata management, a web dashboard for monitoring, and a web GUI for configuration.

## Project Goals
- Automate document operations (upload, download, update, delete) with IBM CM.
- Scan local directories for new documents to archive.
- Manage metadata associated with documents in CM.
- Provide a web-based dashboard for monitoring daemon status and statistics.
- Offer a web-based GUI for easy configuration of the daemon.

## Setup and Running (Initial - Docker Based)

### Prerequisites
- Docker
- Python 3.x (for local development outside Docker if needed)

### Configuration
1.  Copy `config/config.json.example` (once created) to `config/config.json`.
2.  Update `config/config.json` with your IBM Content Manager API details, paths, and other settings.

### Building the Docker Image
```bash
docker build -t cm-daemon .
```

### Running the Web Application (via Docker)
This will start the Flask web server for the dashboard and configuration GUI.
```bash
docker run -p 5000:5000 -v $(pwd)/config:/app/config -v $(pwd)/logs:/app/logs cm-daemon
```
*Note: The volume mounts (`-v`) are to persist config and logs outside the container.*

### Running the Daemon (Placeholder)
Detailed instructions for running the daemon process (potentially in a separate container or directly on a host) will be added here.
