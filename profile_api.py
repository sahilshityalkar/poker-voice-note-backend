# profile_api.py

from fastapi import APIRouter, HTTPException, Header, status
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from datetime import datetime

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
user_collection = db.users  # Changed collection name to 'users'

# Pydantic model for reading user profile (includes created_at)
class UserProfileRead(BaseModel):
    username: str
    phone_number: str
    created_at: datetime

# Pydantic model for updating user profile (excludes created_at)
class UserProfileUpdate(BaseModel):
    username: str
    phone_number: str


@router.get("/profile/", response_model=UserProfileRead)
async def read_profile(user_id: str = Header(None)):
    """
    Endpoint to retrieve a user profile. Requires user_id in the header.
    """
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User ID is required in the header")

    user_profile = await user_collection.find_one({"user_id": user_id})
    if not user_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    return UserProfileRead(**user_profile)


@router.put("/profile/", response_model=UserProfileRead)
async def update_profile(profile: UserProfileUpdate, user_id: str = Header(None)):
    """
    Endpoint to update a user profile. Requires user_id in the header.
    """
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User ID is required in the header")

    existing_user = await user_collection.find_one({"user_id": user_id})
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    profile_data = profile.model_dump()
    update_result = await user_collection.update_one(
        {"user_id": user_id}, {"$set": profile_data}
    )
    if update_result.modified_count == 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user profile")

    updated_profile = await user_collection.find_one({"user_id": user_id})
    return UserProfileRead(**updated_profile)


@router.delete("/profile/", response_model=Dict[str, str])
async def delete_profile(user_id: str = Header(None)):
    """
    Endpoint to delete a user profile. Requires user_id in the header.
    Returns a success message upon successful deletion.
    """
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User ID is required in the header")

    delete_result = await user_collection.delete_one({"user_id": user_id})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")
    return {"message": "User profile successfully deleted"} # Added success message