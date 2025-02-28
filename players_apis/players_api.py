from bson import ObjectId
from fastapi import APIRouter, HTTPException, status, Query
from typing import List
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
players_collection = db.players

# Pydantic models
class HandReference(BaseModel):
    handId: str = Field(..., description="Hand ID")
    noteId: str = Field(..., description="Note ID")
    position: str = Field(..., description="Player position")
    won: bool = Field(..., description="Whether the player won")
    date: datetime = Field(..., description="Hand date")

    class Config:
        json_encoders = {
            ObjectId: str  # Convert ObjectId to string
        }

class Player(BaseModel):
    player_id: str = Field(..., alias="_id", description="Player ID")  # Add player_id field
    user_id: str = Field(..., description="User ID")
    name: str = Field(..., description="Player name")
    totalHands: int = Field(..., description="Total number of hands played")
    totalWins: int = Field(..., description="Total number of wins")
    handReferences: List[HandReference] = Field(..., description="List of hand references")
    createdAt: datetime = Field(..., description="Account creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")

    class Config:
        json_encoders = {
            ObjectId: str  # Convert ObjectId to string
        }
        populate_by_name = True #allows alias to work

@router.get("/players/{user_id}", response_model=List[Player])
async def get_players_by_user_id(user_id: UUID):
    """
    Endpoint to retrieve players associated with a specific user_id.
    Returns a list of players that match the provided user_id.
    """
    try:
        # Fetch players with matching user_id
        players = await players_collection.find({"user_id": str(user_id)}).to_list(length=None)
        
        if not players:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No players found for current user"
            )

        # Convert ObjectId to string for each player
        for player in players:
            # Convert top-level ObjectId
            if "_id" in player and isinstance(player["_id"], ObjectId):
                player["_id"] = str(player["_id"])

            # Convert ObjectIds in handReferences
            for hand_ref in player.get("handReferences", []):
                if "handId" in hand_ref and isinstance(hand_ref["handId"], ObjectId):
                    hand_ref["handId"] = str(hand_ref["handId"])
                if "noteId" in hand_ref and isinstance(hand_ref["noteId"], ObjectId):
                    hand_ref["noteId"] = str(hand_ref["noteId"])
        return players

    except HTTPException:  # Re-raise HTTPExceptions (like 404)
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch players: {str(e)}"
        )