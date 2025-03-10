# Audio Processing with Celery

This system uses Celery with RabbitMQ to process audio files asynchronously in the background while providing immediate responses to users.

## System Architecture

1. **FastAPI Server**: Handles HTTP requests and immediately returns responses
2. **RabbitMQ**: Message broker that queues tasks
3. **Celery Workers**: Process audio files and perform CPU-intensive tasks in the background

## Running the System

### Start the FastAPI Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Start the Celery Worker

```bash
celery -A cel_main worker --loglevel=INFO
```

## Flow

1. User uploads audio via the `/upload/` endpoint
2. System saves the audio file and returns an immediate response with a task ID
3. Processing task is queued in RabbitMQ
4. Celery worker picks up the task and processes it asynchronously
5. User can check task status via the `/task-status/{task_id}` endpoint

## Deployment

For production deployment, you should:

1. Host the API server on one instance
2. Host RabbitMQ and Celery workers on separate instances for better scalability
3. Configure environment variables for all connection strings
4. Use a process manager like Supervisor to keep all services running

## Task Status

Tasks can have the following statuses:

- `PENDING`: Task has been received but not yet started
- `PROCESSING`: Task is currently being processed
- `SUCCESS`: Task completed successfully
- `FAILURE`: Task failed with an error

## Task Results

When a task completes successfully, the result contains:
- The transcribed text
- AI-generated summary and insights
- Player information extracted from the transcript
- References to all created database objects 