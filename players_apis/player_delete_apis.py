from fastapi import APIRouter, HTTPException, Header
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
from dotenv import load_dotenv
from typing import Dict, Any

# Load environment variables
load_dotenv()

router = APIRouter(tags=["player-delete"])

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
players_collection = db.players
players_notes_collection = db.players_notes

@router.delete("/players/{player_id}")
async def delete_player(player_id: str, user_id: str = Header(None)) -> Dict[str, Any]:
    """
    Delete a player from the players collection.
    This will only remove the player record but not their notes.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Validate player_id format
        try:
            player_obj_id = ObjectId(player_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid player ID format")
        
        # Check if player exists and belongs to user
        player = await players_collection.find_one({"_id": player_obj_id, "user_id": user_id})
        if not player:
            raise HTTPException(status_code=404, detail="Player not found or does not belong to this user")
        
        # Delete the player
        delete_result = await players_collection.delete_one({"_id": player_obj_id, "user_id": user_id})
        
        if delete_result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Player not found or not deleted")
        
        return {
            "success": True,
            "message": f"Player {player['name']} deleted successfully",
            "deleted_count": delete_result.deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error deleting player: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete player")

@router.delete("/players/{player_id}/notes")
async def delete_player_notes(player_id: str, user_id: str = Header(None)) -> Dict[str, Any]:
    """
    Delete all notes for a specific player from the players_notes collection.
    This will keep the player record but remove all their associated notes.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Validate player_id format
        try:
            player_obj_id = ObjectId(player_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid player ID format")
        
        # Check if player exists and belongs to user
        player = await players_collection.find_one({"_id": player_obj_id, "user_id": user_id})
        if not player:
            raise HTTPException(status_code=404, detail="Player not found or does not belong to this user")
        
        # Delete all notes for this player
        delete_result = await players_notes_collection.delete_many({
            "player_id": player_obj_id,
            "user_id": user_id
        })
        
        # Clear the notes array in the player document
        await players_collection.update_one(
            {"_id": player_obj_id},
            {"$set": {"notes": []}}
        )
        
        return {
            "success": True,
            "message": f"All notes for player {player['name']} deleted successfully",
            "deleted_count": delete_result.deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error deleting player notes: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete player notes")

@router.delete("/players/{player_id}/complete")
async def delete_player_complete(player_id: str, user_id: str = Header(None)) -> Dict[str, Any]:
    """
    Delete both a player and all their notes.
    This is a convenience endpoint that combines the functionality of the two endpoints above.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Validate player_id format
        try:
            player_obj_id = ObjectId(player_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid player ID format")
        
        # Check if player exists and belongs to user
        player = await players_collection.find_one({"_id": player_obj_id, "user_id": user_id})
        if not player:
            raise HTTPException(status_code=404, detail="Player not found or does not belong to this user")
        
        player_name = player['name']
        
        # Delete all notes for this player
        notes_delete_result = await players_notes_collection.delete_many({
            "player_id": player_obj_id,
            "user_id": user_id
        })
        
        # Delete the player
        player_delete_result = await players_collection.delete_one({
            "_id": player_obj_id,
            "user_id": user_id
        })
        
        return {
            "success": True,
            "message": f"Player {player_name} and all their notes deleted successfully",
            "player_deleted": player_delete_result.deleted_count > 0,
            "notes_deleted_count": notes_delete_result.deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error in complete player deletion: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete player and notes")

@router.delete("/users/all-notes")
async def delete_all_player_notes(user_id: str = Header(None)) -> Dict[str, Any]:
    """
    Delete all player notes for a specific user from the players_notes collection.
    This will keep all player records but remove all their associated notes.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Delete all notes for this user
        notes_delete_result = await players_notes_collection.delete_many({
            "user_id": user_id
        })
        
        # Clear the notes array in all player documents for this user
        players_update_result = await players_collection.update_many(
            {"user_id": user_id},
            {"$set": {"notes": []}}
        )
        
        return {
            "success": True,
            "message": f"All player notes for user deleted successfully",
            "notes_deleted_count": notes_delete_result.deleted_count,
            "players_updated_count": players_update_result.modified_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error deleting all player notes: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete all player notes")

@router.delete("/users/all-players")
async def delete_all_players(user_id: str = Header(None)) -> Dict[str, Any]:
    """
    Delete all players and their notes for a specific user.
    This will remove all player records and all their associated notes.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Get all player IDs for this user
        players = await players_collection.find({"user_id": user_id}).to_list(length=1000)
        player_ids = [player["_id"] for player in players]
        
        # Delete all notes for all players belonging to this user
        notes_delete_result = await players_notes_collection.delete_many({
            "user_id": user_id
        })
        
        # Delete all players for this user
        players_delete_result = await players_collection.delete_many({
            "user_id": user_id
        })
        
        return {
            "success": True,
            "message": f"All players and their notes for user deleted successfully",
            "players_deleted_count": players_delete_result.deleted_count,
            "notes_deleted_count": notes_delete_result.deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error deleting all players: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete all players")

@router.delete("/users/players-only")
async def delete_all_players_only(user_id: str = Header(None)) -> Dict[str, Any]:
    """
    Delete only player records for a specific user.
    This will remove all player records from the players collection but keep their notes in the players_notes collection.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Delete all players for this user
        players_delete_result = await players_collection.delete_many({
            "user_id": user_id
        })
        
        return {
            "success": True,
            "message": f"All player records deleted successfully (notes preserved)",
            "players_deleted_count": players_delete_result.deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error deleting player records: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete player records")
