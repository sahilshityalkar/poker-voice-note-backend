from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from typing import Optional, Dict, Any, List
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
from audio_processing.gpt_analysis import generate_summary, generate_insight
from audio_processing.player_notes_api import analyze_players_in_note

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
players_collection = db.players
players_notes_collection = db.players_notes

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/x-m4a": ".m4a"
}

async def create_or_update_player(user_id: str, player_name: str) -> Optional[ObjectId]:
    """Create or update player record with simplified fields"""
    try:
        if not player_name:
            print(f"[PLAYER] Skipping player without name")
            return None
            
        # Clean up player name - remove extra spaces, capitalize properly
        player_name = player_name.strip()
        
        # Skip if the name is too short or not valid
        if not player_name or len(player_name) < 2:
            print(f"[PLAYER] Skipping invalid player name: '{player_name}'")
            return None
            
        # Skip common non-player words that might be misidentified
        non_player_words = ["player", "user", "button", "small", "big", "blind", "utg", "dealer"]
        if player_name.lower() in non_player_words:
            print(f"[PLAYER] Skipping common non-player word: '{player_name}'")
            return None
            
        # Capitalize the name
        player_name = player_name.capitalize()
        
        print(f"[PLAYER] Processing player: {player_name}")
        
        # Check if player exists for this user
        existing_player = await players_collection.find_one({
            "user_id": user_id,
            "name": player_name
        })

        if existing_player:
            print(f"[PLAYER] Updating existing player: {player_name} with ID: {existing_player['_id']}")
            # Only update timestamp
            await players_collection.update_one(
                {"_id": existing_player["_id"]},
                {
                    "$set": {"updatedAt": datetime.utcnow()}
                }
            )
            return existing_player["_id"]
        else:
            print(f"[PLAYER] Creating new player: {player_name}")
            # Create new player with simplified structure
            new_player = {
                "user_id": user_id,
                "name": player_name,
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            result = await players_collection.insert_one(new_player)
            print(f"[PLAYER] Created new player with ID: {result.inserted_id}")
            return result.inserted_id

    except Exception as e:
        print(f"[PLAYER] Error in create_or_update_player: {e}")
        return None

async def get_transcript_from_deepgram(file_path: Path, content_type: str) -> str:
    """Get transcript from Deepgram"""
    try:
        print(f"[TRANSCRIPT] Starting Deepgram transcription for {file_path}")
        
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
                    print(f"[TRANSCRIPT] Deepgram transcription failed: {result}")
                    raise HTTPException(status_code=500, detail="Transcription failed")

                transcript = result['results']['channels'][0]['alternatives'][0]['transcript']
                print(f"[TRANSCRIPT] Deepgram transcription successful: {transcript[:100]}...")
                return transcript
                
    except Exception as e:
        print(f"[TRANSCRIPT] Error in Deepgram transcription: {e}")
        raise

async def process_audio_file(file_path: Path, content_type: str, user_id: str) -> Dict[str, Any]:
    """Process audio file to get transcript, summary, and insight"""
    try:
        # Step 1: Get transcript from Deepgram
        transcript = await get_transcript_from_deepgram(file_path, content_type)
        
        # Step 2: Generate summary and insight using GPT
        print(f"[GPT] Generating summary for transcript...")
        summary = await generate_summary(transcript)
        print(f"[GPT] Summary generated: {summary[:100]}...")
        
        print(f"[GPT] Generating insights for transcript...")
        insight = await generate_insight(transcript)
        print(f"[GPT] Insights generated: {insight[:100]}...")
        
        # Step 3: Create note document
        note_id = ObjectId()
        note_doc = {
            "_id": note_id,
            "user_id": user_id,
            "audioFileUrl": str(file_path),
            "transcriptFromDeepgram": transcript,
            "summaryFromGPT": summary,
            "insightFromGPT": insight,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }
        
        # Insert the note
        await notes_collection.insert_one(note_doc)
        print(f"[DB] Created note with ID: {note_id}")
        
        # Step 4: Trigger player analysis in background (non-blocking)
        asyncio.create_task(analyze_players_in_note(str(note_id), user_id))
        print(f"[ANALYSIS] Started player analysis for note: {note_id}")
        
        return {
            "success": True,
            "noteId": str(note_id),
            "transcript": transcript,
            "summary": summary,
            "insight": insight
        }
        
    except Exception as e:
        print(f"[ERROR] Error processing audio file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload/")
async def upload_audio(
    file: UploadFile = File(...),
    user_id: str = Header(None)
):
    """Upload audio file and process it"""
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="User ID is required"
        )

    # Check if content type is allowed
    content_type = file.content_type
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type}. Supported types: {', '.join(ALLOWED_AUDIO_TYPES.keys())}"
        )

    try:
        print(f"[UPLOAD] Received audio file: {file.filename} from user: {user_id}")
        
        # Generate a unique filename based on timestamp and random ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_id = uuid.uuid4().hex[:8]
        file_extension = ALLOWED_AUDIO_TYPES[content_type]
        filename = f"{timestamp}_{random_id}{file_extension}"
        
        # Create the full path
        file_path = UPLOAD_DIR / filename
        
        # Write the file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        print(f"[UPLOAD] File saved to {file_path}")
            
        # Process the audio file
        result = await process_audio_file(file_path, content_type, user_id)
        
        return {
            "success": True,
            "message": "Audio processed successfully",
            "data": result
        }
            
    except Exception as e:
        print(f"[ERROR] Error uploading audio: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )