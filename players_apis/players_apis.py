# players_apis.py
from fastapi import APIRouter, HTTPException, Header
from typing import Dict, Any, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# Create a Pydantic model for the player name update
class PlayerNameUpdate(BaseModel):
    name: str

router = APIRouter(tags=["players"])

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
players_collection = db.players
players_notes_collection = db.players_notes
player_analysis_collection = db.player_analysis

def serialize_object_id(obj):
    """Helper function to serialize ObjectId to string."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()  # Convert datetime objects to ISO format
    return obj

@router.get("/players-with-analysis", response_model=List[Dict[str, Any]])
async def get_players_with_last_analysis(user_id: str = Header(None)):
    """
    Get all players associated with a user, along with their most recent analysis.
    Players are sorted by last update date (newest first).
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Get all players for this user, sorted by updatedAt in descending order
        players = await players_collection.find(
            {"user_id": user_id}
        ).sort("updatedAt", -1).to_list(length=1000)
        
        result = []
        for player in players:
            # Serialize player ObjectIds to strings
            player_serialized = {k: serialize_object_id(v) for k, v in player.items()}
            
            # Add notes count to the response
            notes_count = len(player.get("notes", []))
            player_serialized["notes_count"] = notes_count
            
            # Get the most recent analysis for this player
            player_id = player["_id"]
            # Query using the ObjectId directly for player_analysis_collection
            recent_analysis = await player_analysis_collection.find_one(
                {"player_id": player_id, "user_id": user_id},
                sort=[("createdAt", -1)]  # Sort by createdAt in descending order
            )
            
            if recent_analysis:
                # Serialize analysis ObjectIds to strings
                analysis_serialized = {k: serialize_object_id(v) for k, v in recent_analysis.items()}
                player_serialized["latest_analysis"] = analysis_serialized
            else:
                player_serialized["latest_analysis"] = None
            
            result.append(player_serialized)
        
        return result

    except Exception as e:
        print(f"Error retrieving players with analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/player-details/{player_id}", response_model=Dict[str, Any])
async def get_player_details_with_notes(player_id: str, user_id: str = Header(None)):
    """
    Get detailed information about a specific player, including:
    - Player data from players collection
    - Player analysis from player_analysis collection
    - All player notes from players_notes collection
    
    Notes are sorted by date (newest first).
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Convert string ID to ObjectId
        try:
            player_object_id = ObjectId(player_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid player ID format")

        # Get the player document
        player = await players_collection.find_one({"_id": player_object_id, "user_id": user_id})
        
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
            
        # Serialize player ObjectIds to strings
        player_serialized = {k: serialize_object_id(v) for k, v in player.items()}
        
        # Get the most recent analysis for this player
        # Query using the ObjectId directly for player_analysis_collection
        player_analysis = await player_analysis_collection.find_one(
            {"player_id": player_object_id, "user_id": user_id},
            sort=[("createdAt", -1)]  # Sort by createdAt in descending order
        )
        
        if player_analysis:
            # Serialize analysis ObjectIds to strings
            analysis_serialized = {k: serialize_object_id(v) for k, v in player_analysis.items()}
            player_serialized["player_analysis"] = analysis_serialized
        else:
            player_serialized["player_analysis"] = None
        
        # Get all player notes for this player, sorted by date
        player_notes = []
        # Use string representation of player_id for query
        player_id_str = str(player_object_id)
        async for note in players_notes_collection.find(
            {"player_id": player_id_str, "user_id": user_id}
        ).sort("createdAt", -1):  # Sort by createdAt in descending order
            # Serialize player note ObjectIds to strings
            note_serialized = {k: serialize_object_id(v) for k, v in note.items()}
            player_notes.append(note_serialized)
        
        player_serialized["player_notes"] = player_notes
        
        return player_serialized

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving player details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/players/{player_id}/update-name", response_model=Dict[str, Any])
async def update_player_name(player_id: str, player_update: PlayerNameUpdate, user_id: str = Header(None)):
    """
    Update a player's name.
    
    Parameters:
    - player_id: The ID of the player to update
    - player_update: The new name for the player
    - user_id: The ID of the user who owns the player (from header)
    
    Returns:
    - The updated player document
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Convert string ID to ObjectId
        try:
            player_object_id = ObjectId(player_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid player ID format")

        # Get the player document to verify it exists and belongs to the user
        player = await players_collection.find_one({"_id": player_object_id, "user_id": user_id})
        
        if not player:
            raise HTTPException(status_code=404, detail="Player not found or does not belong to this user")
        
        # Update the player's name and update timestamp
        update_result = await players_collection.update_one(
            {"_id": player_object_id, "user_id": user_id},
            {"$set": {
                "name": player_update.name,
                "updatedAt": datetime.utcnow()
            }}
        )
        
        if update_result.modified_count == 0:
            raise HTTPException(status_code=400, detail="Player name update failed")
            
        # Get the updated player document
        updated_player = await players_collection.find_one({"_id": player_object_id, "user_id": user_id})
        
        # Serialize player ObjectIds to strings
        player_serialized = {k: serialize_object_id(v) for k, v in updated_player.items()}
        
        return {
            "success": True,
            "message": "Player name updated successfully",
            "player": player_serialized
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error updating player name: {e}")
        raise HTTPException(status_code=500, detail=str(e))
