import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field
from datetime import datetime
from bson import ObjectId

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
players_collection = db.players
hands_collection = db.hands
notes_collection = db.notes

# Pydantic models
class PlayerInHand(BaseModel):
    playerId: str
    name: str
    position: str
    won: bool

    class Config:
        json_encoders = {
            ObjectId: str
        }

class Hand(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    noteId: str
    myPosition: str
    iWon: bool
    potSize: Optional[float] = None
    date: datetime
    createdAt: datetime
    updatedAt: datetime
    players: List[PlayerInHand]

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str
        }

class NoteInsight(BaseModel):
    playerTendencies: Dict[str, str] = {}
    keyDecisions: List[str] = []
    strategicImplications: List[str] = []

    class Config:
        arbitrary_types_allowed = True

class Note(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    handId: str
    audioFileUrl: str
    transcriptFromDeepgram: str
    summaryFromGPT: str
    insightFromGPT: Any  # Using Any to handle different formats
    date: datetime
    createdAt: datetime
    updatedAt: datetime

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str
        }

class HandReference(BaseModel):
    handId: str
    noteId: str
    position: str
    won: bool
    date: datetime

    class Config:
        json_encoders = {
            ObjectId: str
        }

class Player(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    name: str
    totalHands: int
    totalWins: int
    handReferences: List[HandReference]
    createdAt: datetime
    updatedAt: datetime

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str
        }

class HandNotesPair(BaseModel):
    hand: Hand
    note: Note

class PlayerWithHandsAndNotes(BaseModel):
    player: Player
    handAndNotes: List[HandNotesPair]

def convert_objectid_to_str(data):
    """
    Recursively convert all ObjectId instances to strings in a dictionary or list
    """
    if isinstance(data, dict):
        return {k: convert_objectid_to_str(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_objectid_to_str(item) for item in data]
    elif isinstance(data, ObjectId):
        return str(data)
    else:
        return data

@router.get("/{player_id}/hands-notes", response_model=PlayerWithHandsAndNotes)
async def get_player_hands_and_notes(player_id: str):
    """
    Retrieve all hands and notes for a specific player.
    Returns player details along with all associated hands and notes, sorted by date (newest first).
    """
    logging.debug(f"get_player_hands_and_notes called with player_id: {player_id}")
    try:
        # Convert string player_id to ObjectId
        player_obj_id = ObjectId(player_id)
        
        # Fetch player from database
        player = await players_collection.find_one({"_id": player_obj_id})
        if not player:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player not found"
            )
        
        # Convert all ObjectIds to strings in player data
        player_data = convert_objectid_to_str(player)
        
        # Initialize handAndNotes list
        hands_and_notes = []
        
        # Process each hand reference
        for hand_ref in player.get("handReferences", []):
            try:
                # Get hand and note IDs
                hand_id = hand_ref.get("handId")
                note_id = hand_ref.get("noteId")
                
                if not hand_id or not note_id:
                    logging.warning(f"Missing handId or noteId in handReference: {hand_ref}")
                    continue
                
                # Fetch hand and note from database
                hand = await hands_collection.find_one({"_id": hand_id})
                note = await notes_collection.find_one({"_id": note_id})
                
                if not hand or not note:
                    logging.warning(f"Hand {hand_id} or Note {note_id} not found")
                    continue
                
                # Convert ObjectIds to strings
                hand_data = convert_objectid_to_str(hand)
                note_data = convert_objectid_to_str(note)
                
                # Create Hand and Note objects
                hand_obj = Hand(**hand_data)
                note_obj = Note(**note_data)
                
                # Add to handAndNotes list
                hands_and_notes.append(HandNotesPair(hand=hand_obj, note=note_obj))
                
            except Exception as e:
                logging.exception(f"Error processing hand/note pair: {str(e)}")
        
        # Sort hands and notes by date (newest first)
        hands_and_notes.sort(key=lambda x: x.hand.date, reverse=True)
        
        # Create Player object
        player_obj = Player(**player_data)
        
        # Return combined result
        return PlayerWithHandsAndNotes(
            player=player_obj,
            handAndNotes=hands_and_notes
        )
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logging.exception(f"Error in get_player_hands_and_notes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch player data: {str(e)}"
        )