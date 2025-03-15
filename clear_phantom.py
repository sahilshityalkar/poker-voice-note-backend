#!/usr/bin/env python
"""
Script to clear a specific phantom task from RabbitMQ queue.
This script directly targets the task ID: aeb14b2e-c824-4f5a-9edf-8ba44eaaa25b 
or any other task ID provided as an argument.
"""

import os
import sys
import re
import json
import argparse
from urllib.parse import urlparse, unquote

# The specific task ID from the user's query
DEFAULT_TASK_ID = "aeb14b2e-c824-4f5a-9edf-8ba44eaaa25b"

def get_rabbitmq_info():
    """Get RabbitMQ connection info from environment variables"""
    rabbitmq_url = os.getenv('RABBITMQ_URL')
    if not rabbitmq_url:
        print("ERROR: RABBITMQ_URL environment variable not found.")
        sys.exit(1)
    
    # Parse the URL
    try:
        # Handle URL encoding
        if '%' in rabbitmq_url:
            rabbitmq_url = unquote(rabbitmq_url)
            
        parsed = urlparse(rabbitmq_url)
        
        # Extract username and password
        auth = parsed.netloc.split('@')[0]
        username, password = auth.split(':')
        
        # Extract host and port
        host_port = parsed.netloc.split('@')[1]
        if ':' in host_port:
            host, port = host_port.split(':')
            port = int(port)
        else:
            host = host_port
            port = 5672  # Default RabbitMQ port
        
        # Extract vhost
        vhost = parsed.path.lstrip('/') or '/'
        
        return {
            'username': username,
            'password': password,
            'host': host,
            'port': port,
            'vhost': vhost
        }
    except Exception as e:
        print(f"ERROR: Failed to parse RabbitMQ URL: {e}")
        sys.exit(1)

def clear_specific_task(task_id, dry_run=False):
    """Clear a specific task from the RabbitMQ queue"""
    print(f"Attempting to clear task: {task_id}")
    
    # Get RabbitMQ connection info
    rabbitmq_info = get_rabbitmq_info()
    print(f"Connecting to RabbitMQ at {rabbitmq_info['host']}:{rabbitmq_info['port']} as {rabbitmq_info['username']}")
    
    try:
        # Try using the RabbitMQ Management API
        import requests
        from requests.auth import HTTPBasicAuth
        
        # Construct the Management API URL to get queue info
        api_port = 15672  # Default management port
        api_base = f"http://{rabbitmq_info['host']}:{api_port}/api"
        
        # Get queue name from Celery config
        try:
            # Try to import from Celery app
            from cel_main import app
            queue_name = app.conf.task_default_queue
        except ImportError:
            # Default to 'celery' if import fails
            queue_name = 'celery'
            print("WARNING: Could not import Celery app. Using default queue name 'celery'.")
        
        print(f"Target queue: {queue_name}")
        
        # Get queue details
        queue_url = f"{api_base}/queues/{rabbitmq_info['vhost']}/{queue_name}"
        response = requests.get(
            queue_url,
            auth=HTTPBasicAuth(rabbitmq_info['username'], rabbitmq_info['password'])
        )
        
        if response.status_code != 200:
            print(f"Failed to get queue info: {response.status_code} - {response.text}")
            return False
        
        queue_info = response.json()
        message_count = queue_info.get('messages_ready', 0)
        print(f"Queue has {message_count} messages ready")
        
        if message_count == 0:
            print("No messages to process.")
            return False
        
        # Define how many messages to fetch at once
        batch_size = min(50, message_count)  # Don't fetch more than 50 at once
        
        # URL to get messages from the queue
        messages_url = f"{api_base}/queues/{rabbitmq_info['vhost']}/{queue_name}/get"
        
        # Data for the request
        data = {
            "count": batch_size,
            "requeue": True,  # Keep messages in queue until we decide to reject them
            "encoding": "auto",
            "truncate": 50000  # Set a reasonable message size limit
        }
        
        # Make the POST request to get messages
        print(f"Fetching up to {batch_size} messages from queue...")
        response = requests.post(
            messages_url,
            auth=HTTPBasicAuth(rabbitmq_info['username'], rabbitmq_info['password']),
            json=data,
            headers={"content-type": "application/json"}
        )
        
        if response.status_code != 200:
            print(f"Failed to fetch messages: {response.status_code} - {response.text}")
            return False
        
        messages = response.json()
        if not messages:
            print("No messages found in the queue.")
            return False
        
        print(f"Fetched {len(messages)} messages. Scanning for task ID: {task_id}")
        found = False
        
        # Scan through messages for the task ID
        for idx, msg in enumerate(messages):
            properties = msg.get('properties', {})
            headers = properties.get('headers', {})
            
            # Try to extract task id from the message
            msg_task_id = None
            
            # Method 1: Look in headers
            msg_task_id = headers.get('id')
            
            # Method 2: Look in payload
            if not msg_task_id:
                try:
                    payload = json.loads(msg.get('payload', '{}'))
                    msg_task_id = payload.get('id')
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # If message doesn't have a task ID visible, we'll need to scan the payload
            if not msg_task_id:
                payload_str = msg.get('payload', '')
                if task_id in payload_str:
                    print(f"Found task ID in message payload at position {idx+1}")
                    msg_task_id = task_id
            
            if msg_task_id == task_id:
                found = True
                delivery_tag = msg.get('delivery_tag')
                print(f"FOUND TARGET TASK at position {idx+1}!")
                print(f"Delivery tag: {delivery_tag}")
                
                if dry_run:
                    print("DRY RUN: Would reject message with delivery tag", delivery_tag)
                    return True
                
                # Reject the message without requeuing
                print("Rejecting message...")
                
                # Use direct connection to reject
                try:
                    import pika
                    
                    # Create a connection
                    credentials = pika.PlainCredentials(
                        rabbitmq_info['username'], 
                        rabbitmq_info['password']
                    )
                    
                    parameters = pika.ConnectionParameters(
                        host=rabbitmq_info['host'],
                        port=rabbitmq_info['port'],
                        virtual_host=rabbitmq_info['vhost'],
                        credentials=credentials
                    )
                    
                    connection = pika.BlockingConnection(parameters)
                    channel = connection.channel()
                    
                    # Reject the message without requeuing
                    channel.basic_reject(delivery_tag=delivery_tag, requeue=False)
                    print(f"Successfully rejected message with delivery tag {delivery_tag}")
                    
                    # Close the connection
                    connection.close()
                    return True
                    
                except ImportError:
                    print("Pika library not installed. Try: pip install pika")
                    return False
                except Exception as e:
                    print(f"Error rejecting message: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        if not found:
            print(f"Task ID {task_id} not found in the first {batch_size} messages.")
            
            # If there are more messages, ask to continue searching
            remaining = message_count - batch_size
            if remaining > 0:
                print(f"There are {remaining} more messages in the queue.")
                return False
        
        return found
        
    except ImportError:
        print("Required packages not installed. Try: pip install requests pika")
        return False
    except Exception as e:
        print(f"Error clearing task: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description='Clear a specific phantom task from RabbitMQ')
    parser.add_argument('--task-id', default=DEFAULT_TASK_ID, 
                        help=f'Task ID to clear (default: {DEFAULT_TASK_ID})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Scan for the task but do not remove it')
    
    args = parser.parse_args()
    
    print("=== Phantom Task Cleaner ===")
    print(f"Target Task ID: {args.task_id}")
    
    if args.dry_run:
        print("DRY RUN MODE: Will not actually remove messages")
    
    result = clear_specific_task(args.task_id, args.dry_run)
    
    if result:
        print("Operation completed successfully.")
        return 0
    else:
        print("Operation failed or task not found.")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 