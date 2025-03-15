from pathlib import Path
from typing import Dict, Any
from cel_main import app
import asyncio
import sys
from datetime import datetime

# Import the necessary functions from audio_processing
from audio_processing.audio_api import process_audio_file

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
        
        # Always create a new event loop for each task
        # This prevents "attached to a different loop" errors
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Check if the file path is a GCS URI
            if file_path.startswith("gs://"):
                # Pass the GCS URI directly to process_audio_file
                print(f"[CELERY] Processing GCS URI: {file_path}")
                result = loop.run_until_complete(process_audio_file(file_path, content_type, user_id))
            else:
                # Handle local file path
                path_obj = Path(file_path)
                result = loop.run_until_complete(process_audio_file(path_obj, content_type, user_id))
        except Exception as loop_error:
            print(f"[AUDIO] Error processing audio file: {loop_error}")
            # Return a meaningful error without crashing
            result = {
                "success": False,
                "error": str(loop_error),
                "message": "Error processing audio file",
                "summary": "Error processing audio file",
                "insight": "The system encountered an error while processing this audio",
                "player_notes": []
            }
        finally:
            # Always close the loop to clean up resources
            try:
                # Cancel all running tasks
                pending = asyncio.all_tasks(loop=loop)
                for task in pending:
                    task.cancel()
                
                # Run loop until tasks are cancelled
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                
                # Close the loop
                loop.close()
            except Exception as close_error:
                print(f"[CELERY] Warning: Error while closing event loop: {close_error}")
        
        # Here you could add notification logic to inform the user
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