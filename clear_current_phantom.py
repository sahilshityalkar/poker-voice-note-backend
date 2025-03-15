#!/usr/bin/env python
"""
Script to clear the current phantom task with ID: baf56c5e-9d73-46e7-afbc-c102c2d86d19
"""

import os
import sys
from pathlib import Path
from kombu import Connection

# Add the project directory to the Python path to ensure imports work correctly
project_path = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_path))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import Celery app
from cel_main import app

def clear_phantom_task():
    """Clear the current phantom task by purging the queue"""
    print("Clearing phantom task by purging the queue...")
    
    try:
        # Get RabbitMQ connection from Celery app
        rabbitmq_url = os.getenv('RABBITMQ_URL')
        if not rabbitmq_url:
            print("RABBITMQ_URL environment variable not found.")
            return False
        
        # Try to get information about tasks in the queue
        from celery.task.control import inspect
        i = inspect()
        active = i.active() or {}
        reserved = i.reserved() or {}
        
        print("Tasks currently in the queue:")
        for worker, tasks in active.items():
            for task in tasks:
                print(f"Active: {task.get('id')} - {task.get('name')}")
        
        for worker, tasks in reserved.items():
            for task in tasks:
                print(f"Reserved: {task.get('id')} - {task.get('name')}")
        
        # Use direct connection to purge the queue
        with Connection(rabbitmq_url) as conn:
            channel = conn.channel()
            
            # Get the queue name from Celery config
            queue_name = app.conf.task_default_queue
            
            # Purge the queue
            result = channel.queue_purge(queue_name)
            print(f"Purged {result} messages from the queue")
            
            return True
            
    except Exception as e:
        print(f"Error clearing phantom task: {e}")
        
        # Fallback method using Celery control API
        try:
            print("Trying fallback method with Celery control...")
            result = app.control.purge()
            print(f"Purged {sum(result.values())} messages from the queue")
            return True
        except Exception as e2:
            print(f"Fallback method failed: {e2}")
            return False

if __name__ == "__main__":
    print("=== Phantom Task Clearer ===")
    print("This script will clear the phantom task with ID: baf56c5e-9d73-46e7-afbc-c102c2d86d19")
    print("by purging all tasks from the queue.")
    print()
    
    confirmation = input("Are you sure you want to clear all tasks? (y/n): ")
    if confirmation.lower() == 'y':
        if clear_phantom_task():
            print("Successfully cleared the phantom task")
            print("Don't forget to restart your Celery worker:")
            print("celery -A cel_main worker --loglevel=info")
        else:
            print("Failed to clear the phantom task")
    else:
        print("Operation canceled.") 