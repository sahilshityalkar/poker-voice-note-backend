# profile_api.py

from fastapi import APIRouter, HTTPException, Query, Header, status
from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field, validator
from datetime import datetime
from bson import ObjectId
import re
import json

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
user_collection = db.users

# Static OTP (for testing purposes)
STATIC_OTP = "123123"

# Helper class for handling ObjectId serialization
class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(JSONEncoder, self).default(obj)

# Pydantic models for request/response
class UserProfileRead(BaseModel):
    user_id: str = Field(..., description="User ID")
    mobileNumber: str = Field(..., description="Mobile number")
    username: str = Field(..., description="Username")
    profilePic: Optional[str] = Field("", description="Profile picture URL (optional)")
    isVerified: bool = Field(True, description="Mobile verification status")
    app_language: str = Field("en", description="App language")
    notes_language: str = Field("en", description="Notes language")
    createdAt: datetime = Field(..., description="Account creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")
    
    class Config:
        json_encoders = {
            ObjectId: str,
            datetime: lambda dt: dt.isoformat()
        }

class UserProfileUpdate(BaseModel):
    username: Optional[str] = Field(None, description="Username")
    profilePic: Optional[str] = Field(None, description="Profile picture URL")
    app_language: Optional[str] = Field(None, description="App UI language code (e.g., 'en', 'hi', 'fr')")
    notes_language: Optional[str] = Field(None, description="Notes language code (e.g., 'en', 'hi', 'fr')")

    @validator("app_language", "notes_language")
    def validate_language_code(cls, v):
        if v is not None:
            # List of supported language codes (matching frontend)
            supported_languages = [
                "en", "en-US", "en-GB", "en-AU", "en-NZ", "en-IN",
                "es", "es-419", "fr", "fr-CA", "de", "de-CH",
                "zh", "zh-CN", "zh-Hans", "zh-TW", "zh-Hant", "zh-HK",
                "pt", "pt-BR", "pt-PT", "nl", "nl-BE", "ko", "ko-KR",
                "sv", "sv-SE", "th", "th-TH", "bg", "ca", "cs", "da", "da-DK",
                "et", "fi", "el", "hi", "hu", "id", "it", "ja", "lv", "lt",
                "ms", "no", "pl", "ro", "ru", "sk", "tr", "uk", "vi"
            ]
            if v not in supported_languages:
                # Be flexible with language codes in case frontend sends a code not in our list
                base_lang = v.split('-')[0] if '-' in v else v
                if base_lang not in [lang.split('-')[0] for lang in supported_languages]:
                    raise ValueError(f"Unsupported language code: {v}")
        return v

class LanguageUpdate(BaseModel):
    app_language: str = Field(..., description="App language code")
    notes_language: str = Field(..., description="Notes language code")

class ChangePhoneNumberRequest(BaseModel):
    new_mobileNumber: str = Field(..., description="New mobile number")
    otp: str = Field(..., description="OTP to verify the change")

    @validator("new_mobileNumber")
    def phone_number_must_be_valid(cls, v):
        if not re.match(r"^\d{10,15}$", v):
            raise ValueError("Phone number must be 10-15 digits")
        return v

# Helpers for MongoDB
def format_user_for_response(user):
    """Format user document for API response"""
    if not user:
        return None
    
    # Convert _id to string
    if "_id" in user:
        user["_id"] = str(user["_id"])
    
    # Ensure required fields exist
    if "profilePic" not in user:
        user["profilePic"] = ""
    
    if "isVerified" not in user:
        user["isVerified"] = True
    
    # Convert timestamp to datetime for proper serialization
    if "createdAt" in user and isinstance(user["createdAt"], int):
        user["createdAt"] = datetime.fromtimestamp(user["createdAt"] / 1000)
    elif "createdAt" not in user:
        user["createdAt"] = datetime.utcnow()
        
    if "updatedAt" in user and isinstance(user["updatedAt"], int):
        user["updatedAt"] = datetime.fromtimestamp(user["updatedAt"] / 1000)
    elif "updatedAt" not in user:
        user["updatedAt"] = datetime.utcnow()
    
    return user

# API endpoints
@router.get("/profile/", response_model=Dict[str, Any])
async def read_profile(user_id: str = Query(..., description="User ID")):
    """
    Get user profile information.
    
    This endpoint returns the user's profile including username, phone number,
    and language preferences.
    """
    try:
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        formatted_user = format_user_for_response(user)
        return formatted_user
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error retrieving profile: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.put("/profile/", response_model=Dict[str, Any])
async def update_profile(profile: UserProfileUpdate, user_id: str = Query(..., description="User ID")):
    """
    Update user profile information.
    
    This endpoint allows updating username, profile picture, and language preferences.
    """
    try:
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Extract only the fields that were provided (not None)
        update_data = {k: v for k, v in profile.dict().items() if v is not None}
        
        # Update the updatedAt field
        update_data["updatedAt"] = int(datetime.utcnow().timestamp() * 1000)
        
        # Update user document
        await user_collection.update_one(
            {"user_id": user_id},
            {"$set": update_data}
        )
        
        # Fetch updated user
        updated_user = await user_collection.find_one({"user_id": user_id})
        formatted_user = format_user_for_response(updated_user)
        return formatted_user
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error updating profile: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.put("/profile/languages/", response_model=Dict[str, Any])
async def update_languages(language_update: LanguageUpdate, user_id: str = Query(..., description="User ID")):
    """
    Update user language preferences.
    
    This endpoint allows updating app and notes language preferences.
    """
    try:
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Update language fields and updatedAt
        update_data = {
            "app_language": language_update.app_language,
            "notes_language": language_update.notes_language,
            "updatedAt": int(datetime.utcnow().timestamp() * 1000)
        }
        
        # Update user document
        await user_collection.update_one(
            {"user_id": user_id},
            {"$set": update_data}
        )
        
        # Fetch updated user
        updated_user = await user_collection.find_one({"user_id": user_id})
        formatted_user = format_user_for_response(updated_user)
        return formatted_user
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error updating languages: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/profile/change-phone-number/", response_model=Dict[str, Any])
async def change_phone_number(
    change_request: ChangePhoneNumberRequest, 
    user_id: str = Query(..., description="User ID")
):
    """
    Change user's phone number.
    
    This endpoint verifies the OTP and updates the user's phone number.
    """
    try:
        # Check if OTP is valid
        if change_request.otp != STATIC_OTP:
            raise HTTPException(status_code=400, detail="Invalid OTP")
        
        # Find user
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Check if new number is already registered to another user
        existing_user = await user_collection.find_one({
            "mobileNumber": change_request.new_mobileNumber,
            "user_id": {"$ne": user_id}  # Not the current user
        })
        if existing_user:
            raise HTTPException(status_code=400, detail="Phone number already registered to another user")
        
        # Update the phone number and updatedAt
        await user_collection.update_one(
            {"user_id": user_id},
            {"$set": {
                "mobileNumber": change_request.new_mobileNumber,
                "updatedAt": int(datetime.utcnow().timestamp() * 1000)
            }}
        )
        
        # Fetch updated user
        updated_user = await user_collection.find_one({"user_id": user_id})
        formatted_user = format_user_for_response(updated_user)
        return formatted_user
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error changing phone number: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.delete("/profile/", response_model=Dict[str, str])
async def delete_profile(user_id: str = Query(..., description="User ID")):
    """
    Delete user account.
    
    This endpoint permanently removes the user's account from the system.
    """
    try:
        # Find user to confirm it exists
        user = await user_collection.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete user
        result = await user_collection.delete_one({"user_id": user_id})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=500, detail="Failed to delete user")
        
        return {"message": "User account deleted successfully"}
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")