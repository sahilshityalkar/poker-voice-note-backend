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
    """Celery task to update a note's transcript and reprocess all data"""
    
    print(f"[TASK] Starting transcript update task for note: {note_id}")
    
    # Update task state to STARTED
    self.update_state(state='STARTED', meta={
        'message': f'Processing transcript update for note {note_id}',
        'note_id': note_id,
        'text_length': len(text),
        'progress': 0
    })
    
    try:
        # Create a completely isolated event loop and process
        result = execute_in_isolated_process(note_id, text, user_id)
        
        # Process the result
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
    except Exception as e:
        error_message = f"Error in transcript update task: {str(e)}"
        self.update_state(state='FAILURE', meta={
            'message': error_message,
            'note_id': note_id
        })
        print(f"[TASK] Exception in transcript update task for note {note_id}: {e}")
        traceback.print_exc()
        return {
            'success': False,
            'message': error_message,
            'error': str(e)
        }

def execute_in_isolated_process(note_id: str, text: str, user_id: str) -> Dict[str, Any]:
    """Execute the update in a completely isolated process"""
    
    # Import here to prevent circular imports
    from database import get_database_connection
    from audio_processing.analyze_players_in_note import analyze_players_completely
    from audio_processing.gpt_analysis import process_transcript
    
    # Create a completely fresh event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        print(f"[TASK] Created fresh event loop for note {note_id}")
        
        async def isolated_process():
            try:
                # Get a fresh database connection with the current event loop
                db_conn = get_database_connection()
                
                # Extract collections
                db = db_conn.pokernotes
                notes_coll = db.notes
                players_coll = db.players
                players_notes_coll = db.players_notes
                users_coll = db.users
                
                print(f"[TASK] Got fresh database connections for note {note_id}")
                print(f"[TASK] Database name: {db.name}, Collections available: notes, players, players_notes, users")
                
                # Basic validation
                if not text or not text.strip():
                    return {
                        "success": False,
                        "error": "Empty text",
                        "message": "No text provided for update",
                        "player_notes": []
                    }
                
                # Validate note_id
                try:
                    note_obj_id = ObjectId(note_id)
                except Exception as e:
                    print(f"[TASK] Invalid note ID format: {e}")
                    return {
                        "success": False,
                        "error": "Invalid note ID",
                        "message": f"Invalid note ID format: {note_id}",
                        "player_notes": []
                    }
                
                # Find the note
                note = await notes_coll.find_one({"_id": note_obj_id, "user_id": user_id})
                if not note:
                    print(f"[TASK] Note not found: {note_id}")
                    return {
                        "success": False,
                        "error": "Note not found",
                        "message": "Note not found or you don't have permission to update it",
                        "player_notes": []
                    }
                
                # Get user language
                user = await users_coll.find_one({"user_id": user_id})
                language = user.get("notes_language", "en") if user else "en"
                print(f"[TASK] Using language {language} for note {note_id}")
                
                # Process transcript with GPT
                print(f"[TASK] Starting GPT analysis for note {note_id}")
                try:
                    processed_data = await process_transcript(text, language)
                except Exception as gpt_ex:
                    print(f"[TASK] Error in GPT processing: {gpt_ex}")
                    processed_data = {
                        "summary": f"Error processing text in {language}",
                        "insight": "Error during analysis"
                    }
                
                # Extract summary and insight
                summary = processed_data.get("summary", "")
                insight = processed_data.get("insight", "")
                
                # Update the note document
                await notes_coll.update_one(
                    {"_id": note_obj_id},
                    {"$set": {
                        "transcript": text,
                        "summary": summary,
                        "insight": insight,
                        "updatedAt": datetime.utcnow()
                    }}
                )
                print(f"[TASK] Updated note {note_id} with new transcript and analysis")
                
                # Use our completely isolated player analysis function
                print(f"[TASK] Starting isolated player analysis for note {note_id}")
                conn_dict = {
                    'db': db,
                    'players': players_coll,
                    'players_notes': players_notes_coll,
                    'notes': notes_coll
                }
                
                player_result = await analyze_players_completely(
                    note_id=note_id,
                    user_id=user_id,
                    transcript=text,
                    language=language,
                    db_connection=conn_dict
                )
                print(f"[TASK] Completed isolated player analysis for note {note_id}")
                
                player_notes = player_result.get("player_notes", [])
                
                # Return the result
                return {
                    "success": True,
                    "noteId": note_id,
                    "transcript": text,
                    "summary": summary,
                    "insight": insight,
                    "language": language,
                    "player_notes": player_notes
                }
                
            except Exception as e:
                print(f"[TASK] Error in isolated process: {e}")
                traceback.print_exc()
                return {
                    "success": False,
                    "error": str(e),
                    "message": f"Error in update process: {str(e)}",
                    "player_notes": []
                }
        
        # Run the coroutine and get the result
        result = loop.run_until_complete(isolated_process())
        return result
        
    finally:
        # Always clean up the event loop
        try:
            # Cancel any pending tasks
            pending_tasks = asyncio.all_tasks(loop)
            if pending_tasks:
                loop.run_until_complete(asyncio.gather(*pending_tasks, return_exceptions=True))
            
            # Close the loop
            loop.close()
            print(f"[TASK] Closed isolated event loop")
        except Exception as e:
            print(f"[TASK] Error cleaning up event loop: {e}") 