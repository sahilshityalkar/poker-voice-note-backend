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
          retry_backoff_max=300,  # Max 5 minutes backoff
          acks_late=True)  # Only acknowledge task after it completes successfully
def process_text_task(self, text: str, user_id: str) -> Dict[str, Any]:
    """
    Celery task to process text input in the background.
    
    Args:
        text: Text to process (poker session notes/transcript)
        user_id: User ID of the uploader
        
    Returns:
        Results of the text processing pipeline
    """
    try:
        task_id = self.request.id
        retry_count = self.request.retries
        print(f"[CELERY] Starting text processing task {task_id} for user {user_id} (attempt {retry_count+1}/6)")
        
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
        
        # Return the full result
        return {
            "status": "completed",
            "task_id": task_id,
            "user_id": user_id,
            "text_length": len(text),
            "completion_time": datetime.now().isoformat(),
            "result": result
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