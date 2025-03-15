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

def main_menu():
    """Display the main menu and handle user input"""
    while True:
        print("\n==== Task Recovery Utility ====")
        print("1. Get task information")
        print("2. Recover unacked tasks")
        print("3. Restart Celery workers")
        print("4. Purge all tasks")
        print("5. Retry a specific failed task")
        print("0. Exit")
        
        choice = input("\nEnter choice (0-5): ")
        
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
    else:
        # No arguments, show interactive menu
        main_menu() 