from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from typing import Optional, Dict, Any
import shutil
import os
from datetime import datetime
from pathlib import Path
import uuid
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import asyncio
from bson import ObjectId

# Import the GPT analysis functions
from audio_processing.gpt_analysis import process_transcript

# Load environment variables
load_dotenv()

router = APIRouter()

# Set upload directory
UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads" / "audio"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Deepgram setup
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
notes_collection = db.notes
hands_collection = db.hands
players_collection = db.players

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/x-m4a": ".m4a"
}

async def create_or_update_player(user_id: str, player_data: Dict, hand_id: ObjectId, note_id: ObjectId) -> ObjectId:
    """Create or update player record"""
    try:
        # Check if player exists for this user
        existing_player = await players_collection.find_one({
            "user_id": user_id,
            "name": player_data["name"]
        })

        hand_reference = {
            "handId": hand_id,
            "noteId": note_id,
            "position": player_data.get("position"),
            "won": player_data["won"],
            "date": datetime.utcnow()
        }

        if existing_player:
            # Update existing player
            await players_collection.update_one(
                {"_id": existing_player["_id"]},
                {
                    "$inc": {
                        "totalHands": 1,
                        "totalWins": 1 if player_data["won"] else 0
                    },
                    "$push": {"handReferences": hand_reference},
                    "$set": {"updatedAt": datetime.utcnow()}
                }
            )
            return existing_player["_id"]
        else:
            # Create new player
            new_player = {
                "user_id": user_id,
                "name": player_data["name"],
                "totalHands": 1,
                "totalWins": 1 if player_data["won"] else 0,
                "handReferences": [hand_reference],
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            result = await players_collection.insert_one(new_player)
            return result.inserted_id

    except Exception as e:
        print(f"Error in create_or_update_player: {e}")
        raise

async def transcribe_audio_file(file_path: Path, content_type: str, user_id: str) -> Dict[str, Any]:
    """Transcribe audio file using Deepgram and process with GPT"""
    try:
        # Read the audio file
        with open(file_path, 'rb') as audio_file:
            audio_content = audio_file.read()

        # Headers for Deepgram
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": content_type
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DEEPGRAM_URL,
                data=audio_content,
                headers=headers,
                timeout=180
            ) as response:
                result = await response.json()
                
                if response.status != 200 or 'results' not in result:
                    raise HTTPException(status_code=500, detail="Transcription failed")

                transcript = result['results']['channels'][0]['alternatives'][0]['transcript']
                
                # Process transcript with GPT
                processed_data = await process_transcript(transcript)
                
                # Create note document
                note_id = ObjectId()
                note_doc = {
                    "_id": note_id,
                    "user_id": user_id,
                    "audioFileUrl": str(file_path),
                    "transcriptFromDeepgram": transcript,
                    "summaryFromGPT": processed_data["summary"],
                    "insightFromGPT": processed_data["insight"],
                    "date": datetime.utcnow(),
                    "createdAt": datetime.utcnow(),
                    "updatedAt": datetime.utcnow()
                }

                # Create hand document
                hand_data = processed_data["hand_data"]
                hand_doc = {
                    "user_id": user_id,
                    "noteId": note_id,
                    "myPosition": hand_data["myPosition"],
                    "iWon": hand_data["iWon"],
                    "potSize": hand_data.get("potSize"),
                    "date": datetime.utcnow(),
                    "createdAt": datetime.utcnow(),
                    "updatedAt": datetime.utcnow()
                }

                # Insert hand document
                hand_result = await hands_collection.insert_one(hand_doc)
                hand_id = hand_result.inserted_id

                # Update note with hand reference
                note_doc["handId"] = hand_id
                await notes_collection.insert_one(note_doc)

                # Process players
                player_ids = []
                for player in hand_data["players"]:
                    player_id = await create_or_update_player(
                        user_id,
                        player,
                        hand_id,
                        note_id
                    )
                    player_ids.append({
                        "playerId": player_id,
                        "name": player["name"],
                        "position": player.get("position"),
                        "won": player["won"]
                    })

                # Update hand with player references
                await hands_collection.update_one(
                    {"_id": hand_id},
                    {"$set": {"players": player_ids}}
                )

                return {
                    "noteId": str(note_id),
                    "handId": str(hand_id),
                    "transcript": transcript,
                    "summary": processed_data["summary"],
                    "insight": processed_data["insight"]
                }

    except Exception as e:
        print(f"Error during transcription and processing: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload/")
async def upload_audio(
    file: UploadFile = File(...),
    user_id: str = Header(None)
):
    """Endpoint to upload and process audio files"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")

        if file.content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types are: {', '.join(ALLOWED_AUDIO_TYPES.keys())}"
            )

        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = ALLOWED_AUDIO_TYPES[file.content_type]
        filename = f"{timestamp}_{uuid.uuid4()}{extension}"
        file_path = UPLOAD_DIR / filename

        # Save the file
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as save_error:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(save_error)}")

        # Process the audio file
        result = await transcribe_audio_file(
            file_path=file_path,
            content_type=file.content_type,
            user_id=user_id
        )

        return {
            "success": True,
            "filename": filename,
            "file_size": os.path.getsize(file_path),
            **result
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error during upload: {str(e)}")
        if "file_path" in locals() and Path(file_path).exists():
            Path(file_path).unlink()
        raise HTTPException(status_code=500, detail=str(e))