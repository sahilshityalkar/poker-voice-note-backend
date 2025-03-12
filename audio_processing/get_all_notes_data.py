from fastapi import APIRouter, HTTPException, Header
from typing import Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId
import os
from datetime import datetime

# Load environment variables
load_dotenv()

router = APIRouter(tags=["notes"])

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
notes_collection = db.notes
players_notes_collection = db.players_notes

def serialize_object_id(obj):
    """Helper function to serialize ObjectId to string."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()  # Convert datetime objects to ISO format
    return obj

@router.get("/note-detailed/{note_id}", response_model=Dict[str, Any])
async def get_note_details(note_id: str, user_id: str = Header(None)):
    """
    Get detailed information about a specific note
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Convert string ID to ObjectId
        try:
            note_object_id = ObjectId(note_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid note ID format")

        # Find the note document
        note = await notes_collection.find_one({"_id": note_object_id, "user_id": user_id})
        
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
            
        # Serialize ObjectIds to strings
        note_serialized = {k: serialize_object_id(v) for k, v in note.items()}
        
        return note_serialized

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving note details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/notes", response_model=List[Dict[str, Any]])
async def get_all_notes_by_user(user_id: str = Header(None)):
    """
    Get all notes associated with a specific user ID.
    Returns a list of note objects sorted by date (newest first).
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        notes = []
        # Sort by createdAt in descending order (newest first)
        async for note in notes_collection.find({"user_id": user_id}).sort("createdAt", -1):
            # Serialize ObjectIds to strings
            note = {k: serialize_object_id(v) for k, v in note.items()}
            notes.append(note)

        return notes

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/notes-with-players", response_model=List[Dict[str, Any]])
async def get_all_notes_with_players(user_id: str = Header(None)):
    """
    Get all notes with their associated player notes for a specific user.
    Returns a list where each item contains a note and its associated player notes.
    Notes are sorted by date (newest first).
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        result = []
        
        # First, get all notes for this user sorted by createdAt in descending order (newest first)
        async for note in notes_collection.find({"user_id": user_id}).sort("createdAt", -1):
            # Serialize note ObjectIds to strings
            note_serialized = {k: serialize_object_id(v) for k, v in note.items()}
            
            # Get all player notes for this note
            player_notes = []
            note_id = note["_id"]
            
            # Use string representation of note_id for query
            note_id_str = str(note_id)
            async for player_note in players_notes_collection.find({"note_id": note_id_str, "user_id": user_id}):
                # Serialize player note ObjectIds to strings
                player_note_serialized = {k: serialize_object_id(v) for k, v in player_note.items()}
                player_notes.append(player_note_serialized)
            
            # Add this note and its player notes to the result
            result.append({
                "note": note_serialized,
                "player_notes": player_notes
            })
        
        return result

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving notes with player data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/latest-note", response_model=Dict[str, Any])
async def get_latest_note_with_players(user_id: str = Header(None)):
    """
    Get the most recent note with its associated player notes for a specific user.
    Returns a single note object with its player notes.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Get the most recent note for this user
        note = await notes_collection.find_one(
            {"user_id": user_id},
            sort=[("createdAt", -1)]  # Sort by createdAt in descending order (newest first)
        )
        
        if not note:
            raise HTTPException(status_code=404, detail="No notes found for this user")
            
        # Serialize note ObjectIds to strings
        note_serialized = {k: serialize_object_id(v) for k, v in note.items()}
        
        # Get all player notes for this note
        player_notes = []
        note_id = note["_id"]
        
        # Use string representation of note_id for query
        note_id_str = str(note_id)
        async for player_note in players_notes_collection.find({"note_id": note_id_str, "user_id": user_id}):
            # Serialize player note ObjectIds to strings
            player_note_serialized = {k: serialize_object_id(v) for k, v in player_note.items()}
            player_notes.append(player_note_serialized)
        
        # Return this note and its player notes
        return {
            "note": note_serialized,
            "player_notes": player_notes
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving latest note with player data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/note-with-players/{note_id}", response_model=Dict[str, Any])
async def get_note_with_player_notes(note_id: str, user_id: str = Header(None)):
    """
    Get a specific note and all player notes associated with it.
    Returns the note document and an array of player notes.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Convert string ID to ObjectId
        try:
            note_object_id = ObjectId(note_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid note ID format")

        # Find the note document
        note = await notes_collection.find_one({"_id": note_object_id, "user_id": user_id})
        
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
            
        # Serialize note ObjectIds to strings
        note_serialized = {k: serialize_object_id(v) for k, v in note.items()}
        
        # Find all player notes associated with this note
        player_notes = []
        # Use string representation of note_id for query
        async for player_note in players_notes_collection.find({"note_id": note_id, "user_id": user_id}):
            # Serialize player note ObjectIds to strings
            player_note_serialized = {k: serialize_object_id(v) for k, v in player_note.items()}
            player_notes.append(player_note_serialized)
        
        # Return combined data
        return {
            "note": note_serialized,
            "player_notes": player_notes
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving note with player notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))