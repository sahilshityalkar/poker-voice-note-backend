#!/usr/bin/env python
"""
Simple script to purge all tasks from the Celery queue.
Run this script when you want to completely clear all tasks.
"""

import os
import sys
from pathlib import Path

# Add the project directory to the Python path to ensure imports work correctly
project_path = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_path))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import Celery app
from cel_main import app

def purge_queue():
    """Purge all tasks from the queue"""
    print("Purging all tasks from the queue...")
    
    try:
        # Use the Celery control purge command
        result = app.control.purge()
        
        if result and sum(result.values()) > 0:
            print(f"Successfully purged {sum(result.values())} tasks from the queue")
        else:
            print("Queue is already empty, no tasks to purge")
        
        return True
        
    except Exception as e:
        print(f"Error purging queue: {e}")
        
        # Fallback method using direct RabbitMQ connection
        try:
            print("Trying fallback method...")
            conn = app.connection()
            conn.connect()
            channel = conn.channel()
            
            # Get the queue name from Celery config
            queue_name = app.conf.task_default_queue
            
            # Purge the queue
            result = channel.queue_purge(queue_name)
            print(f"Purged {result} messages from the queue")
            
            # Close the connection
            channel.close()
            conn.close()
            
            return True
        except Exception as e2:
            print(f"Fallback method failed: {e2}")
            return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Purge all tasks from the Celery queue")
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    if args.force:
        purge_queue()
    else:
        confirmation = input("This will purge ALL tasks from the queue. Are you sure? (y/n): ")
        if confirmation.lower() == 'y':
            purge_queue()
        else:
            print("Operation canceled.") 