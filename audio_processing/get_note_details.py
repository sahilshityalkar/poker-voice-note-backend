# get_transcript_details.py

from fastapi import APIRouter, HTTPException, Header
from typing import Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
transcripts_collection = db.transcripts

@router.get("/transcript/{transcript_id}", response_model=Dict[str, Any])
async def get_transcript_details(transcript_id: str, user_id: str = Header(None)):
    """
    Endpoint to retrieve all details for a specific transcript, given the transcript_id and user_id.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        transcript_doc = await transcripts_collection.find_one(
            {"transcript_id": transcript_id, "user_id": user_id}
        )

        if not transcript_doc:
            raise HTTPException(status_code=404, detail="Transcript not found")

        # Convert ObjectId to string for serialization
        transcript_doc["_id"] = str(transcript_doc["_id"])

        return transcript_doc

    except Exception as e:
        print(f"Error retrieving transcript details: {e}")
        raise HTTPException(status_code=500, detail=str(e))