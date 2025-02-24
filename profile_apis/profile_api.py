# profile_api.py

from fastapi import APIRouter, HTTPException, Query, status
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
user_collection = db.users

# Pydantic models
class UserProfileRead(BaseModel):
    user_id: UUID = Field(..., description="User ID")
    mobileNumber: str = Field(..., description="Mobile number")
    username: str = Field(..., description="Username")
    profilePic: Optional[str] = Field("", description="Profile picture URL (optional)")
    isVerified: bool = Field(..., description="Mobile verification status")
    createdAt: datetime = Field(..., description="Account creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")


class UserProfileUpdate(BaseModel):
    username: Optional[str] = Field(None, description="Username")
    profilePic: Optional[str] = Field(None, description="Profile picture URL")


@router.get("/profile/", response_model=UserProfileRead)
async def read_profile(user_id: UUID = Query(..., description="User ID from storage")):
    """
    Endpoint to retrieve a user profile. Requires user_id as a query parameter.
    """
    user_profile = await user_collection.find_one({"user_id": str(user_id)}) # Convert UUID to string
    if not user_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    return UserProfileRead(**user_profile)


@router.put("/profile/", response_model=UserProfileRead)
async def update_profile(
    profile: UserProfileUpdate,
    user_id: UUID = Query(..., description="User ID from storage")
):
    """
    Endpoint to update a user profile. Requires user_id as a query parameter.
    Only allows updating username and profilePic.
    """

    existing_user = await user_collection.find_one({"user_id": str(user_id)}) # Convert UUID to string
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    profile_data = profile.model_dump(exclude_unset=True)  # Only include updated fields

    # Update the 'updatedAt' field
    profile_data["updatedAt"] = datetime.utcnow()

    update_result = await user_collection.update_one(
        {"user_id": str(user_id)}, {"$set": profile_data} # Convert UUID to string
    )

    if update_result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user profile"
        )

    updated_profile = await user_collection.find_one({"user_id": str(user_id)}) # Convert UUID to string
    return UserProfileRead(**updated_profile)


@router.delete("/profile/", response_model=Dict[str, str])
async def delete_profile(user_id: UUID = Query(..., description="User ID from storage")):
    """
    Endpoint to delete a user profile. Requires user_id as a query parameter.
    Returns a success message upon successful deletion.
    """
    delete_result = await user_collection.delete_one({"user_id": str(user_id)}) # Convert UUID to string
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")
    return {"message": "User profile successfully deleted"}