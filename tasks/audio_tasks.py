from pathlib import Path
from typing import Dict, Any
from cel_main import app
import asyncio
import sys
from datetime import datetime

# Import the necessary functions from audio_processing
from audio_processing.audio_api import process_audio_file

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
print(f"[CELERY] Task Python path: {sys.path}")


@app.task(name="tasks.process_audio", bind=True)
def process_audio_task(self, file_path: str, content_type: str, user_id: str) -> Dict[str, Any]:
    """
    Celery task to process an audio file in the background.
    
    Args:
        file_path: Path to the saved audio file or GCS URI
        content_type: MIME type of the audio file
        user_id: User ID of the uploader
        
    Returns:
        Results of the audio processing pipeline
    """
    try:
        task_id = self.request.id
        print(f"[CELERY] Starting audio processing task {task_id} for user {user_id}")
        
        # Update task status (could be stored in a database or sent to a websocket)
        self.update_state(
            state="PROCESSING",
            meta={
                "file_path": file_path,
                "user_id": user_id,
                "start_time": datetime.now().isoformat()
            }
        )
        
        # Check if the file path is a GCS URI
        if file_path.startswith("gs://"):
            # Pass the GCS URI directly to process_audio_file
            # It will handle extracting the bucket and blob info
            print(f"[CELERY] Processing GCS URI: {file_path}")
            
            # Create an event loop and run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(process_audio_file(file_path, content_type, user_id))
            loop.close()
        else:
            # Handle local file path (existing behavior)
            # Convert string path to Path object
            path_obj = Path(file_path)
            
            # Create an event loop and run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(process_audio_file(path_obj, content_type, user_id))
            loop.close()
        
        # Here you could add notification logic to inform the user
        # (e.g., send an email, push notification, or websocket message)
        print(f"[CELERY] Completed audio processing task {task_id} for user {user_id}")
        
        # Return the full result
        return {
            "status": "completed",
            "task_id": task_id,
            "user_id": user_id,
            "file_path": file_path,
            "completion_time": datetime.now().isoformat(),
            "result": result
        }
        
    except Exception as e:
        print(f"[CELERY] Error in audio processing task: {str(e)}")
        # Update task status to failed
        self.update_state(
            state="FAILED",
            meta={
                "file_path": file_path,
                "user_id": user_id,
                "error": str(e),
                "time": datetime.now().isoformat()
            }
        )
        # Re-raise the exception to mark the task as failed
        raise 