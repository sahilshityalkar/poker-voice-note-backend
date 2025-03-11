from pathlib import Path
from typing import Dict, Any
from cel_main import app
import asyncio
import sys
from datetime import datetime
from bson import ObjectId

# Try to import nest_asyncio, but don't fail if it's not available
try:
    import nest_asyncio
    # Apply nest_asyncio to allow nested event loops
    # This is needed to run async functions within Celery tasks
    nest_asyncio.apply()
    print("[CELERY] Successfully initialized nest_asyncio")
except ImportError:
    print("[CELERY] Warning: nest_asyncio not available. Using standard asyncio.")

# Debug information
print(f"[CELERY] Text Task Python path: {sys.path}")


@app.task(name="tasks.process_text", bind=True)
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
        print(f"[CELERY] Starting text processing task {task_id} for user {user_id}")
        
        # Update task status
        self.update_state(
            state="PROCESSING",
            meta={
                "text_length": len(text),
                "user_id": user_id,
                "start_time": datetime.now().isoformat()
            }
        )
        
        # Import here to avoid circular imports
        from audio_processing.audio_api import process_text_directly
        
        # Safely create and use an event loop without closing it
        try:
            # First check if there's a running event loop we can use
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    print("[CELERY] Existing event loop is closed, creating a new one")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                # No event loop in this thread, create one
                print("[CELERY] No event loop in thread, creating a new one")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Process the text
            result = loop.run_until_complete(process_text_directly(text, user_id))
            
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
                "time": datetime.now().isoformat()
            }
        )
        # Re-raise the exception to mark the task as failed
        raise 