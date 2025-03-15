from celery import Celery
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add the project directory to the Python path to ensure imports work correctly
project_path = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_path))

# Load environment variables
load_dotenv()

# Setup Celery app
app = Celery('cel_main', 
             broker=os.getenv('RABBITMQ_URL'),  # Use the RabbitMQ URL from the .env file
             backend='rpc://')  # Using RPC for result backend

# Include tasks packages
app.conf.imports = ['tasks.audio_tasks', 'tasks.text_tasks', 'tasks.transcript_update_tasks']

# Configure Celery
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_track_started=True,  # Track when tasks are started
    task_time_limit=3600,     # 1 hour time limit per task
    task_acks_late=False,  # Acknowledge tasks before processing
    broker_transport_options={'confirm_publish': True},  # Ensure publisher confirms
    worker_prefetch_multiplier=1,  # Lower prefetch count
)

# Print debug information
print(f"[CELERY] Python path: {sys.path}")
print(f"[CELERY] Project path: {project_path}")
print(f"[CELERY] Imported packages: {app.conf.imports}")

