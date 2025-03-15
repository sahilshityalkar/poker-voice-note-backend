#!/usr/bin/env python
"""
Script to examine and purge the random/amq.gen queue that still has pending messages.
"""

import os
import sys
from pathlib import Path
import re

# Add the project directory to the Python path to ensure imports work correctly
project_path = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_path))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import Celery app
from cel_main import app

def find_random_queues():
    """Find all random/generated queues in RabbitMQ"""
    try:
        # Get RabbitMQ URL from environment
        rabbitmq_url = os.getenv('RABBITMQ_URL')
        if not rabbitmq_url:
            print("RABBITMQ_URL environment variable not found.")
            return None
        
        # Parse the URL to get connection parameters
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
        
        # Filter for random/generated queues (those starting with amq.gen)
        random_queues = [q for q in queues if q.get('name', '').startswith(('amq.gen', 'celery.'))]
        
        # Print queue info
        if random_queues:
            print(f"\nFound {len(random_queues)} random/generated queues:")
            print("-" * 80)
            print(f"{'Queue Name':<50} {'Messages':<10} {'Consumers':<10}")
            print("-" * 80)
            
            for queue in random_queues:
                name = queue.get('name', 'Unknown')
                messages = queue.get('messages', 0)
                consumers = queue.get('consumers', 0)
                print(f"{name:<50} {messages:<10} {consumers:<10}")
        else:
            print("No random/generated queues found.")
        
        return random_queues
        
    except Exception as e:
        print(f"Error finding random queues: {e}")
        import traceback
        traceback.print_exc()
        return None

def purge_random_queue(queue_name):
    """Purge a specific random queue"""
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

def delete_random_queue(queue_name):
    """Delete a random queue entirely"""
    print(f"Deleting queue: {queue_name}")
    
    try:
        # Get RabbitMQ URL from environment
        rabbitmq_url = os.getenv('RABBITMQ_URL')
        if not rabbitmq_url:
            print("RABBITMQ_URL environment variable not found.")
            return False
            
        # Parse the URL to get connection parameters
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
        api_url = f"http://{host}:{api_port}/api/queues/{vhost}/{queue_name}"
        
        # Delete the queue
        response = requests.delete(
            api_url,
            auth=HTTPBasicAuth(username, password)
        )
        
        if response.status_code == 204:  # 204 No Content is the success response
            print(f"Successfully deleted queue '{queue_name}'")
            return True
        else:
            print(f"Failed to delete queue: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"Error deleting queue '{queue_name}': {e}")
        return False

if __name__ == "__main__":
    print("=== Random Queue Examiner ===")
    print("This script will find and manage random/generated queues in RabbitMQ")
    print()
    
    # Find all random queues
    random_queues = find_random_queues()
    
    if not random_queues:
        print("No random queues found or error occurred.")
        sys.exit(1)
    
    print("\nOptions:")
    print("1. Purge all random queues (clear messages)")
    print("2. Delete all random queues (remove completely)")
    print("3. Purge a specific random queue")
    print("4. Delete a specific random queue")
    print("0. Exit")
    
    choice = input("\nEnter choice (0-4): ")
    
    if choice == "1":
        confirmation = input("This will purge ALL random queues. Are you sure? (y/n): ")
        if confirmation.lower() == 'y':
            for queue in random_queues:
                name = queue.get('name', 'Unknown')
                messages = queue.get('messages', 0)
                
                if messages > 0:
                    if purge_random_queue(name):
                        print(f"Successfully purged queue '{name}'")
                    else:
                        print(f"Failed to purge queue '{name}'")
                else:
                    print(f"Queue '{name}' is already empty, skipping.")
        else:
            print("Operation canceled.")
            
    elif choice == "2":
        confirmation = input("This will DELETE ALL random queues. This is destructive! Are you sure? (y/n): ")
        if confirmation.lower() == 'y':
            double_check = input("Are you REALLY sure? This will remove the queues entirely. Type 'DELETE' to confirm: ")
            if double_check == "DELETE":
                for queue in random_queues:
                    name = queue.get('name', 'Unknown')
                    if delete_random_queue(name):
                        print(f"Successfully deleted queue '{name}'")
                    else:
                        print(f"Failed to delete queue '{name}'")
            else:
                print("Operation canceled.")
        else:
            print("Operation canceled.")
            
    elif choice == "3":
        print("\nAvailable random queues:")
        for i, queue in enumerate(random_queues):
            name = queue.get('name', 'Unknown')
            messages = queue.get('messages', 0)
            print(f"{i+1}. {name} ({messages} messages)")
            
        try:
            idx = int(input("\nEnter queue number to purge (0 to cancel): "))
            if idx == 0:
                print("Operation canceled.")
            elif 1 <= idx <= len(random_queues):
                queue_name = random_queues[idx-1].get('name', 'Unknown')
                confirmation = input(f"This will purge queue '{queue_name}'. Are you sure? (y/n): ")
                if confirmation.lower() == 'y':
                    purge_random_queue(queue_name)
                else:
                    print("Operation canceled.")
            else:
                print("Invalid queue number.")
        except ValueError:
            print("Invalid input. Expected a number.")
            
    elif choice == "4":
        print("\nAvailable random queues:")
        for i, queue in enumerate(random_queues):
            name = queue.get('name', 'Unknown')
            messages = queue.get('messages', 0)
            print(f"{i+1}. {name} ({messages} messages)")
            
        try:
            idx = int(input("\nEnter queue number to DELETE (0 to cancel): "))
            if idx == 0:
                print("Operation canceled.")
            elif 1 <= idx <= len(random_queues):
                queue_name = random_queues[idx-1].get('name', 'Unknown')
                confirmation = input(f"This will DELETE queue '{queue_name}'. Are you sure? (y/n): ")
                if confirmation.lower() == 'y':
                    delete_random_queue(queue_name)
                else:
                    print("Operation canceled.")
            else:
                print("Invalid queue number.")
        except ValueError:
            print("Invalid input. Expected a number.")
            
    else:
        print("Exiting.") 