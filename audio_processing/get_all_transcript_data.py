# get_all_transcript_data.py

from fastapi import APIRouter, HTTPException, Header
from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
from bson import ObjectId # Import ObjectId

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
transcripts_collection = db.transcripts


@router.get("/transcripts/", response_model=List[Dict[str, Any]])
async def get_all_transcripts_by_user(user_id: str = Header(None)):
    """
    Endpoint to retrieve all transcript data for a given user ID.
    Returns a list of transcript documents, including transcript, summary, and insight.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        transcripts = []
        async for transcript_doc in transcripts_collection.find({"user_id": user_id}):
            # Convert ObjectId to string
            transcript_doc["_id"] = str(transcript_doc["_id"]) # Added: Convert ObjectId to string
            transcripts.append(transcript_doc)

        return transcripts

    except Exception as e:
        print(f"Error retrieving transcripts: {e}")
        raise HTTPException(status_code=500, detail=str(e))