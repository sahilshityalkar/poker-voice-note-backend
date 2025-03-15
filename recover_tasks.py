#!/usr/bin/env python3
"""
Task Recovery Utility Script

This script helps recover stalled or unacknowledged tasks from Celery queues.
Run this script when you need to recover tasks after worker downtime.
"""

import os
import sys
import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add the project directory to the Python path to ensure imports work correctly
project_path = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_path))

# Load environment variables
load_dotenv()

# Import Celery app
from cel_main import app

def get_task_info():
    """Get information about active, reserved, and scheduled tasks"""
    from celery.task.control import inspect
    
    i = inspect()
    
    # Get worker stats
    stats = i.stats() or {}
    active_tasks = i.active() or {}
    reserved_tasks = i.reserved() or {}
    scheduled_tasks = i.scheduled() or {}
    revoked_tasks = i.revoked() or {}
    
    # Print worker stats
    print(f"Worker stats: {stats}")
    print(f"Active tasks: {sum(len(tasks) for tasks in active_tasks.values())}")
    print(f"Reserved tasks: {sum(len(tasks) for tasks in reserved_tasks.values())}")
    print(f"Scheduled tasks: {sum(len(tasks) for tasks in scheduled_tasks.values())}")
    print(f"Revoked tasks: {len(revoked_tasks)}")
    
    # Print active tasks
    for worker, tasks in active_tasks.items():
        for task in tasks:
            task_id = task.get('id')
            task_name = task.get('name')
            runtime = task.get('time_start')
            print(f"Active task {task_id} ({task_name}) on worker {worker} running since {runtime}")
    
    return {
        "active": active_tasks,
        "reserved": reserved_tasks,
        "scheduled": scheduled_tasks,
        "revoked": revoked_tasks
    }

def purge_all_tasks():
    """Purge all tasks from the queue (use with caution)"""
    confirmation = input("Warning: This will purge ALL tasks from the queue. Type 'PURGE' to confirm: ")
    if confirmation.strip() != "PURGE":
        print("Purge canceled.")
        return False
    
    # Purge the queue
    result = app.control.purge()
    print(f"Purged tasks: {result}")
    return True

def restart_workers():
    """Restart all Celery workers"""
    confirmation = input("This will restart all Celery workers. Type 'RESTART' to confirm: ")
    if confirmation.strip() != "RESTART":
        print("Restart canceled.")
        return False
    
    # Restart all workers
    result = app.control.broadcast('pool_restart', arguments={'reload': True})
    print(f"Restart result: {result}")
    return True

def recover_unacked_tasks():
    """Attempt to recover unacknowledged tasks"""
    # First get current task info
    task_info = get_task_info()
    
    # Ask for confirmation before proceeding
    confirmation = input("This will attempt to recover unacked tasks. Type 'RECOVER' to confirm: ")
    if confirmation.strip() != "RECOVER":
        print("Recovery canceled.")
        return False
    
    # For RabbitMQ, we can use the management API or restart workers
    print("Attempting to recover tasks by restarting Celery workers...")
    app.control.broadcast('pool_restart', arguments={'reload': True})
    print("Recovery command sent. Unacked tasks should be redelivered.")
    
    return True

def retry_failed_task():
    """Manually retry a specific failed task"""
    task_id = input("Enter the task ID to retry: ").strip()
    if not task_id:
        print("No task ID provided.")
        return False
    
    task_name = input("Enter the task name (e.g., 'tasks.process_text'): ").strip()
    if not task_name:
        print("No task name provided.")
        return False
    
    # Create a new task with the same arguments
    confirmation = input(f"This will retry task {task_id}. Type 'RETRY' to confirm: ")
    if confirmation.strip() != "RETRY":
        print("Retry canceled.")
        return False
    
    print(f"Retrying task {task_id}...")
    try:
        # This is a simplified approach - in a real system, you would
        # need to get the original task arguments
        # For demonstration purposes, we'll just create a new placeholder task
        if task_name == "tasks.process_text":
            from tasks.text_tasks import process_text_task
            result = process_text_task.apply_async(args=["Sample text", "user_id"], countdown=0)
            print(f"New task created: {result.id}")
        else:
            print(f"Task type {task_name} not supported for manual retry")
    except Exception as e:
        print(f"Error retrying task: {e}")
        return False
    
    return True

def clear_stuck_ready_tasks():
    """
    Clean up tasks that are stuck in the "ready" queue after completion.
    This is useful when you see phantom tasks in the queue after processing.
    """
    from celery.task.control import inspect
    
    i = inspect()
    
    # Get queue stats
    stats = i.stats() or {}
    
    # Check for tasks in ready state
    reserved_tasks = i.reserved() or {}
    ready_count = sum(len(tasks) for tasks in reserved_tasks.values()) 
    print(f"Tasks in reserved/ready state: {ready_count}")
    
    for worker, tasks in reserved_tasks.items():
        for task in tasks:
            task_id = task.get('id')
            task_name = task.get('name')
            print(f"Found ready task {task_id} ({task_name}) on worker {worker}")
    
    # Ask for confirmation before purging
    confirmation = input("\nThis will purge all ready tasks. Type 'CLEAR-READY' to confirm: ")
    if confirmation.strip() != "CLEAR-READY":
        print("Operation canceled.")
        return False
    
    # Create a direct connection to RabbitMQ via Celery connection
    # Note: This is a more targeted approach than purging all
    print("Clearing stuck ready tasks...")
    try:
        # Get the Celery connection
        conn = app.connection()
        conn.connect()
        channel = conn.channel()
        
        # Get the queue name from Celery config
        queue_name = app.conf.task_default_queue
        
        # Purge the specific queue
        result = channel.queue_purge(queue_name)
        print(f"Purged {result} messages from queue '{queue_name}'")
        
        # Close the connection
        channel.close()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error clearing ready tasks: {e}")
        return False

def clear_task_by_id():
    """
    Clear a specific task by ID from the RabbitMQ queue.
    This requires the RabbitMQ Management plugin to be enabled.
    """
    task_id = input("Enter the task ID to clear: ").strip()
    if not task_id:
        print("No task ID provided.")
        return False
    
    # Get RabbitMQ connection information from environment
    rabbitmq_url = os.getenv('RABBITMQ_URL')
    if not rabbitmq_url:
        print("RABBITMQ_URL environment variable not found.")
        return False
    
    # Parse the RabbitMQ URL to get connection parameters
    import re
    match = re.match(r'amqp://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', rabbitmq_url)
    if not match:
        print(f"Failed to parse RabbitMQ URL: {rabbitmq_url}")
        return False
    
    username, password, host, port, vhost = match.groups()
    vhost = vhost or '/'
    
    print(f"Connecting to RabbitMQ at {host}:{port} as {username}")
    
    # Ask for confirmation
    confirmation = input(f"This will attempt to clear task {task_id} from the queue. Type 'CLEAR-TASK' to confirm: ")
    if confirmation.strip() != "CLEAR-TASK":
        print("Operation canceled.")
        return False
    
    try:
        # Try using the RabbitMQ Management API
        import requests
        from requests.auth import HTTPBasicAuth
        
        # Construct the Management API URL
        api_port = 15672  # Default management port
        queue_name = app.conf.task_default_queue
        
        # Get all messages in the queue
        api_url = f"http://{host}:{api_port}/api/queues/{vhost}/{queue_name}/get"
        
        # Request to get messages from the queue
        payload = {
            "count": 100,  # Get up to 100 messages
            "requeue": True,  # Requeue them after viewing
            "encoding": "auto"
        }
        
        response = requests.post(
            api_url, 
            json=payload,
            auth=HTTPBasicAuth(username, password)
        )
        
        if response.status_code != 200:
            print(f"Failed to get messages: {response.status_code} - {response.text}")
            return False
        
        messages = response.json()
        print(f"Found {len(messages)} messages in queue")
        
        # Find the message with our task ID
        target_message = None
        for msg in messages:
            properties = msg.get('properties', {})
            headers = properties.get('headers', {})
            
            # Look for the task ID in various places
            msg_id = headers.get('id', '')
            
            if msg_id == task_id or task_id in str(msg):
                target_message = msg
                break
        
        if not target_message:
            print(f"Task {task_id} not found in the queue")
            return False
        
        # Get the delivery tag
        delivery_tag = target_message.get('delivery_tag')
        print(f"Found task {task_id} with delivery tag {delivery_tag}")
        
        # Now reject the message to remove it
        # We need to use a direct connection for this
        from kombu import Connection
        
        with Connection(rabbitmq_url) as conn:
            channel = conn.channel()
            
            # Reject the message without requeuing
            channel.basic_reject(delivery_tag, requeue=False)
            print(f"Task {task_id} has been removed from the queue")
            
        return True
    except ImportError:
        print("Required packages not installed. Try: pip install requests")
        return False
    except Exception as e:
        print(f"Error clearing task: {e}")
        import traceback
        traceback.print_exc()
        return False

def force_purge_rabbitmq_queue():
    """
    Force purge a RabbitMQ queue using the Management API.
    This is a more direct approach than using Celery's purge command.
    """
    # Get RabbitMQ connection information from environment
    rabbitmq_url = os.getenv('RABBITMQ_URL')
    if not rabbitmq_url:
        print("RABBITMQ_URL environment variable not found.")
        return False
    
    # Parse the RabbitMQ URL to get connection parameters
    import re
    match = re.match(r'amqp://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', rabbitmq_url)
    if not match:
        print(f"Failed to parse RabbitMQ URL: {rabbitmq_url}")
        return False
    
    username, password, host, port, vhost = match.groups()
    vhost = vhost or '/'
    
    print(f"Connecting to RabbitMQ at {host}:{port} as {username}")
    
    # Ask for confirmation
    confirmation = input(f"This will FORCEFULLY purge all messages in the queue. Type 'FORCE-PURGE' to confirm: ")
    if confirmation.strip() != "FORCE-PURGE":
        print("Operation canceled.")
        return False
    
    try:
        # Try using the RabbitMQ Management API
        import requests
        from requests.auth import HTTPBasicAuth
        
        # Get the queue name from Celery config
        queue_name = app.conf.task_default_queue
        
        # Construct the Management API URL for purging the queue
        api_port = 15672  # Default management port
        
        # URL to purge the queue
        api_url = f"http://{host}:{api_port}/api/queues/{vhost}/{queue_name}/contents"
        
        # Make the DELETE request to purge the queue
        response = requests.delete(
            api_url,
            auth=HTTPBasicAuth(username, password)
        )
        
        if response.status_code == 204:  # 204 No Content is the success response
            print(f"Queue '{queue_name}' successfully purged")
            return True
        else:
            print(f"Failed to purge queue: {response.status_code} - {response.text}")
            
            # Try fallback method with direct connection
            print("Trying fallback method...")
            from kombu import Connection
            
            with Connection(rabbitmq_url) as conn:
                channel = conn.channel()
                result = channel.queue_purge(queue_name)
                print(f"Purged {result} messages from queue '{queue_name}' using direct connection")
                return True
                
            return False
            
    except ImportError:
        print("Required packages not installed. Try: pip install requests")
        return False
    except Exception as e:
        print(f"Error forcefully purging queue: {e}")
        import traceback
        traceback.print_exc()
        return False

def force_reject_message():
    """
    Forcefully reject a specific message from the RabbitMQ queue using the Management API.
    This is useful for removing stuck messages that have been delivered but not acknowledged.
    """
    # Get RabbitMQ connection information from environment
    rabbitmq_url = os.getenv('RABBITMQ_URL')
    if not rabbitmq_url:
        print("RABBITMQ_URL environment variable not found.")
        return False
    
    # Parse the RabbitMQ URL to get connection parameters
    import re
    match = re.match(r'amqp://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', rabbitmq_url)
    if not match:
        print(f"Failed to parse RabbitMQ URL: {rabbitmq_url}")
        return False
    
    username, password, host, port, vhost = match.groups()
    vhost = vhost or '/'
    
    print(f"Connecting to RabbitMQ at {host}:{port} as {username}")
    
    try:
        # Try using the RabbitMQ Management API
        import requests
        from requests.auth import HTTPBasicAuth
        import json
        
        # Get the queue name from Celery config
        queue_name = app.conf.task_default_queue
        
        # Construct the Management API URL to get messages
        api_port = 15672  # Default management port
        api_url = f"http://{host}:{api_port}/api/queues/{vhost}/{queue_name}/get"
        
        # Ask how many messages to check (getting all messages at once can be resource-intensive)
        try:
            count = int(input("How many messages to check (recommend 10-50): ") or "20")
        except ValueError:
            count = 20
        
        # Prepare the request to get messages
        data = {
            "count": count,
            "requeue": True,
            "encoding": "auto",
            "truncate": 50000
        }
        
        print(f"Fetching up to {count} messages from queue '{queue_name}'...")
        
        # Make the POST request to get messages
        response = requests.post(
            api_url,
            auth=HTTPBasicAuth(username, password),
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
            
        print(f"Found {len(messages)} messages in the queue.")
        
        # Display summary of messages
        for idx, msg in enumerate(messages):
            properties = msg.get("properties", {})
            headers = properties.get("headers", {})
            
            # Try to extract task id from the message
            task_id = None
            task_name = None
            
            # Extract from properties headers
            task_id = headers.get("id", None)
            if not task_id:
                # Try to extract from payload if it's a Celery task
                try:
                    payload = json.loads(msg.get("payload"))
                    task_id = payload.get("id", None)
                    task_name = payload.get("task", None)
                except (json.JSONDecodeError, TypeError):
                    pass
            
            delivery_tag = msg.get("delivery_tag")
                
            print(f"{idx+1}. Delivery Tag: {delivery_tag}")
            print(f"   Task ID: {task_id or 'Unknown'}")
            print(f"   Task: {task_name or 'Unknown'}")
            
            # Display a small portion of the payload
            try:
                payload_str = msg.get("payload", "")
                if len(payload_str) > 100:
                    payload_str = payload_str[:100] + "..."
                print(f"   Payload: {payload_str}")
            except:
                print("   Payload: [Error displaying payload]")
            print("")
        
        # Ask which message to reject
        try:
            idx = int(input("Enter the number of the message to reject (0 to cancel): "))
            if idx == 0:
                print("Operation canceled.")
                return False
                
            if idx < 1 or idx > len(messages):
                print(f"Invalid selection. Must be between 1 and {len(messages)}.")
                return False
                
            selected_msg = messages[idx-1]
            delivery_tag = selected_msg.get("delivery_tag")
            
            # Get confirmation
            confirm = input(f"Are you sure you want to REJECT message with delivery tag {delivery_tag}? (y/n): ")
            if confirm.lower() != 'y':
                print("Operation canceled.")
                return False
                
            # Use a direct connection to reject the message
            from kombu import Connection
            
            with Connection(rabbitmq_url) as conn:
                channel = conn.channel()
                
                # Reject the message without requeuing
                channel.basic_reject(delivery_tag, requeue=False)
                print(f"Successfully rejected message with delivery tag {delivery_tag}")
                
                # Close the connection
                channel.close()
                
            return True
                
        except ValueError:
            print("Invalid input. Expected a number.")
            return False
            
    except ImportError:
        print("Required packages not installed. Try: pip install requests")
        return False
    except Exception as e:
        print(f"Error rejecting message: {e}")
        import traceback
        traceback.print_exc()
        return False

def main_menu():
    """Display the main menu and handle user input"""
    while True:
        print("\n==== Task Recovery Utility ====")
        print("1. Get task information")
        print("2. Recover unacked tasks")
        print("3. Restart Celery workers")
        print("4. Purge all tasks")
        print("5. Retry a specific failed task")
        print("6. Clear stuck ready tasks")
        print("7. Clear a specific task by ID")
        print("8. Force purge RabbitMQ queue")
        print("9. Force reject specific message")
        print("0. Exit")
        
        choice = input("\nEnter choice (0-9): ")
        
        if choice == "1":
            get_task_info()
        elif choice == "2":
            recover_unacked_tasks()
        elif choice == "3":
            restart_workers()
        elif choice == "4":
            purge_all_tasks()
        elif choice == "5":
            retry_failed_task()
        elif choice == "6":
            clear_stuck_ready_tasks()
        elif choice == "7":
            clear_task_by_id()
        elif choice == "8":
            force_purge_rabbitmq_queue()
        elif choice == "9":
            force_reject_message()
        elif choice == "0":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    print(f"Task Recovery Utility - {datetime.datetime.now()}")
    print(f"Connecting to broker: {os.getenv('RABBITMQ_URL')}")
    
    if len(sys.argv) > 1:
        # Command line arguments provided
        if sys.argv[1] == "info":
            get_task_info()
        elif sys.argv[1] == "recover":
            recover_unacked_tasks()
        elif sys.argv[1] == "restart":
            restart_workers()
        elif sys.argv[1] == "purge":
            purge_all_tasks()
        elif sys.argv[1] == "clear-ready":
            clear_stuck_ready_tasks()
        elif sys.argv[1] == "clear-task":
            clear_task_by_id()
    else:
        # No arguments, show interactive menu
        main_menu() 