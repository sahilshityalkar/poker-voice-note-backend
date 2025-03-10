import sys
from pathlib import Path
from typing import Dict, Any
import asyncio
from datetime import datetime
from bson.objectid import ObjectId
import traceback

# Add parent directory to path to allow imports
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import Celery app
from cel_main import app

# Try to import nest_asyncio to handle nested event loops
try:
    import nest_asyncio
    nest_asyncio.apply()
    print("[CELERY] Successfully initialized nest_asyncio")
except ImportError:
    print("[WARNING] nest_asyncio not installed, may have issues with nested event loops")
except Exception as nest_error:
    print(f"[WARNING] Error setting up nest_asyncio: {nest_error}")

@app.task(bind=True, name="update_transcript_task")
def update_transcript_task(self, note_id: str, text: str, user_id: str) -> Dict[str, Any]:
    """
    Celery task to update a note's transcript and reprocess all data
    
    Args:
        self: Task instance
        note_id: ObjectId of the note to update
        text: New transcript text
        user_id: User ID who owns the note
        
    Returns:
        Dict with the result of the operation
    """
    print(f"[TASK] Starting transcript update task for note: {note_id}")
    
    # Update task state to STARTED
    self.update_state(state='STARTED', meta={
        'message': f'Processing transcript update for note {note_id}',
        'note_id': note_id,
        'text_length': len(text),
        'progress': 0
    })
    
    try:
        # Make sure nest_asyncio is applied
        try:
            import nest_asyncio
            nest_asyncio.apply()
            print("[TASK] Applied nest_asyncio for this task")
        except ImportError:
            print("[TASK] nest_asyncio not available, proceeding with caution")
        except Exception as nest_err:
            print(f"[TASK] Error applying nest_asyncio: {nest_err}")
        
        # Use a persistent loop variable to avoid "Event loop is closed" errors
        loop = None
        
        # Create the async function that contains all the processing work
        async def process_transcript_update():
            # Import here to avoid circular imports
            from audio_processing.audio_api import update_transcript_directly
            
            # Run the update function and return the result
            try:
                result = await update_transcript_directly(note_id, text, user_id)
                return result
            except Exception as e:
                print(f"[TASK] Error in update_transcript_directly: {str(e)}")
                return {
                    "success": False,
                    "error": str(e),
                    "message": "Error updating transcript"
                }
        
        # Create a new event loop - more robust approach
        try:
            # Check if there's an existing event loop that's running
            try:
                existing_loop = asyncio.get_event_loop()
                if existing_loop.is_running():
                    print("[TASK] Using existing running event loop")
                    loop = existing_loop
                else:
                    print("[TASK] Creating new event loop (existing one not running)")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                # No event loop exists in this thread
                print("[TASK] No event loop exists, creating new one")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the async function in the loop
            print("[TASK] Running async function in loop")
            result = loop.run_until_complete(process_transcript_update())
            
            # If processing succeeded
            if result.get("success", False):
                self.update_state(state='SUCCESS', meta={
                    'message': 'Transcript update completed successfully',
                    'note_id': note_id,
                    'transcript': text[:100] + "..." if len(text) > 100 else text,
                    'summary': result.get('summary', '')[:100] + "..." if result.get('summary', '') and len(result.get('summary', '')) > 100 else result.get('summary', ''),
                    'players_count': len(result.get('player_notes', [])),
                    'progress': 100
                })
                print(f"[TASK] Transcript update completed for note: {note_id}")
                return {
                    'success': True,
                    'message': 'Transcript update completed successfully',
                    'data': result
                }
            else:
                # If processing failed but we got an error message
                error_message = result.get('message', 'Unknown error during transcript update')
                self.update_state(state='FAILURE', meta={
                    'message': error_message,
                    'note_id': note_id,
                    'error': result.get('error', 'Unknown error')
                })
                print(f"[TASK] Transcript update failed for note {note_id}: {error_message}")
                return {
                    'success': False,
                    'message': error_message,
                    'error': result.get('error', 'Unknown error')
                }
        finally:
            # Clean up the event loop - ONLY if we created a new one
            # DO NOT close the loop if it was an existing one
            if loop and loop is not asyncio.get_event_loop():
                print("[TASK] Cleaning up new event loop we created")
                try:
                    # Only close the loop if we created it
                    if not loop.is_closed():
                        loop.close()
                except Exception as e:
                    print(f"[TASK] Error closing event loop: {str(e)}")
            else:
                print("[TASK] Not closing existing event loop")
            
    except Exception as e:
        error_message = f"Error in transcript update task: {str(e)}"
        self.update_state(state='FAILURE', meta={
            'message': error_message,
            'note_id': note_id
        })
        print(f"[TASK] Exception in transcript update task for note {note_id}: {e}")
        return {
            'success': False,
            'message': error_message,
            'error': str(e)
        } 