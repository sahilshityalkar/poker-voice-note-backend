from fastapi import APIRouter, HTTPException, Header
from typing import Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

router = APIRouter(tags=["player-analysis"])

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
player_analysis_collection = db.player_analysis
players_collection = db.players

def serialize_object_id(obj):
    """Helper function to serialize ObjectId to string."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()  # Convert datetime objects to ISO format
    return obj

@router.get("/latest-analysis/{player_id}", response_model=Dict[str, Any])
async def get_latest_player_analysis(player_id: str, user_id: str = Header(None)):
    """
    Get the most recent analysis for a specific player.
    
    Args:
        player_id: The ID of the player
        user_id: The ID of the user (from request header)
        
    Returns:
        The most recent player analysis document
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Convert string ID to ObjectId
        try:
            player_object_id = ObjectId(player_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid player ID format")

        # Check if player exists and belongs to this user
        player = await players_collection.find_one({"_id": player_object_id, "user_id": user_id})
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        # Get the latest analysis for this player
        latest_analysis = await player_analysis_collection.find_one(
            {"player_id": player_object_id, "user_id": user_id},
            sort=[("createdAt", -1)]  # Sort by createdAt in descending order (newest first)
        )
        
        if not latest_analysis:
            raise HTTPException(status_code=404, detail="No analysis found for this player")
        
        # Serialize ObjectIds to strings
        analysis_serialized = {k: serialize_object_id(v) for k, v in latest_analysis.items()}
        
        # Add player name for convenience
        analysis_serialized["player_name"] = player.get("name", "Unknown Player")
        
        return analysis_serialized

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving latest player analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/analysis-history/{player_id}", response_model=Dict[str, Any])
async def get_player_analysis_history(player_id: str, user_id: str = Header(None)):
    """
    Get the complete history of analyses for a specific player.
    
    Args:
        player_id: The ID of the player
        user_id: The ID of the user (from request header)
        
    Returns:
        Player info and a list of all analysis documents for this player, sorted by date (newest first)
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Convert string ID to ObjectId
        try:
            player_object_id = ObjectId(player_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid player ID format")

        # Check if player exists and belongs to this user
        player = await players_collection.find_one({"_id": player_object_id, "user_id": user_id})
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        # Serialize player data
        player_serialized = {
            "player_id": str(player["_id"]),
            "name": player.get("name", "Unknown Player"),
            "players_notes_count": player.get("players_notes_count", 0),
            "createdAt": serialize_object_id(player.get("createdAt")),
            "updatedAt": serialize_object_id(player.get("updatedAt"))
        }

        # Get all analyses for this player, sorted by date
        analyses = []
        async for analysis in player_analysis_collection.find(
            {"player_id": player_object_id, "user_id": user_id}
        ).sort("createdAt", -1):  # Sort by createdAt in descending order (newest first)
            # Serialize ObjectIds to strings
            analysis_serialized = {k: serialize_object_id(v) for k, v in analysis.items()}
            analyses.append(analysis_serialized)
        
        # Return player info and analyses
        return {
            "player": player_serialized,
            "analyses": analyses
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving player analysis history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
