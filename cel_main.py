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
    task_acks_late=True,      # Acknowledge tasks only after processing completes successfully
    broker_transport_options={
        'confirm_publish': True,  # Ensure publisher confirms
        'visibility_timeout': 3600,  # 1 hour - how long before a task is redelivered if not acknowledged
    },
    worker_prefetch_multiplier=1,  # Lower prefetch count
    
    # Task acknowledgment settings
    worker_cancel_long_running_tasks_on_connection_loss=True,  # Cancel tasks if connection lost
    task_reject_on_worker_lost=True,  # Reject task if worker dies
    
    # Retry settings for failed tasks
    task_default_retry_delay=30,  # 30 seconds delay before first retry
    task_max_retries=5,          # Maximum of 5 retries
    task_retry_jitter=True,      # Add jitter to avoid thundering herd
    
    # Ensure tasks aren't lost if they fail
    task_always_eager=False,      # Don't run tasks synchronously
    task_store_errors_even_if_ignored=True,  # Store errors even when ignored
    task_ignore_result=False,     # Don't ignore results
    result_expires=86400,         # Results expire after 1 day
    
    # Add retry settings for more resilience
    task_publish_retry=True,
    task_publish_retry_policy={
        'max_retries': 5,
        'interval_start': 0,
        'interval_step': 0.2,
        'interval_max': 0.5,
    },
    
    # Explicitly define queue settings to prevent random queue creation
    task_queues=(default_queue,),
    task_default_queue='celery',
    task_default_exchange='celery',
    task_default_exchange_type='direct',
    task_default_routing_key='celery',
)

# Print debug information
print(f"[CELERY] Python path: {sys.path}")
print(f"[CELERY] Project path: {project_path}")
print(f"[CELERY] Imported packages: {app.conf.imports}")
print(f"[CELERY] Connecting to broker URL: {os.getenv('RABBITMQ_URL')}")
print(f"[CELERY] Using queue: {app.conf.task_default_queue}")

