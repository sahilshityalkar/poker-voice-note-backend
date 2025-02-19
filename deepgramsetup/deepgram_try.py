from fastapi import APIRouter
import aiohttp
import os
from pathlib import Path
from dotenv import load_dotenv
import json
from motor.motor_asyncio import AsyncIOMotorClient
import uuid
from datetime import datetime

# Load environment variables
load_dotenv()

router = APIRouter()

# Constants
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
transcripts_collection = db.transcripts

@router.get("/transcribe-recording/")
async def transcribe_recording():
    """Transcribe the M4A recording file"""
    try:
        # Get file path for the M4A file
        file_path = Path(__file__).parent.parent / "uploads" / "audio" / "Recording.m4a"
        print(f"\nAttempting to process: {file_path}")
        print(f"File exists: {file_path.exists()}")
        
        if not file_path.exists():
            return {"success": False, "error": "File not found"}

        # Read file
        with open(file_path, 'rb') as audio_file:
            audio_content = audio_file.read()
            print(f"Successfully read {len(audio_content)} bytes")

        # Minimal headers
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "audio/x-m4a"
        }

        # No additional parameters for base tier
        print(f"\nSending request to Deepgram:")
        print(f"URL: {DEEPGRAM_URL}")
        print(f"Headers: {json.dumps({k: v[:10] + '...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DEEPGRAM_URL,
                data=audio_content,
                headers=headers,
                timeout=180
            ) as response:
                print(f"\nResponse status: {response.status}")
                
                text = await response.text()
                print(f"\nRaw response text: {text[:500]}...")
                
                result = json.loads(text)
                print(f"Full response: {json.dumps(result, indent=2)}")
                
                if response.status == 200 and 'results' in result:
                    transcript = result['results']['channels'][0]['alternatives'][0]['transcript']
                    confidence = result['results']['channels'][0]['alternatives'][0].get('confidence', 0)
                    
                    # Save to MongoDB if we got a transcript
                    if transcript:
                        transcript_doc = {
                            "transcript_id": str(uuid.uuid4()),
                            "filename": file_path.name,
                            "created_at": datetime.utcnow(),
                            "transcript": transcript,
                            "room_id": "test_room_id",
                            "user_id": "test_user_id"
                        }
                        
                        await transcripts_collection.insert_one(transcript_doc)
                        print(f"Saved transcript to MongoDB")
                    
                    return {
                        "success": True,
                        "transcript": transcript,
                        "confidence": confidence,
                        "metadata": result.get('metadata', {}),
                        "saved_to_db": bool(transcript)
                    }
                
                return {
                    "success": False,
                    "error": "No transcript found in response",
                    "raw_response": result
                }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@router.get("/test-simple/")
async def test_simple():
    """Test with Deepgram's sample URL - most basic test"""
    try:
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "url": "https://static.deepgram.com/examples/Bueller-Life-moves-pretty-fast.wav"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPGRAM_URL, json=data, headers=headers) as response:
                print(f"\nResponse status: {response.status}")
                result = await response.json()
                print(f"Response: {json.dumps(result, indent=2)}")
                return {
                    "success": True,
                    "response": result
                }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {"success": False, "error": str(e)}