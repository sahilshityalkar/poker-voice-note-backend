import datetime
import os
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

# TODO: error handling
@app.task
async def handle_update_transcript(text: str, language: str, note_id, user_id: str ):
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
        "summary": summary,
        "insight": insight,
        "updatedAt": datetime.utcnow()
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