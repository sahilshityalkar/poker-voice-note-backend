from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from typing import Optional
import shutil
import os
from datetime import datetime
from pathlib import Path
import uuid
import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from typing import Any, Dict
import asyncio

# Import the GPT analysis functions
from audio_processing.gpt_analysis import generate_summary, generate_insight

# Load environment variables
load_dotenv()

router = APIRouter()

# Get the current file's directory
CURRENT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
# Set upload directory relative to current file
UPLOAD_DIR = CURRENT_DIR / "uploads" / "audio"

print(f"Upload directory path: {UPLOAD_DIR}")

# Create upload directory if it doesn't exist
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Successfully created/verified directory at: {UPLOAD_DIR}")
except Exception as e:
    print(f"Error creating directory: {e}")

# Deepgram setup
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
transcripts_collection = db.transcripts

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/x-m4a": ".m4a"
}

async def transcribe_audio_file(file_path: Path, content_type: str, user_id: str):
    """Transcribe audio file using Deepgram"""
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
                            "user_id": user_id,
                            "summary": None,  # Add summary field initialized to None
                            "insight": None   # Add insight field initialized to None
                        }
                        
                        await transcripts_collection.insert_one(transcript_doc)

                        # Asynchronously generate summary and update the document
                        asyncio.create_task(update_transcript_with_analysis(transcript_doc["transcript_id"], transcript)) # Pass the document id


                        return transcript, confidence
                
                return None, 0

    except Exception as e:
        print(f"Error during transcription: {str(e)}")
        return None, 0

async def update_transcript_with_analysis(transcript_id: str, transcript: str):
    """Updates the transcript document with the generated summary and insight."""
    try:
        summary = await generate_summary(transcript)
        insight = await generate_insight(transcript)

        await transcripts_collection.update_one(
            {"transcript_id": transcript_id},
            {"$set": {"summary": summary, "insight": insight}}
        )
        print(f"Transcript {transcript_id} updated with summary and insight.")

    except Exception as e:
        print(f"Error updating transcript with analysis: {e}")

@router.post("/upload/")
async def upload_audio(
    file: UploadFile = File(...),
    user_id: str = Header(None),
):
    """Endpoint to upload audio files with user_id"""
    try:
        # Verify that the Header parameters are defined.
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Validate file content type
        if file.content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types are: {', '.join(ALLOWED_AUDIO_TYPES.keys())}"
            )

        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = file.filename
        extension = ALLOWED_AUDIO_TYPES[file.content_type]
        new_filename = f"{timestamp}_{original_filename}"
        file_path = UPLOAD_DIR / new_filename

        # Save the file
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as save_error:
            print(f"Error saving file: {save_error}")
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(save_error)}")

        # Verify file was saved
        if not file_path.exists():
            raise HTTPException(status_code=500, detail="File was not saved successfully")

        file_size = os.path.getsize(file_path)

        # Transcribe the audio file
        transcript, confidence = await transcribe_audio_file(
            file_path=file_path,
            content_type=file.content_type,
            user_id=user_id
        )

        return {
            "success": True,
            "filename": new_filename,
            "file_size": file_size,
            "file_path": str(file_path),
            "user_id": user_id,
            "transcript": transcript,
            "confidence": confidence
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error during upload: {str(e)}")
        # Clean up if file was partially uploaded
        if "file_path" in locals() and Path(file_path).exists():
            Path(file_path).unlink()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/")
async def list_audio_files(user_id: str = Header(None)):
    """Endpoint to list all uploaded audio files filtered by user_id"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        if not UPLOAD_DIR.exists():
            return {"success": True, "files": [], "total_files": 0}

        files = []
        for file_path in UPLOAD_DIR.glob("*"):
            if file_path.suffix in ALLOWED_AUDIO_TYPES.values():
                filename = file_path.name
                file_size = os.path.getsize(file_path)
                
                # Get transcript from MongoDB
                transcript_doc = await transcripts_collection.find_one({
                    "filename": filename,
                    "user_id": user_id
                })
                
                file_data = {
                    "filename": filename,
                    "file_size": file_size,
                    "file_path": str(file_path),
                    "user_id": user_id,
                    "transcript": transcript_doc["transcript"] if transcript_doc else None,
                    "summary": transcript_doc.get("summary"),   # Retrieve summary
                    "insight": transcript_doc.get("insight")     # Retrieve insight
                }
                files.append(file_data)

        return {"success": True, "files": files, "total_files": len(files)}
        
    except Exception as e:
        print(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{filename}")
async def delete_audio_file(filename: str):
    """Endpoint to delete a specific audio file and its transcript"""
    try:
        file_path = UPLOAD_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File {filename} not found")

        # Delete the file
        os.remove(file_path)
        
        # Delete associated transcript
        await transcripts_collection.delete_one({"filename": filename})
        
        return {
            "success": True,
            "message": f"File {filename} and its transcript successfully deleted"
        }
    except Exception as e:
        print(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))