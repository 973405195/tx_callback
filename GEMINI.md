# Project Overview

This project is a Python-based web service that acts as a callback handler for Tencent Cloud's Media Processing Service (MPS). It is built using the Flask web framework.

The primary function of this service is to receive HTTP POST notifications from Tencent MPS whenever a video processing workflow task is completed. The service then parses the JSON payload of the notification to extract key information, such as:

*   Task ID and status
*   Results from AI-based content analysis, specifically video de-logo (removing watermarks)
*   Smart subtitling results, including full-text speech recognition and subtitle file paths
*   Original video URL and processed output paths

This extracted data is then inserted into a MySQL database table named `mps_task_result`. The service includes logic for retrying the database insertion in case of connection errors.

The main technologies used are:
*   **Python:** The core programming language.
*   **Flask:** A micro web framework for handling HTTP requests.
*   **Pymysql:** A Python library for connecting to and interacting with a MySQL database.
*   **Tencent Cloud SDK:** Used for interacting with Tencent Cloud services (though the current code primarily receives data rather than making API calls with the SDK).

# Building and Running

This is a Python project and requires a virtual environment for managing dependencies.

**1. Setup and Installation:**

First, ensure you have Python installed. Then, create and activate a virtual environment:

```bash
# Create a virtual environment (replace .venv with your preferred name)
python -m venv .venv

# Activate the virtual environment
# On Windows
.venv\Scripts\activate
# On macOS/Linux
source .venv/bin/activate
```

Next, install the required Python packages. Based on the imports in `tx_callback.py`, the following packages are needed:

```bash
pip install Flask Flask-Cors pymysql requests tencentcloud-sdk-python
```

**2. Running the Service:**

To start the Flask web server, run the main Python script:

```bash
python tx_callback.py
```

The service will start on `http://0.0.0.0:8787`.

**3. Testing:**

There are no automated tests in this project. To test the callback functionality, you would typically need to:
1.  Configure a workflow in Tencent Cloud MPS.
2.  Set the callback URL for the workflow to the public-facing address of this running service (e.g., using a tool like ngrok for local development).
3.  Trigger the MPS workflow by uploading a video.
4.  Monitor the console output of the `tx_callback.py` script to see the incoming POST request and processing logs.
5.  Check the `mps_task_result` table in the `video_auto` database to verify that the task data was inserted correctly.

# Development Conventions

*   **Configuration:** Database credentials and other settings like timeouts are hardcoded in the `tx_callback.py` script. For production environments, it is recommended to move these to environment variables or a separate configuration file.
*   **Error Handling:** The main callback endpoint (`/pyapi/mps/callback`) has a general `try...except` block to catch and log exceptions. The database insertion logic includes a retry mechanism with exponential backoff to handle transient connection issues.
*   **Logging:** The `logging` module is used for logging errors and informational messages.
*   **Dependencies:** The project's dependencies are not formally listed in a `requirements.txt` file but can be inferred from the import statements. It is a best practice to create one.
