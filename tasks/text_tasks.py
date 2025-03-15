from pathlib import Path
from typing import Dict, Any
from cel_main import app
import asyncio
import sys
from datetime import datetime
from bson import ObjectId

# Apply nest_asyncio unconditionally - this is critical for handling nested event loops in Celery tasks
try:
    import nest_asyncio
    # Apply nest_asyncio to allow nested event loops
    # This is needed to run async functions within Celery tasks
    nest_asyncio.apply()
    print("[CELERY] Successfully initialized nest_asyncio")
except ImportError:
    print("[CELERY] WARNING: nest_asyncio not available. Event loop issues may occur!")

# Debug information
print(f"[CELERY] Text Task Python path: {sys.path}")


@app.task(name="tasks.process_text", bind=True, queue='celery', 
          autoretry_for=(Exception,),  # Auto retry for all exceptions
          retry_kwargs={'max_retries': 5},  # Max 5 retries
          retry_backoff=True,  # Exponential backoff
          retry_backoff_max=300)  # Max 5 minutes backoff
def process_text_task(self, text: str, user_id: str) -> Dict[str, Any]:
    """
    Celery task to process text input in the background.
    
    Args:
        text: Text to process (poker session notes/transcript)
        user_id: User ID of the uploader
        
    Returns:
        Results of the text processing pipeline
    """
    # Import kombu for direct RabbitMQ communication if needed
    from kombu import Connection
    
    # Support for manual acknowledgment
    message_acknowledged = False
    delivery_info = None
    delivery_tag = None
    
    try:
        task_id = self.request.id
        retry_count = self.request.retries
        print(f"[CELERY] Starting text processing task {task_id} for user {user_id} (attempt {retry_count+1}/6)")
        
        # Debug: Check if we have message delivery info
        if hasattr(self.request, 'message') and self.request.message:
            delivery_info = getattr(self.request.message, 'delivery_info', None)
            delivery_tag = delivery_info.get('delivery_tag') if delivery_info else None
            print(f"[CELERY DEBUG] Task {task_id} has delivery_tag: {delivery_tag}")
            connection_id = getattr(self.request.message, 'channel', None)
            if connection_id:
                print(f"[CELERY DEBUG] Task connected via channel: {connection_id}")
        else:
            print(f"[CELERY DEBUG] Task {task_id} has no message attribute")
        
        # Update task status
        self.update_state(
            state="PROCESSING",
            meta={
                "text_length": len(text),
                "user_id": user_id,
                "start_time": datetime.now().isoformat(),
                "attempt": retry_count + 1
            }
        )
        
        # Import here to avoid circular imports
        from audio_processing.audio_api import process_text_directly
        
        # Always create a new event loop for each task
        # This prevents "attached to a different loop" errors
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Process the text
            result = loop.run_until_complete(process_text_directly(text, user_id, loop=loop))
            
            # Check if result indicates error
            if result.get("success") is False:
                error = result.get("error", "Unknown error in text processing")
                print(f"[TEXT] Text processing returned error: {error}")
                # Force task failure to trigger retry
                if retry_count < 5:
                    raise Exception(f"Text processing failed: {error}")
                    
        except Exception as loop_error:
            print(f"[TEXT] Error processing text directly: {loop_error}")
            # Return a meaningful error without crashing
            result = {
                "success": False,
                "error": str(loop_error),
                "message": "Error processing text input",
                "summary": "Error processing text input",
                "insight": "The system encountered an error while analyzing this text",
                "player_notes": []
            }
            # Always raise the exception to trigger a retry
            raise loop_error
        finally:
            # Clean up resources but DON'T close the loop
            try:
                # Cancel all running tasks
                pending = asyncio.all_tasks(loop=loop)
                for task in pending:
                    task.cancel()
                
                # Run loop until tasks are cancelled
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                
                # DO NOT close the loop - this causes "Event loop is closed" errors on subsequent runs
                # loop.close()  <- Removing this line
            except Exception as close_error:
                print(f"[CELERY] Warning: Error while cleaning up event loop tasks: {close_error}")
        
        print(f"[CELERY] Completed text processing task {task_id} for user {user_id}")
        
        # Attempt direct acknowledgment through multiple methods
        if not self.request.is_eager:
            try:
                # METHOD 1: Direct message acknowledgment if available
                if hasattr(self.request, 'message') and self.request.message is not None:
                    print(f"[CELERY] Attempting Method 1: Direct message acknowledgment for task {task_id}")
                    
                    # Check what type of message object we have (debugging info)
                    msg_type = type(self.request.message).__name__
                    print(f"[CELERY DEBUG] Message object type: {msg_type}")
                    
                    # Try to find acknowledgment method
                    if hasattr(self.request.message, 'ack'):
                        print(f"[CELERY DEBUG] Found message.ack() method")
                        self.request.message.ack()
                        message_acknowledged = True
                        print(f"[CELERY] Successfully acknowledged task {task_id} via message.ack()")
                    elif hasattr(self.request.message, 'acknowledge'):
                        print(f"[CELERY DEBUG] Found message.acknowledge() method")
                        self.request.message.acknowledge()
                        message_acknowledged = True
                        print(f"[CELERY] Successfully acknowledged task {task_id} via message.acknowledge()")
                    else:
                        print(f"[CELERY DEBUG] Message object has no ack/acknowledge method")
            except Exception as direct_ack_error:
                print(f"[CELERY] Method 1 failed: {direct_ack_error}")
            
            # METHOD 2: Try to acknowledge via task request
            if not message_acknowledged:
                try:
                    print(f"[CELERY] Attempting Method 2: Task request acknowledgment for task {task_id}")
                    if hasattr(self.request, 'acknowledge'):
                        self.request.acknowledge()
                        message_acknowledged = True
                        print(f"[CELERY] Successfully acknowledged task {task_id} via request.acknowledge()")
                except Exception as req_ack_error:
                    print(f"[CELERY] Method 2 failed: {req_ack_error}")
            
            # METHOD 3: Use connection via app - most reliable way
            if not message_acknowledged and delivery_tag:
                try:
                    print(f"[CELERY] Attempting Method 3: Direct channel acknowledgment for task {task_id}")
                    # Get connection from Celery app
                    conn = app.connection()
                    conn.connect()
                    channel = conn.channel()
                    
                    # Acknowledge the message using its delivery tag
                    channel.basic_ack(delivery_tag=delivery_tag)
                    
                    # Close the connection
                    channel.close()
                    conn.close()
                    
                    message_acknowledged = True
                    print(f"[CELERY] Successfully acknowledged task {task_id} via channel (tag: {delivery_tag})")
                except Exception as channel_ack_error:
                    print(f"[CELERY] Method 3 failed: {channel_ack_error}")
            
            # METHOD 4: Last resort - acknowledge all pending messages
            if not message_acknowledged:
                try:
                    print(f"[CELERY] Attempting Method 4: Acknowledge all pending messages for task {task_id}")
                    # Get connection from Celery app
                    conn = app.connection()
                    conn.connect()
                    channel = conn.channel()
                    
                    # Acknowledge all pending messages up to this point
                    # This is a last resort and will acknowledge ALL messages, not just this one
                    channel.basic_ack(delivery_tag=0, multiple=True)
                    
                    # Close the connection
                    channel.close()
                    conn.close()
                    
                    print(f"[CELERY] WARNING: Acknowledged ALL pending tasks via channel as last resort")
                    message_acknowledged = True
                except Exception as all_ack_error:
                    print(f"[CELERY] Method 4 failed: {all_ack_error}")
        
        # Return the full result
        return {
            "status": "completed",
            "task_id": task_id,
            "user_id": user_id,
            "text_length": len(text),
            "completion_time": datetime.now().isoformat(),
            "result": result,
            "message_acknowledged": message_acknowledged,
            "delivery_tag": delivery_tag
        }
        
    except Exception as e:
        print(f"[CELERY] Error in text processing task: {str(e)}")
        # Update task status to failed
        self.update_state(
            state="FAILED",
            meta={
                "text_length": len(text) if text else 0,
                "user_id": user_id,
                "error": str(e),
                "time": datetime.now().isoformat(),
                "attempt": self.request.retries + 1,
                "max_attempts": 6
            }
        )
        # Re-raise the exception to mark the task as failed and trigger a retry if retries remain
        raise 