import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional, Dict
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
    potSize: Optional[float]
    date: datetime
    createdAt: datetime
    updatedAt: datetime
    players: List[PlayerInHand]

    class Config:
        allow_population_by_field_name = True
        json_encoders = {
            ObjectId: str
        }

class NoteInsight(BaseModel):
    playerTendencies: Dict[str, str]
    keyDecisions: List[str]
    strategicImplications: List[str]

class Note(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    handId: str
    audioFileUrl: str
    transcriptFromDeepgram: str
    summaryFromGPT: str
    insightFromGPT: NoteInsight
    date: datetime
    createdAt: datetime
    updatedAt: datetime

    class Config:
        allow_population_by_field_name = True
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
        json_encoders = {
            ObjectId: str
        }

class HandNotesPair(BaseModel):
    hand: Hand
    note: Note

class PlayerWithHandsAndNotes(BaseModel):
    player: Player
    handAndNotes: List[HandNotesPair]

@router.get("/{player_id}/hands-notes", response_model=PlayerWithHandsAndNotes)
async def get_player_hands_and_notes(player_id: str):
    """
    Retrieve all hands and notes for a specific player.
    Returns player details along with all associated hands and notes, sorted by date (newest first).
    """
    logging.debug(f"get_player_hands_and_notes called with player_id: {player_id}")
    try:
        # Get player
        player_obj_id = ObjectId(player_id)
        logging.debug(f"Attempting to find player with _id: {player_obj_id}")
        
        player = await players_collection.find_one({"_id": player_obj_id})
        if not player:
            logging.warning(f"Player with _id {player_id} not found.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player not found"
            )

        # Convert ObjectId to string for _id field
        player_data = dict(player)
        player_data["_id"] = str(player_data["_id"])

        # Process hand references
        hand_references = []
        hands_and_notes = []
        
        for hand_ref in player.get("handReferences", []):
            hand_ref_copy = dict(hand_ref)
            
            # Extract IDs ensuring they are in the correct format
            hand_id = hand_ref_copy.get("handId")
            note_id = hand_ref_copy.get("noteId")
            
            # Convert to string for the returned object
            if isinstance(hand_id, ObjectId):
                hand_ref_copy["handId"] = str(hand_id)
            
            if isinstance(note_id, ObjectId):
                hand_ref_copy["noteId"] = str(note_id)
            
            # Create HandReference for the player model
            hand_references.append(HandReference(**hand_ref_copy))
            
            try:
                # Use the ObjectId for query if it's a string
                hand_obj_id = hand_id if isinstance(hand_id, ObjectId) else ObjectId(hand_id)
                note_obj_id = note_id if isinstance(note_id, ObjectId) else ObjectId(note_id)
                
                # Query the collections
                hand = await hands_collection.find_one({"_id": hand_obj_id})
                note = await notes_collection.find_one({"_id": note_obj_id})
                
                if hand and note:
                    # Convert all ObjectIds to strings in the hand document
                    hand_data = dict(hand)
                    hand_data["_id"] = str(hand_data["_id"])
                    
                    if "noteId" in hand_data and isinstance(hand_data["noteId"], ObjectId):
                        hand_data["noteId"] = str(hand_data["noteId"])
                    
                    # Convert players array
                    for player_in_hand in hand_data.get("players", []):
                        if "playerId" in player_in_hand and isinstance(player_in_hand["playerId"], ObjectId):
                            player_in_hand["playerId"] = str(player_in_hand["playerId"])
                    
                    # Convert all ObjectIds to strings in the note document
                    note_data = dict(note)
                    note_data["_id"] = str(note_data["_id"])
                    
                    if "handId" in note_data and isinstance(note_data["handId"], ObjectId):
                        note_data["handId"] = str(note_data["handId"])
                    
                    # Create Hand and Note objects
                    hand_obj = Hand(**hand_data)
                    note_obj = Note(**note_data)
                    
                    # Add to our list of pairs
                    hands_and_notes.append(HandNotesPair(hand=hand_obj, note=note_obj))
                else:
                    logging.warning(f"Hand {hand_id} or Note {note_id} not found")
            except Exception as e:
                logging.exception(f"Error processing hand {hand_id} or note {note_id}: {str(e)}")
        
        # Sort hands and notes by date (newest first)
        hands_and_notes.sort(key=lambda x: x.hand.date, reverse=True)
        
        # Create final player object with the processed hand references
        player_data["handReferences"] = hand_references
        player_obj = Player(**player_data)
        
        # Return the final combined result
        return PlayerWithHandsAndNotes(
            player=player_obj,
            handAndNotes=hands_and_notes
        )
        
    except HTTPException as http_exc:
        # Re-raise HTTPExceptions
        raise http_exc
    except Exception as e:
        logging.exception(f"General error in get_player_hands_and_notes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch player hands and notes: {str(e)}"
        )