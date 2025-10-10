# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python Flask service that acts as a webhook callback handler for Tencent Cloud Media Processing Service (MPS). It processes video workflow completion notifications and stores results in a MySQL database.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Running the Service
```bash
# Start the Flask development server
python tx_callback.py
```
Service runs on `http://0.0.0.0:8787`

### Testing
No automated tests exist. Manual testing requires:
1. Configure Tencent MPS workflow with callback URL pointing to this service
2. Upload video to trigger workflow
3. Monitor console output for incoming webhooks
4. Verify database records in `mps_task_result` table

## Architecture

### Core Components

**Single-file architecture** (`tx_callback.py`):
- Flask web server with CORS enabled
- Two endpoints: health check (`/`) and MPS callback (`/pyapi/mps/callback`)
- Database integration with retry logic and exponential backoff
- Processes two types of MPS events: DeLogo (watermark removal) and ASR (speech recognition)

### Data Flow
1. Tencent MPS sends POST webhook to `/pyapi/mps/callback`
2. Service validates `EventType` (only processes "WorkflowTask")
3. Extracts task data from different workflow types:
   - **DeLogo**: Processed video URL, subtitle files, timestamps
   - **ASR**: VTT subtitle files from speech recognition
4. Inserts structured data into MySQL table `mps_task_result`

### Database Schema
The `mps_task_result` table stores:
- `task_id`: Unique MPS task identifier
- `status`: Task completion status
- `video_name`: Extracted from file paths
- `url`: Direct link to processed video
- `vtt_url`: Chinese subtitle file path
- `en_vtt`: English subtitle file path
- `username`: From SessionContext

### Configuration
- Database credentials hardcoded in `MYSQL_CONFIG` (should be moved to environment variables)
- Tencent Cloud COS base URL: `https://zh-video-1322637479.cos.ap-shanghai.myqcloud.com`
- Connection timeouts: 60s connect, 30s read/write

### Error Handling
- Comprehensive retry logic for database connections (3 attempts with exponential backoff)
- Graceful handling of malformed JSON payloads
- Detailed logging for debugging workflow issues

## Security Considerations
- Database credentials exposed in source code
- No authentication on webhook endpoint
- CORS enabled for all origins