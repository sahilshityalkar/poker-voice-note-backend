#!/usr/bin/env python
"""
Script to list and purge ALL queues in RabbitMQ, including any temporary or random queues.
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

# Import Celery app for connection info
from cel_main import app

def list_all_queues():
    """List all queues in the RabbitMQ server"""
    print("Connecting to RabbitMQ server...")
    
    try:
        # Get RabbitMQ URL from environment
        rabbitmq_url = os.getenv('RABBITMQ_URL')
        if not rabbitmq_url:
            print("RABBITMQ_URL environment variable not found.")
            return None
        
        # Parse the URL to get connection parameters
        import re
        from urllib.parse import urlparse, unquote
        
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
        
        # Use the RabbitMQ Management API to get all queues
        import requests
        from requests.auth import HTTPBasicAuth
        
        # Construct the Management API URL
        api_port = 15672  # Default management port
        api_url = f"http://{host}:{api_port}/api/queues"
        
        # Get all queues
        response = requests.get(
            api_url,
            auth=HTTPBasicAuth(username, password)
        )
        
        if response.status_code != 200:
            print(f"Failed to get queues: {response.status_code} - {response.text}")
            return None
        
        queues = response.json()
        
        # Print queue info
        print(f"\nFound {len(queues)} queues in RabbitMQ server:")
        print("-" * 60)
        print(f"{'Queue Name':<30} {'Messages':<10} {'Consumers':<10}")
        print("-" * 60)
        
        for queue in queues:
            name = queue.get('name', 'Unknown')
            messages = queue.get('messages', 0)
            consumers = queue.get('consumers', 0)
            print(f"{name:<30} {messages:<10} {consumers:<10}")
        
        return queues
        
    except Exception as e:
        print(f"Error listing queues: {e}")
        import traceback
        traceback.print_exc()
        return None

def purge_specific_queue(queue_name):
    """Purge a specific queue by name"""
    print(f"Purging queue: {queue_name}")
    
    try:
        # Get RabbitMQ URL from environment
        rabbitmq_url = os.getenv('RABBITMQ_URL')
        if not rabbitmq_url:
            print("RABBITMQ_URL environment variable not found.")
            return False
            
        # Use kombu Connection to purge the queue
        from kombu import Connection
        
        with Connection(rabbitmq_url) as conn:
            channel = conn.channel()
            
            # Purge the queue
            result = channel.queue_purge(queue_name)
            print(f"Purged {result} messages from queue '{queue_name}'")
            
            return True
            
    except Exception as e:
        print(f"Error purging queue '{queue_name}': {e}")
        
        # Try using the RabbitMQ Management API as fallback
        try:
            print("Trying fallback method with RabbitMQ Management API...")
            
            # Parse the URL to get connection parameters
            import re
            from urllib.parse import urlparse, unquote
            import requests
            from requests.auth import HTTPBasicAuth
            
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
            
            # Construct the Management API URL
            api_port = 15672  # Default management port
            api_url = f"http://{host}:{api_port}/api/queues/{vhost}/{queue_name}/contents"
            
            # Purge the queue
            response = requests.delete(
                api_url,
                auth=HTTPBasicAuth(username, password)
            )
            
            if response.status_code == 204:  # 204 No Content is the success response
                print(f"Successfully purged queue '{queue_name}' with API")
                return True
            else:
                print(f"Failed to purge queue with API: {response.status_code} - {response.text}")
                return False
                
        except Exception as api_error:
            print(f"Fallback method failed: {api_error}")
            return False
            
        return False

def purge_all_queues():
    """Purge all queues in the RabbitMQ server"""
    queues = list_all_queues()
    
    if not queues:
        print("No queues found or error listing queues.")
        return False
    
    print("\nPurging all queues...")
    
    for queue in queues:
        name = queue.get('name', 'Unknown')
        messages = queue.get('messages', 0)
        
        # Skip if no messages
        if messages == 0:
            print(f"Queue '{name}' is already empty, skipping.")
            continue
            
        # Purge the queue
        if purge_specific_queue(name):
            print(f"Successfully purged queue '{name}'")
        else:
            print(f"Failed to purge queue '{name}'")
    
    print("\nAll queues processed.")
    return True

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="List and purge RabbitMQ queues")
    parser.add_argument('--list', action='store_true', help='Only list queues without purging')
    parser.add_argument('--purge', action='store_true', help='Purge all queues')
    parser.add_argument('--queue', type=str, help='Purge a specific queue by name')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompts')
    
    args = parser.parse_args()
    
    print("=== RabbitMQ Queue Manager ===")
    
    if args.list:
        # Just list queues
        list_all_queues()
        
    elif args.queue:
        # Purge a specific queue
        if args.force:
            purge_specific_queue(args.queue)
        else:
            confirmation = input(f"This will purge queue '{args.queue}'. Are you sure? (y/n): ")
            if confirmation.lower() == 'y':
                purge_specific_queue(args.queue)
            else:
                print("Operation canceled.")
                
    elif args.purge:
        # Purge all queues
        if args.force:
            purge_all_queues()
        else:
            confirmation = input("This will purge ALL queues. Are you sure? (y/n): ")
            if confirmation.lower() == 'y':
                purge_all_queues()
            else:
                print("Operation canceled.")
                
    else:
        # Default: list queues and ask what to do
        queues = list_all_queues()
        
        if not queues:
            print("No queues found or error listing queues.")
            sys.exit(1)
            
        print("\nOptions:")
        print("1. Purge all queues")
        print("2. Purge a specific queue")
        print("0. Exit")
        
        choice = input("\nEnter choice (0-2): ")
        
        if choice == "1":
            confirmation = input("This will purge ALL queues. Are you sure? (y/n): ")
            if confirmation.lower() == 'y':
                purge_all_queues()
            else:
                print("Operation canceled.")
                
        elif choice == "2":
            print("\nAvailable queues:")
            for i, queue in enumerate(queues):
                name = queue.get('name', 'Unknown')
                messages = queue.get('messages', 0)
                print(f"{i+1}. {name} ({messages} messages)")
                
            try:
                idx = int(input("\nEnter queue number to purge (0 to cancel): "))
                if idx == 0:
                    print("Operation canceled.")
                elif 1 <= idx <= len(queues):
                    queue_name = queues[idx-1].get('name', 'Unknown')
                    confirmation = input(f"This will purge queue '{queue_name}'. Are you sure? (y/n): ")
                    if confirmation.lower() == 'y':
                        purge_specific_queue(queue_name)
                    else:
                        print("Operation canceled.")
                else:
                    print("Invalid queue number.")
            except ValueError:
                print("Invalid input. Expected a number.")
                
        else:
            print("Exiting.") 