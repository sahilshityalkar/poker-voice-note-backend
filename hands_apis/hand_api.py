from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from typing import List, Dict, Any, Optional
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
hands_collection = db.hands

# Pydantic models
class PlayerInHand(BaseModel):
    playerId: str = Field(..., description="Player ID")
    name: str = Field(..., description="Player name")
    position: str = Field(..., description="Player position")
    won: bool = Field(..., description="Whether the player won the hand")

    class Config:
        json_encoders = {
            ObjectId: str  # Convert ObjectId to string
        }


class Hand(BaseModel):
    id: str = Field(..., alias="_id", description="Hand ID")  # Use 'id' but map it to '_id'
    user_id: str = Field(..., description="User ID")
    noteId: str = Field(..., description="Note ID")
    myPosition: str = Field(..., description="My position")
    iWon: bool = Field(..., description="I won or not")
    potSize: Optional[float] = Field(None, description="Pot Size")
    date: datetime = Field(..., description="Date of hand")
    createdAt: datetime = Field(..., description="Creation timestamp")
    updatedAt: datetime = Field(..., description="Update timestamp")
    players: List[PlayerInHand] = Field(..., description="List of players in hand")

    class Config:
        json_encoders = {
            ObjectId: str  # Convert ObjectId to string
        }


@router.get("/hands/{user_id}", response_model=List[Hand])
async def get_hands_by_user_id(user_id: UUID):
    """
    Endpoint to retrieve hands associated with a specific user_id.
    Returns a list of hands that match the provided user_id.
    """
    try:
        # Fetch hands with matching user_id
        hands = await hands_collection.find({"user_id": str(user_id)}).to_list(length=None)

        if not hands:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No hands found for user_id: {user_id}"
            )

        # Convert ObjectId to string for each hand and its nested objects
        for hand in hands:
            if "_id" in hand and isinstance(hand["_id"], ObjectId):
                hand["_id"] = str(hand["_id"])
            if "noteId" in hand and isinstance(hand["noteId"], ObjectId):
                hand["noteId"] = str(hand["noteId"])

            for player in hand.get("players", []):
                if "playerId" in player and isinstance(player["playerId"], ObjectId):
                    player["playerId"] = str(player["playerId"])

        return hands

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch hands: {str(e)}"
        )


@router.get("/hand/{hand_id}/{user_id}", response_model=Hand)
async def get_hand_by_id(hand_id: str, user_id: UUID):
    """
    Endpoint to retrieve a specific hand by hand_id and user_id.
    Returns the hand that matches the provided hand_id and user_id.
    """
    try:
        # Fetch the hand with matching hand_id and user_id
        hand = await hands_collection.find_one({"_id": ObjectId(hand_id), "user_id": str(user_id)})

        if not hand:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No hand found with hand_id: {hand_id} and user_id: {user_id}"
            )

        # Convert ObjectId to string for the hand and its nested objects
        if "_id" in hand and isinstance(hand["_id"], ObjectId):
            hand["_id"] = str(hand["_id"])
        if "noteId" in hand and isinstance(hand["noteId"], ObjectId):
            hand["noteId"] = str(hand["noteId"])

        for player in hand.get("players", []):
            if "playerId" in player and isinstance(player["playerId"], ObjectId):
                player["playerId"] = str(player["playerId"])

        return Hand(**hand)  # Create a Hand object for the response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch hand: {str(e)}"
        )