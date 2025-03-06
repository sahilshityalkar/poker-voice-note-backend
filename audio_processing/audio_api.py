from fastapi import APIRouter, UploadFile, File, HTTPException, Header, Body, Form, Request
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
import json
from pydantic import BaseModel, Field

# Import the GPT analysis functions
from audio_processing.gpt_analysis import process_transcript
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
user_collection = db.users  # Add user collection

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

async def get_transcript_from_deepgram(file_path: Path, content_type: str, language: str = "en") -> str:
    """Get transcript from Deepgram using user's preferred language"""
    try:
        print(f"[TRANSCRIPT] Starting Deepgram transcription for {file_path} in language: {language}")
        
        # Read the audio file
        with open(file_path, 'rb') as audio_file:
            audio_content = audio_file.read()

        # Headers for Deepgram
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": content_type
        }

        # Build the URL with query parameters for language and model
        url = f"{DEEPGRAM_URL}?model=nova-2&language={language}"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
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
    """Process audio file to get transcript, summary, and insight in user's language"""
    try:
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            print(f"[USER] User not found with user_id: {user_id}")
            raise HTTPException(status_code=404, detail="User not found")
            
        language = user.get("notes_language", "en")  # Default to English if not set
        print(f"[AUDIO] Processing audio for user {user_id} in language: {language}")
        
        # Step 1: Get transcript from Deepgram with user's language preference
        transcript = await get_transcript_from_deepgram(file_path, content_type, language)
        
        # Check if transcript is empty and terminate early if it is
        if not transcript or transcript.strip() == "":
            print(f"[AUDIO] Empty transcript received, terminating processing")
            return {
                "success": False,
                "error": "Empty transcript",
                "message": "No speech detected in the audio file",
                "summary": "Empty recording",
                "insight": "The audio file did not contain any detectable speech",
                "player_notes": []
            }
        
        # Step 2: Process transcript with GPT in user's language
        print(f"[GPT] Processing transcript in {language}...")
        processed_data = await process_transcript(transcript, language)
        
        # Our improved process_transcript always returns a dictionary, never None
        # But as a safety check, provide default values if somehow it's None
        if not processed_data:
            processed_data = {
                "summary": f"Error processing audio in {language}",
                "insight": f"The system encountered an error while analyzing this recording"
            }
            
        summary = processed_data.get("summary", "")
        insight = processed_data.get("insight", "")
        print(f"[GPT] Processing complete. Summary: {summary[:100]}...")
        
        # Step 3: Create note document (without players field - we'll handle players separately)
        note_id = ObjectId()
        note_doc = {
            "_id": note_id,
            "user_id": user_id,
            "audioFileUrl": str(file_path),
            "transcript": transcript,
            "summary": summary,
            "insight": insight,
            "language": language,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }
        
        # Insert the note
        await notes_collection.insert_one(note_doc)
        print(f"[DB] Created note with ID: {note_id}")
        
        # Step 4: Analyze players in the note asynchronously
        print(f"[PLAYERS] Starting player analysis for note {note_id}")
        player_analysis_result = await analyze_players_in_note(str(note_id), user_id)
        
        # Check if player analysis was successful
        if player_analysis_result.get("success", False):
            player_notes = player_analysis_result.get("player_notes", [])
            print(f"[PLAYERS] Successfully analyzed {len(player_notes)} players in note {note_id}")
        else:
            print(f"[PLAYERS] Player analysis failed for note {note_id}: {player_analysis_result.get('message', 'Unknown error')}")
            player_notes = []
        
        return {
            "success": True,
            "noteId": str(note_id),
            "transcript": transcript,
            "summary": summary,
            "insight": insight,
            "language": language,
            "player_notes": player_notes
        }
        
    except Exception as e:
        print(f"[AUDIO] Error processing audio file: {e}")
        return {
            "success": False,
            "error": str(e),
            "summary": "Error processing audio",
            "insight": "The system encountered an error while analyzing this recording",
            "player_notes": []
        }

@router.post("/upload/")
async def upload_audio(
    file: UploadFile = File(...),
    user_id: str = Header(None)
):
    """Upload audio file and process it"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
            
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        language = user.get("notes_language", "en")  # Default to English if not set
        print(f"[UPLOAD] Processing upload for user {user_id} in language: {language}")
        
        # Create upload directory if it doesn't exist
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        # Generate a unique filename
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        # Save the file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Process the audio file
        result = await process_audio_file(Path(file_path), file.content_type, user_id)
        
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

async def transcribe_audio_file(audio_url: str, user_id: str) -> Dict[str, Any]:
    """Transcribe audio file and create note with player data"""
    try:
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        notes_language = user.get("notes_language", "en")  # Default to English if not set
        
        print(f"[TRANSCRIBE] Processing audio for user {user_id} in language: {notes_language}")
        
        # Get transcript from Deepgram with user's language preference
        transcript = await get_transcript_from_deepgram_url(audio_url, notes_language)
        if not transcript:
            raise HTTPException(status_code=500, detail="Failed to get transcript from Deepgram")
            
        # Check if transcript is empty (just whitespace) and terminate early if it is
        if transcript.strip() == "":
            print(f"[TRANSCRIBE] Empty transcript received, terminating processing")
            return {
                "success": False,
                "error": "Empty transcript",
                "message": "No speech detected in the audio file",
                "summary": "Empty recording",
                "insight": "The audio file did not contain any detectable speech",
                "player_notes": []
            }
            
        print(f"[TRANSCRIBE] Got transcript in {notes_language}")
        
        # Process transcript with GPT in user's language
        processed_data = await process_transcript(transcript, notes_language)
        
        # Our improved process_transcript always returns a dictionary, never None
        # But as a safety check, provide default values if somehow it's None
        if not processed_data:
            processed_data = {
                "summary": f"Error processing audio in {notes_language}",
                "insight": f"The system encountered an error while analyzing this recording"
            }
            
        print(f"[TRANSCRIBE] Processed transcript data: {processed_data}")
        
        # Create note document (without players field - we'll handle players separately)
        note_id = ObjectId()
        note_doc = {
            "_id": note_id,
            "user_id": user_id,
            "audioFileUrl": audio_url,
            "transcript": transcript,
            "summary": processed_data.get("summary", ""),
            "insight": processed_data.get("insight", ""),
            "language": notes_language,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }
        
        # Insert the note
        result = await notes_collection.insert_one(note_doc)
        print(f"[TRANSCRIBE] Created note with ID: {note_id}")
        
        # Analyze players in the note asynchronously
        print(f"[PLAYERS] Starting player analysis for note {note_id}")
        player_analysis_result = await analyze_players_in_note(str(note_id), user_id)
        
        # Check if player analysis was successful
        if player_analysis_result.get("success", False):
            player_notes = player_analysis_result.get("player_notes", [])
            print(f"[PLAYERS] Successfully analyzed {len(player_notes)} players in note {note_id}")
        else:
            print(f"[PLAYERS] Player analysis failed for note {note_id}: {player_analysis_result.get('message', 'Unknown error')}")
            player_notes = []
        
        return {
            "success": True,
            "note_id": str(note_id),
            "transcript": transcript,
            "summary": processed_data.get("summary", ""),
            "insight": processed_data.get("insight", ""),
            "language": notes_language,
            "player_notes": player_notes
        }
        
    except Exception as e:
        print(f"[TRANSCRIBE] Error in transcribe_audio_file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-text/")
async def process_text_input(
    text: str = Body(..., media_type="text/plain"),
    user_id: str = Header(None)
):
    """Endpoint to process text input directly without audio transcription"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")

        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="Text input is required")

        print(f"[TEXT] Processing text input from user {user_id}")
        
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            print(f"[USER] User not found with user_id: {user_id}")
            raise HTTPException(status_code=404, detail="User not found")
            
        # Get user's language preference, default to English if not set
        language = user.get('notes_language', 'en')
        print(f"[TEXT] Using language: {language}")

        # Process text with GPT
        processed_data = await process_transcript(text, language)
        
        # Our improved process_transcript always returns a dictionary, never None
        # But as a safety check, provide default values if somehow it's None
        if not processed_data:
            processed_data = {
                "summary": f"Error processing text in {language}",
                "insight": f"The system encountered an error while analyzing this text"
            }
        
        summary = processed_data.get("summary", "")
        insight = processed_data.get("insight", "")
        print(f"[TEXT] Processing complete. Summary: {summary[:100]}...")

        # Create note document (without players field - we'll handle players separately)
        note_id = ObjectId()
        note_doc = {
            "_id": note_id,
            "user_id": user_id,
            "audioFileUrl": None,  # No audio file for text input
            "transcript": text,  # Store original text as transcript
            "summary": summary,
            "insight": insight,
            "language": language,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }

        # Insert the note
        await notes_collection.insert_one(note_doc)
        print(f"[TEXT] Created note with ID: {note_id}")

        # Analyze players in the note asynchronously
        print(f"[PLAYERS] Starting player analysis for note {note_id}")
        player_analysis_result = await analyze_players_in_note(str(note_id), user_id)
        
        # Check if player analysis was successful
        if player_analysis_result.get("success", False):
            player_notes = player_analysis_result.get("player_notes", [])
            print(f"[PLAYERS] Successfully analyzed {len(player_notes)} players in note {note_id}")
        else:
            print(f"[PLAYERS] Player analysis failed for note {note_id}: {player_analysis_result.get('message', 'Unknown error')}")
            player_notes = []

        return {
            "success": True,
            "noteId": str(note_id),
            "transcript": text,
            "summary": summary,
            "insight": insight,
            "language": language,
            "player_notes": player_notes
        }

    except Exception as e:
        print(f"[TEXT] Error processing text input: {e}")
        return {
            "success": False,
            "error": str(e),
            "summary": "Error processing text input",
            "insight": "The system encountered an error while analyzing this text",
            "player_notes": []
        }

async def get_transcript_from_deepgram_url(audio_url: str, language: str = "en") -> str:
    """Get transcript from Deepgram using an audio URL and user's preferred language"""
    try:
        print(f"[TRANSCRIPT] Starting Deepgram transcription for URL: {audio_url} in language: {language}")
        
        # Headers for Deepgram
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "application/json"
        }

        # Build the URL with query parameters for language and model
        url = f"{DEEPGRAM_URL}?model=nova-2&language={language}"
        
        # Prepare the request body with the audio URL
        request_body = {
            "url": audio_url
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=request_body,
                headers=headers,
                timeout=180
            ) as response:
                result = await response.json()

                if response.status != 200 or 'results' not in result:
                    print(f"[TRANSCRIPT] Deepgram transcription failed: {result}")
                    raise HTTPException(status_code=500, detail="Transcription failed")

                transcript = result['results']['channels'][0]['alternatives'][0]['transcript']
                print(f"[TRANSCRIPT] Got transcript in {language}: {transcript[:100]}...")
                return transcript

    except Exception as e:
        print(f"[TRANSCRIPT] Error getting transcript from Deepgram: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting transcript: {str(e)}")

@router.put("/notes/{note_id}/update-transcript")
async def update_transcript(
    note_id: str,
    text: str = Body(..., media_type="text/plain"),
    user_id: str = Header(None)
):
    """Endpoint to update transcript of an existing note and reprocess all data"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")

        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="Updated transcript text is required")

        # Validate note_id
        try:
            note_obj_id = ObjectId(note_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid note ID format")

        # Find the existing note
        note = await notes_collection.find_one({"_id": note_obj_id, "user_id": user_id})
        if not note:
            raise HTTPException(status_code=404, detail="Note not found or you don't have permission to update it")

        print(f"[UPDATE] Updating transcript for note {note_id} from user {user_id}")
        
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            print(f"[USER] User not found with user_id: {user_id}")
            raise HTTPException(status_code=404, detail="User not found")
            
        # Get user's language preference, default to English if not set
        language = user.get('notes_language', 'en')
        print(f"[UPDATE] Using language: {language}")

        # Process updated text with GPT
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
            "transcript": text,  # Store updated text as transcript
            "summary": summary,
            "insight": insight,
            "updatedAt": datetime.utcnow()
        }
        
        await notes_collection.update_one(
            {"_id": note_obj_id},
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
    except HTTPException:
        raise
    except Exception as e:
        print(f"[UPDATE] Error updating transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))