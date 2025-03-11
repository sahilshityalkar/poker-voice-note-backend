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
import re
import traceback
from google.cloud import storage
from google.oauth2 import service_account

# Import the GPT analysis functions
from audio_processing.gpt_analysis import process_transcript
from audio_processing.player_notes_api import analyze_players_in_note, get_fresh_connection

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

# GCP Cloud Storage configuration
GCP_BUCKET_NAME = os.environ.get("GCP_BUCKET_NAME", "your-bucket-name")
GCP_CREDENTIALS_PATH = os.environ.get("GCP_CREDENTIALS_PATH", "path/to/your/credentials.json")

# Initialize GCP storage client
def get_storage_client():
    """Initialize and return a GCP storage client."""
    try:
        if os.path.exists(GCP_CREDENTIALS_PATH):
            credentials = service_account.Credentials.from_service_account_file(GCP_CREDENTIALS_PATH)
            return storage.Client(credentials=credentials)
        else:
            # Use default credentials if available
            return storage.Client()
    except Exception as e:
        print(f"[ERROR] Failed to initialize GCP storage client: {e}")
        return None

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
    """Process an audio file, either from a local path or a GCS URI."""
    try:
        # Check if the file_path is a GCS URI
        if isinstance(file_path, str) and file_path.startswith("gs://"):
            # Extract the bucket name and blob name from the GCS URI
            # Format: gs://bucket-name/path/to/file
            parts = file_path[5:].split("/", 1)
            bucket_name = parts[0]
            blob_name = parts[1]
            
            # Get a temporary signed URL for processing
            storage_client = get_storage_client()
            if not storage_client:
                raise Exception("Storage client not available")
                
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            signed_url = blob.generate_signed_url(
                version="v4",
                expiration=3600,  # 1 hour
                method="GET"
            )
            
            # Use the signed URL for transcription
            transcript = await get_transcript_from_deepgram_url(signed_url, "en")
        else:
            # Handle local file (existing behavior)
            if isinstance(file_path, str):
                file_path = Path(file_path)
            transcript = await get_transcript_from_deepgram(file_path, content_type)
        
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            print(f"[USER] User not found with user_id: {user_id}")
            raise HTTPException(status_code=404, detail="User not found")
            
        language = user.get("notes_language", "en")  # Default to English if not set
        print(f"[AUDIO] Processing audio for user {user_id} in language: {language}")
        
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
        
        # Step 2: Process transcript with GPT in user's language (in parallel with player analysis)
        # Create tasks to run in parallel
        from audio_processing.gpt_analysis import process_transcript
        
        # Start GPT transcript analysis task
        transcript_task = process_transcript(transcript, language)
        
        # Step 3: Create note document (without analyzed fields - we'll update it after GPT call)
        note_id = ObjectId()
        base_note_doc = {
            "_id": note_id,
            "user_id": user_id,
            "audioFileUrl": str(file_path),
            "transcript": transcript,
            "language": language,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }
        
        # Insert the note with basic information
        await notes_collection.insert_one(base_note_doc)
        print(f"[DB] Created note with ID: {note_id}")
        
        # Step 4: Start player analysis in parallel with transcript analysis
        # Since player_analysis needs the note_id which we now have
        from audio_processing.player_notes_api import analyze_players_in_note
        player_analysis_task = analyze_players_in_note(str(note_id), user_id, is_update=True)
        
        # Wait for both tasks to complete in parallel
        processed_data, player_analysis_result = await asyncio.gather(
            transcript_task,
            player_analysis_task
        )
        
        # Process transcript results
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
        
        # Update the note with analysis results
        await notes_collection.update_one(
            {"_id": note_id},
            {"$set": {
                "summary": summary,
                "insight": insight,
                "updatedAt": datetime.utcnow()
            }}
        )
        
        # Process player analysis results
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
            "message": "Error processing audio file",
            "summary": "Error processing recording",
            "insight": "The system encountered an error while processing this recording",
            "player_notes": []
        }

@router.post("/upload/")
async def upload_audio(
    file: UploadFile = File(...),
    user_id: str = Header(None)
):
    from tasks.audio_tasks import process_audio_task
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    
    try:
        # Generate a unique filename
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        
        # Create a temporary local file
        temp_file_path = os.path.join(UPLOAD_DIR, unique_filename)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        # Save the file temporarily
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Upload to GCP Cloud Storage
        storage_client = get_storage_client()
        if storage_client:
            try:
                bucket = storage_client.bucket(GCP_BUCKET_NAME)
                blob = bucket.blob(f"audio/{unique_filename}")
                
                blob.upload_from_filename(temp_file_path)
                
                # Generate a signed URL that will be valid for 1 hour
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=3600,  # 1 hour
                    method="GET"
                )
                
                # Remove the temporary file after upload
                os.remove(temp_file_path)
                
                # Use the GCS URI format for the file path
                gcs_uri = f"gs://{GCP_BUCKET_NAME}/audio/{unique_filename}"
                
                # Queue the audio processing task to Celery with the GCS URI
                try:
                    task = process_audio_task.delay(gcs_uri, file.content_type, user_id)
                    
                    return {
                        "success": True,
                        "message": "Audio file uploaded to Cloud Storage. Processing started in background.",
                        "task_id": task.id,
                        "file_id": unique_filename,
                        "gcs_uri": gcs_uri
                    }
                except ImportError as import_error:
                    print(f"[ERROR] Import error in upload_audio: {import_error}")
                    # Fallback to direct processing if Celery task import fails
                    print(f"[UPLOAD] Falling back to direct processing for {gcs_uri}")
                    result = process_audio_task.delay(gcs_uri, file.content_type, user_id)
                    
                    return {
                        "success": True,
                        "message": "Audio processed directly (Celery unavailable)",
                        "data": result,
                        "gcs_uri": gcs_uri
                    }
            except Exception as storage_error:
                print(f"[ERROR] Cloud Storage error: {storage_error}")
                # Fallback to local processing if GCP upload fails
                print(f"[UPLOAD] Falling back to local file processing for {temp_file_path}")
                result = process_audio_task.delay(Path(temp_file_path), file.content_type, user_id)
                
                return {
                    "success": True,
                    "message": "Audio processed locally (Cloud Storage unavailable)",
                    "data": result
                }
        else:
            # No storage client, fallback to local processing
            print(f"[UPLOAD] No GCP client available, using local file: {temp_file_path}")
            result = process_audio_task.delay(Path(temp_file_path), file.content_type, user_id)
            
            return {
                "success": True,
                "message": "Audio processed locally (Cloud Storage not configured)",
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
        player_analysis_result = await analyze_players_in_note(str(note_id), user_id, is_update=True)
        
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

async def process_text_directly(text: str, user_id: str) -> Dict[str, Any]:
    """Process text directly without audio transcription - used by Celery tasks"""
    try:
        if not text or not text.strip():
            return {
                "success": False,
                "error": "Empty text",
                "message": "No text provided for processing",
                "summary": "Empty text input",
                "insight": "The text input was empty",
                "player_notes": []
            }
        
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            return {
                "success": False,
                "error": "User not found",
                "message": f"User with ID {user_id} not found",
                "summary": "Error processing text",
                "insight": "User not found in the system",
                "player_notes": []
            }
            
        # Get user's language preference, default to English if not set
        language = user.get('notes_language', 'en')
        print(f"[TEXT] Using language: {language}")

        # Step 1: Process transcript with GPT in user's language (in parallel with player analysis)
        # Create tasks to run in parallel
        from audio_processing.gpt_analysis import process_transcript
        
        # Start GPT transcript analysis task
        transcript_task = process_transcript(text, language)
        
        # Step 2: Create note document (without analyzed fields - we'll update it after GPT call)
        note_id = ObjectId()
        base_note_doc = {
            "_id": note_id,
            "user_id": user_id,
            "audioFileUrl": None,  # No audio file for text input
            "transcript": text,  # Store original text as transcript
            "language": language,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }
        
        # Insert the note with basic information
        await notes_collection.insert_one(base_note_doc)
        print(f"[TEXT] Created note with ID: {note_id}")
        
        # Step 3: Start player analysis in parallel with transcript analysis
        # Since player_analysis needs the note_id which we now have
        from audio_processing.player_notes_api import analyze_players_in_note
        player_analysis_task = analyze_players_in_note(str(note_id), user_id, is_update=True)
        
        # Wait for both tasks to complete in parallel
        processed_data, player_analysis_result = await asyncio.gather(
            transcript_task,
            player_analysis_task
        )
        
        # Process transcript results
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
        
        # Update the note with analysis results
        await notes_collection.update_one(
            {"_id": note_id},
            {"$set": {
                "summary": summary,
                "insight": insight,
                "updatedAt": datetime.utcnow()
            }}
        )
        
        # Process player analysis results
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
        print(f"[TEXT] Error processing text directly: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Error processing text input",
            "summary": "Error processing text input",
            "insight": "The system encountered an error while analyzing this text",
            "player_notes": []
        }

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
        
        # Queue the text processing task to Celery
        # Import task locally to prevent circular imports
        import sys
        print(f"[DEBUG] Python path: {sys.path}")
        
        try:
            from tasks.text_tasks import process_text_task
            task = process_text_task.delay(text, user_id)
            
            return {
                "success": True,
                "message": "Text processing started in background.",
                "task_id": task.id,
                "text_length": len(text)
            }
        except ImportError as import_error:
            print(f"[ERROR] Import error in process_text_input: {import_error}")
            # Fallback to direct processing if Celery task import fails
            print(f"[TEXT] Falling back to direct processing")
            result = await process_text_directly(text, user_id)
            
            return {
                "success": True,
                "message": "Text processed directly (Celery unavailable)",
                "data": result
            }
            
    except Exception as e:
        print(f"[TEXT] Error processing text input: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

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

async def update_transcript_directly(note_id: str, text: str, user_id: str) -> Dict[str, Any]:
    """Update a note's transcript and reprocess it directly - used by Celery tasks"""
    try:
        # Import the get_fresh_connection function
        from audio_processing.player_notes_api import get_fresh_connection
        
        # Import our completely isolated player analysis function
        from audio_processing.analyze_players_in_note import analyze_players_completely
        
        # Get fresh database connections for this task
        print(f"[UPDATE] Getting fresh database connections for note {note_id}")
        conn = get_fresh_connection()
        notes_coll = conn['notes']
        players_coll = conn['players']
        players_notes_coll = conn['players_notes']
        user_coll = conn['db'].users
        
        if not text or not text.strip():
            return {
                "success": False,
                "error": "Empty text",
                "message": "No text provided for update",
                "summary": "Empty text input",
                "insight": "The text input was empty",
                "player_notes": []
            }
        
        # Validate note_id
        try:
            note_obj_id = ObjectId(note_id)
        except Exception as e:
            print(f"[UPDATE] Invalid note ID format: {e}")
            return {
                "success": False,
                "error": "Invalid note ID",
                "message": f"Invalid note ID format: {note_id}",
                "player_notes": []
            }

        # Find the existing note
        try:
            note = await notes_coll.find_one({"_id": note_obj_id, "user_id": user_id})
            if not note:
                print(f"[UPDATE] Note not found: {note_id} for user {user_id}")
                return {
                    "success": False,
                    "error": "Note not found",
                    "message": "Note not found or you don't have permission to update it",
                    "player_notes": []
                }
        except Exception as e:
            print(f"[UPDATE] Database error finding note: {e}")
            return {
                "success": False,
                "error": "Database error",
                "message": f"Error accessing note: {str(e)}",
                "player_notes": []
            }
            
        print(f"[UPDATE] Updating transcript for note {note_id} from user {user_id}")
        
        # Get user's language preference
        try:
            user = await user_coll.find_one({"user_id": user_id})
            if not user:
                print(f"[UPDATE] User not found: {user_id}")
                return {
                    "success": False,
                    "error": "User not found",
                    "message": f"User with ID {user_id} not found",
                    "player_notes": []
                }
                
            # Get user's language preference, default to English if not set
            language = user.get('notes_language', 'en')
            print(f"[UPDATE] Using language: {language}")
        except Exception as e:
            print(f"[UPDATE] Error getting user language: {e}")
            language = "en" # Default to English on error
            print(f"[UPDATE] Defaulting to language: {language}")

        # CLEANUP STEP - completely handled by analyze_players_completely now
        # This is no longer needed, but we'll keep a log message
        print(f"[UPDATE] Player cleanup will be handled by analyze_players_completely")

        # Step 1: Process transcript with GPT in user's language
        try:
            from audio_processing.gpt_analysis import process_transcript
            print(f"[UPDATE] Starting GPT analysis for transcript")
            processed_data = await process_transcript(text, language)
        except Exception as gpt_ex:
            print(f"[UPDATE] Error in GPT transcript processing: {gpt_ex}")
            processed_data = {
                "summary": f"Error processing updated text in {language}",
                "insight": f"The system encountered an error while analyzing this updated text"
            }
        
        # Step 2: Use our completely isolated player analysis function
        try:
            print(f"[UPDATE] Starting player analysis with isolated function")
            player_analysis_result = await analyze_players_completely(
                note_id=note_id, 
                user_id=user_id, 
                transcript=text, 
                language=language, 
                db_connection=conn
            )
            print(f"[UPDATE] Completed isolated player analysis")
        except Exception as player_ex:
            print(f"[UPDATE] Error in isolated player analysis: {player_ex}")
            traceback.print_exc()
            player_analysis_result = {
                "success": False,
                "message": f"Error analyzing players: {str(player_ex)}",
                "player_notes": []
            }
        
        # Process transcript results
        # Provide default values if processing fails
        if not processed_data:
            processed_data = {
                "summary": f"Error processing updated text in {language}",
                "insight": f"The system encountered an error while analyzing this updated text"
            }
        
        summary = processed_data.get("summary", "")
        insight = processed_data.get("insight", "")
        print(f"[UPDATE] Processing complete. Summary: {summary[:100]}...")

        # Step 3: Update the note document with new data
        try:
            update_data = {
                "transcript": text,  # Store updated text as transcript
                "summary": summary,
                "insight": insight,
                "updatedAt": datetime.utcnow()
            }
            
            await notes_coll.update_one(
                {"_id": note_obj_id},
                {"$set": update_data}
            )
            print(f"[UPDATE] Updated note with ID: {note_id}")
        except Exception as update_ex:
            print(f"[UPDATE] Error updating note document: {update_ex}")
            return {
                "success": False,
                "error": "Database update failed",
                "message": f"Error updating note: {str(update_ex)}",
                "player_notes": []
            }
        
        # Process player analysis results
        if player_analysis_result.get("success", False):
            player_notes = player_analysis_result.get("player_notes", [])
            print(f"[PLAYERS] Successfully analyzed {len(player_notes)} players in updated note {note_id}")
        else:
            print(f"[PLAYERS] Player analysis failed for updated note {note_id}: {player_analysis_result.get('message', 'Unknown error')}")
            # Continue with the update even if player analysis fails, just return an empty array
            player_notes = []
            
            # Still try to create a basic fallback player analysis
            try:
                print(f"[PLAYERS] Attempting basic keyword-based player extraction as fallback")
                # Extract names that look like player names (capitalized words in parentheses)
                potential_players = []
                player_pattern = r'\b([A-Z][a-z]+)(?:\s*\((?:UTG|MP|CO|BTN|SB|BB)\)|\s+\(?\b(?:raised|called|folded|checked|bet|raised to)\b\)?)'
                matches = re.findall(player_pattern, text)
                if matches:
                    # Remove duplicates and keep only unique player names
                    potential_players = list(set(matches))
                    print(f"[PLAYERS] Found {len(potential_players)} potential player names: {', '.join(potential_players)}")
            except Exception as fallback_ex:
                print(f"[PLAYERS] Error in fallback player extraction: {fallback_ex}")
                # Continue without any players

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
        print(f"[UPDATE] Error updating transcript directly: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "message": "Error updating transcript",
            "player_notes": []
        }

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
        
        # Queue the transcript update task to Celery
        # Import task locally to prevent circular imports
        import sys
        print(f"[DEBUG] Python path: {sys.path}")
        
        try:
            from tasks.transcript_update_tasks import update_transcript_task
            task = update_transcript_task.delay(note_id, text, user_id)
            
            return {
                "success": True,
                "message": "Transcript update started in background.",
                "task_id": task.id,
                "note_id": note_id,
                "text_length": len(text)
            }
        except ImportError as import_error:
            print(f"[ERROR] Import error in update_transcript: {import_error}")
            # Fallback to direct processing if Celery task import fails
            print(f"[UPDATE] Falling back to direct processing for note {note_id}")
            result = await update_transcript_directly(note_id, text, user_id)
            
            return {
                "success": True,
                "message": "Transcript updated directly (Celery unavailable)",
                "data": result
            }
            
    except Exception as e:
        print(f"[UPDATE] Error updating transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/task-status/{task_id}")
async def get_task_status(task_id: str):
    """Check the status of an audio processing task"""
    try:
        from celery.result import AsyncResult
        
        # Get task result
        result = AsyncResult(task_id)
        
        # Return status information
        response = {
            "task_id": task_id,
            "status": result.status,
        }
        
        # If task is ready, include result information
        if result.ready():
            if result.successful():
                response["result"] = result.get()
            else:
                response["error"] = str(result.result)
                
        return response
        
    except Exception as e:
        print(f"[ERROR] Error checking task status: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )