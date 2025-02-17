# audio_api.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import Optional
import shutil
import os
from datetime import datetime
from pathlib import Path

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

ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/x-m4a": ".m4a"
}

@router.post("/upload/")
async def upload_audio(
    file: UploadFile = File(...),
    description: Optional[str] = None
):
    """Endpoint to upload audio files"""
    try:
        # Debug prints
        print(f"Starting file upload process...")
        print(f"Current working directory: {os.getcwd()}")
        print(f"Upload directory: {UPLOAD_DIR}")
        print(f"Received file: {file.filename}")
        print(f"File content type: {file.content_type}")

        # Check if upload directory exists
        if not UPLOAD_DIR.exists():
            print("Upload directory doesn't exist, creating it...")
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

        print(f"Attempting to save file to: {file_path}")

        # Save the file
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            print(f"File saved successfully at: {file_path}")
        except Exception as save_error:
            print(f"Error saving file: {save_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save file: {str(save_error)}"
            )

        # Verify file was saved
        if file_path.exists():
            file_size = os.path.getsize(file_path)
            print(f"File verification successful. Size: {file_size} bytes")
        else:
            raise HTTPException(
                status_code=500,
                detail="File was not saved successfully"
            )

        return {
            "success": True,
            "filename": new_filename,
            "file_size": file_size,
            "file_path": str(file_path)
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error during upload: {str(e)}")
        # Clean up if file was partially uploaded
        if 'file_path' in locals() and Path(file_path).exists():
            Path(file_path).unlink()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/")
async def list_audio_files():
    """Endpoint to list all uploaded audio files"""
    try:
        if not UPLOAD_DIR.exists():
            return {
                "success": True,
                "files": [],
                "total_files": 0
            }

        files = []
        for file_path in UPLOAD_DIR.glob("*"):
            if file_path.suffix in ALLOWED_AUDIO_TYPES.values():
                files.append({
                    "filename": file_path.name,
                    "file_size": os.path.getsize(file_path),
                    "file_path": str(file_path)
                })
        return {
            "success": True,
            "files": files,
            "total_files": len(files)
        }
    except Exception as e:
        print(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{filename}")
async def delete_audio_file(filename: str):
    """Endpoint to delete a specific audio file"""
    try:
        file_path = UPLOAD_DIR / filename
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File {filename} not found"
            )
        
        os.remove(file_path)
        return {
            "success": True,
            "message": f"File {filename} successfully deleted"
        }
    except Exception as e:
        print(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail=str(e))