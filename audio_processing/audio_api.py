from fastapi import APIRouter, UploadFile, File, HTTPException, Header, Body
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

async def create_or_update_player(user_id: str, player_data: Dict, hand_id: ObjectId, note_id: ObjectId) -> Optional[ObjectId]:
    """Create or update player record"""
    try:
        # Validate player data
        if not player_data.get("name"):
            print(f"Skipping player without name: {player_data}")
            return None
            
        # Convert name to proper format
        player_name = player_data["name"].strip().capitalize()
        
        print(f"Processing player: {player_name}, Position: {player_data.get('position')}, Won: {player_data.get('won')}")
        
        # Check if player exists for this user
        existing_player = await players_collection.find_one({
            "user_id": user_id,
            "name": player_name
        })

        hand_reference = {
            "handId": hand_id,
            "noteId": note_id,
            "position": player_data.get("position", "Unknown"),
            "won": bool(player_data.get("won", False)),
            "date": datetime.utcnow()
        }

        if existing_player:
            print(f"Updating existing player: {player_name}")
            # Update existing player
            await players_collection.update_one(
                {"_id": existing_player["_id"]},
                {
                    "$inc": {
                        "totalHands": 1,
                        "totalWins": 1 if player_data.get("won", False) else 0
                    },
                    "$push": {"handReferences": hand_reference},
                    "$set": {"updatedAt": datetime.utcnow()}
                }
            )
            return existing_player["_id"]
        else:
            print(f"Creating new player: {player_name}")
            # Create new player
            new_player = {
                "user_id": user_id,
                "name": player_name,
                "totalHands": 1,
                "totalWins": 1 if player_data.get("won", False) else 0,
                "handReferences": [hand_reference],
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            result = await players_collection.insert_one(new_player)
            return result.inserted_id

    except Exception as e:
        print(f"Error in create_or_update_player: {e}")
        return None

async def process_players(user_id: str, players: List[Dict], hand_id: ObjectId, note_id: ObjectId) -> List[Dict]:
    """Process all players in the hand data"""
    player_ids = []
    
    if not players:
        print("No players to process")
        return player_ids
        
    print(f"Processing {len(players)} players")
    
    for player in players:
        if not player.get("name"):
            print("Skipping player without name")
            continue
            
        try:
            player_id = await create_or_update_player(
                user_id,
                player,
                hand_id,
                note_id
            )
            
            if player_id:
                player_ids.append({
                    "playerId": player_id,
                    "name": player["name"],
                    "position": player.get("position", "Unknown"),
                    "won": bool(player.get("won", False))
                })
        except Exception as e:
            print(f"Error processing player {player.get('name')}: {e}")
    
    print(f"Successfully processed {len(player_ids)} players")
    return player_ids

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
                print(f"Transcript received: {transcript}")

                # Process transcript with GPT
                processed_data = await process_transcript(transcript)
                print(f"Processed data received from GPT analysis")

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
                print(f"Hand data for database: {hand_data}")
                
                hand_doc = {
                    "user_id": user_id,
                    "noteId": note_id,
                    "myPosition": hand_data.get("myPosition", "Unknown"),
                    "iWon": bool(hand_data.get("iWon", False)),
                    "potSize": hand_data.get("potSize"),
                    "date": datetime.utcnow(),
                    "createdAt": datetime.utcnow(),
                    "updatedAt": datetime.utcnow()
                }

                # Insert hand document
                hand_result = await hands_collection.insert_one(hand_doc)
                hand_id = hand_result.inserted_id
                print(f"Created hand with ID: {hand_id}")

                # Update note with hand reference
                note_doc["handId"] = hand_id
                await notes_collection.insert_one(note_doc)
                print(f"Created note with ID: {note_id}")

                # Process players
                print(f"Processing players from hand data: {hand_data.get('players', [])}")
                player_ids = await process_players(
                    user_id,
                    hand_data.get("players", []),
                    hand_id,
                    note_id
                )

                # Update hand with player references
                if player_ids:
                    print(f"Updating hand with {len(player_ids)} player references")
                    await hands_collection.update_one(
                        {"_id": hand_id},
                        {"$set": {"players": player_ids}}
                    )
                else:
                    print("No players to update in hand document")

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

@router.put("/note/{note_id}/transcript")
async def update_transcript(
    note_id: str,
    edited_transcript: str = Body(...),  # The edited transcript from the user
    user_id: str = Header(None)
):
    """
    Endpoint to update the transcript of a note and re-run the analysis pipeline.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")

        # Convert note_id to ObjectId
        try:
            note_object_id = ObjectId(note_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid note ID format")

        # Verify note exists and belongs to user
        note = await notes_collection.find_one({"_id": note_object_id, "user_id": user_id})
        if not note:
            raise HTTPException(status_code=404, detail="Note not found or unauthorized")

        # Get hand ID
        hand_id = note.get("handId")
        if not hand_id:
            raise HTTPException(status_code=400, detail="Hand ID not found associated with the note.")

        # Run GPT-based analysis on the edited transcript
        processed_data = await process_transcript(edited_transcript)
        print(f"Re-processed data for transcript update: {processed_data}")

        # Update the note document
        await notes_collection.update_one(
            {"_id": note_object_id},
            {
                "$set": {
                    "transcriptFromDeepgram": edited_transcript,
                    "summaryFromGPT": processed_data["summary"],
                    "insightFromGPT": processed_data["insight"],
                    "updatedAt": datetime.utcnow()
                }
            }
        )

        # Update hand data
        hand_data = processed_data["hand_data"]
        await hands_collection.update_one(
            {"_id": ObjectId(hand_id)},
            {
                "$set": {
                    "myPosition": hand_data.get("myPosition", "Unknown"),
                    "iWon": bool(hand_data.get("iWon", False)),
                    "potSize": hand_data.get("potSize"),
                    "updatedAt": datetime.utcnow()
                }
            }
        )

        # Clear existing player references in the hand document
        await hands_collection.update_one(
            {"_id": ObjectId(hand_id)},
            {"$set": {"players": []}}
        )

        # Process players and create/update them, linking them to the hand
        player_ids = await process_players(
            user_id,
            hand_data.get("players", []),
            ObjectId(hand_id),
            note_object_id
        )

        # Update hand with new player references
        await hands_collection.update_one(
            {"_id": ObjectId(hand_id)},
            {"$set": {"players": player_ids}}
        )

        return {"message": "Transcript updated and analysis re-run successfully."}

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error updating transcript and re-running analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-text/")
async def process_text_input(
    text_input: str = Body(..., description="The poker hand text to analyze"),
    user_id: str = Header(None)
):
    """Endpoint to process text input directly without audio transcription"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")

        if not text_input or not text_input.strip():
            raise HTTPException(status_code=400, detail="Text input is required")

        print(f"Processing text input: {text_input}")

        # Process text with GPT
        processed_data = await process_transcript(text_input)
        print(f"Processed data received from GPT analysis")

        # Create note document
        note_id = ObjectId()
        note_doc = {
            "_id": note_id,
            "user_id": user_id,
            "audioFileUrl": None,  # No audio file for text input
            "transcriptFromDeepgram": text_input,  # Store original text as transcript
            "summaryFromGPT": processed_data["summary"],
            "insightFromGPT": processed_data["insight"],
            "date": datetime.utcnow(),
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }

        # Create hand document
        hand_data = processed_data["hand_data"]
        print(f"Hand data for database: {hand_data}")
        
        hand_doc = {
            "user_id": user_id,
            "noteId": note_id,
            "myPosition": hand_data.get("myPosition", "Unknown"),
            "iWon": bool(hand_data.get("iWon", False)),
            "potSize": hand_data.get("potSize"),
            "date": datetime.utcnow(),
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }

        # Insert hand document
        hand_result = await hands_collection.insert_one(hand_doc)
        hand_id = hand_result.inserted_id
        print(f"Created hand with ID: {hand_id}")

        # Update note with hand reference
        note_doc["handId"] = hand_id
        await notes_collection.insert_one(note_doc)
        print(f"Created note with ID: {note_id}")

        # Process players
        print(f"Processing players from hand data: {hand_data.get('players', [])}")
        player_ids = await process_players(
            user_id,
            hand_data.get("players", []),
            hand_id,
            note_id
        )

        # Update hand with player references
        if player_ids:
            print(f"Updating hand with {len(player_ids)} player references")
            await hands_collection.update_one(
                {"_id": hand_id},
                {"$set": {"players": player_ids}}
            )
        else:
            print("No players to update in hand document")

        return {
            "noteId": str(note_id),
            "handId": str(hand_id),
            "transcript": text_input,
            "summary": processed_data["summary"],
            "insight": processed_data["insight"]
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error processing text input: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))