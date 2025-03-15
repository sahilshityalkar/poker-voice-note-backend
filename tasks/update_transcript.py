import datetime
import os
import asyncio
from audio_processing.gpt_analysis import process_transcript
from audio_processing.player_notes_api import analyze_players_in_note
from cel_main import app
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
notes_collection = db.notes

# Try to import nest_asyncio, critical for proper event loop handling
try:
    import nest_asyncio
    nest_asyncio.apply()
    print("[CELERY] Successfully initialized nest_asyncio for transcript updates")
except ImportError:
    print("[CELERY] WARNING: nest_asyncio not available. Event loop issues may occur!")

@app.task(bind=True)
def handle_update_transcript(self, text: str, language: str, note_id: str, user_id: str):
    """
    Synchronous Celery task that handles transcript updates in an isolated event loop.
    
    Args:
        text: Updated transcript text
        language: User's preferred language for analysis
        note_id: ID of the note to update
        user_id: User's ID
        
    Returns:
        Dictionary with the results of the update
    """
    # Create new event loop for this task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Run async operations within the new event loop
        result = loop.run_until_complete(_process_update_async(text, language, note_id, user_id))
        return result
    except Exception as e:
        print(f"[UPDATE] Error in handle_update_transcript: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Error updating transcript: {str(e)}",
            "noteId": note_id,
            "player_notes": []
        }
    finally:
        # Always clean up the event loop
        try:
            # Cancel pending tasks
            pending = asyncio.all_tasks(loop=loop)
            for task in pending:
                task.cancel()
            
            # Run loop until tasks are cancelled
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            
            # Close the loop
            loop.close()
        except Exception as close_error:
            print(f"[UPDATE] Warning: Error while closing event loop: {close_error}")

async def _process_update_async(text: str, language: str, note_id: str, user_id: str):
    """Async function to process transcript updates"""
    try:
        processed_data = await process_transcript(text, language)
            
        # Provide default values if processing fails
        if not processed_data:
            processed_data = {
                "summary": f"Error processing updated text in {language}",
                "insight": f"The system encountered an error while analyzing this updated text"
            }
            
        summary = processed_data.get("summary", "")
        insight = processed_data.get("insight", "")
        print(f"[UPDATE] Processing complete. Summary: {summary[:100]}...")

        # Update the note document
        update_data = {
            "transcript": text,  # Make sure to update the transcript too
            "summary": summary,
            "insight": insight,
            "updatedAt": datetime.datetime.utcnow()  # Fixed: use datetime.datetime
        }
        
        await notes_collection.update_one(
            {"_id": ObjectId(note_id)},
            {"$set": update_data}
        )
        print(f"[UPDATE] Updated note with ID: {note_id}")

        # Re-analyze players in the note
        print(f"[PLAYERS] Starting player analysis for updated note {note_id}")
        player_analysis_result = await analyze_players_in_note(note_id, user_id)
        
        # Check if player analysis was successful
        if player_analysis_result.get("success", False):
            player_notes = player_analysis_result.get("player_notes", [])
            print(f"[PLAYERS] Successfully analyzed {len(player_notes)} players in updated note {note_id}")
        else:
            print(f"[PLAYERS] Player analysis failed for updated note {note_id}: {player_analysis_result.get('message', 'Unknown error')}")
            player_notes = []

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
        print(f"[UPDATE] Error in _process_update_async: {e}")
        raise