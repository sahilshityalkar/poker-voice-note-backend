# get_note_details.py

from fastapi import APIRouter, HTTPException, Header
from typing import Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId
import os

# Load environment variables
load_dotenv()

router = APIRouter(tags=["notes"])

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
notes_collection = db.notes

def serialize_object_id(obj):
    """Helper function to serialize ObjectId to string."""
    if isinstance(obj, ObjectId):
        return str(obj)
    return obj

@router.get("/note/{note_id}", response_model=Dict[str, Any])
async def get_note_by_id(note_id: str, user_id: str = Header(None)):
    """
    Endpoint to retrieve all details for a specific note, given the note_id and user_id.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        try:
            note_object_id = ObjectId(note_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid note ID format")

        note_doc = await notes_collection.find_one(
            {"_id": note_object_id, "user_id": user_id}
        )

        if not note_doc:
            raise HTTPException(status_code=404, detail="Note not found")

        # Convert ObjectId to string for serialization
        note_doc["_id"] = str(note_doc["_id"])

        return note_doc

    except Exception as e:
        print(f"Error retrieving note details: {e}")
        raise HTTPException(status_code=500, detail=str(e))