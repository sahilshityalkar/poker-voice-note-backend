from celery import Celery
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from kombu import Queue, Exchange

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

# Define the queue explicitly
default_exchange = Exchange('celery', type='direct')
default_queue = Queue('celery', default_exchange, routing_key='celery')

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
    
    # Explicitly define queue settings to prevent random queue creation
    task_queues=(default_queue,),
    task_default_queue='celery',
    task_default_exchange='celery',
    task_default_exchange_type='direct',
    task_default_routing_key='celery',
    
    # Add retry settings for robust message delivery
    task_publish_retry=True,
    task_publish_retry_policy={
        'max_retries': 3,
        'interval_start': 0,
        'interval_step': 0.2,
        'interval_max': 0.5,
    }
)

# Print debug information
print(f"[CELERY] Python path: {sys.path}")
print(f"[CELERY] Project path: {project_path}")
print(f"[CELERY] Imported packages: {app.conf.imports}")
print(f"[CELERY] Connecting to broker URL: {os.getenv('RABBITMQ_URL')}")
print(f"[CELERY] Using queue: {app.conf.task_default_queue}")

