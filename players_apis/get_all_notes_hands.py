# backend/players_apis/analyze_player.py

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
    strengths: Optional[List[str]] = None
    weaknesses: Optional[List[str]] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str
        }

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
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str
        }

class Note(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    handId: str
    audioFileUrl: Optional[str] = None
    transcriptFromDeepgram: str
    summaryFromGPT: str
    insightFromGPT: Any
    date: datetime
    createdAt: datetime
    updatedAt: datetime

    class Config:
        populate_by_name = True
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
    Retrieve player details along with all associated hands and notes.
    Returns player data and all hands-notes pairs, sorted by date (newest first).
    """
    try:
        # Convert string player_id to ObjectId
        player_obj_id = ObjectId(player_id)
        print(f"Looking up player with ID: {player_obj_id}")

        # Fetch player from database
        player = await players_collection.find_one({"_id": player_obj_id})
        if not player:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player not found"
            )

        print(f"Found player: {player['name']}")
        print(f"Player handReferences: {player.get('handReferences', [])}")

        # Convert player data and create Player object
        player_data = convert_objectid_to_str(player)
        player_obj = Player(**player_data)
        print("Successfully created Player object")

        hands_and_notes = []

        # Process each hand reference
        for hand_ref in player.get("handReferences", []):
            try:
                print(f"\nProcessing hand reference: {hand_ref}")
                
                # Get and convert IDs
                hand_id = hand_ref.get("handId")
                note_id = hand_ref.get("noteId")
                
                print(f"Original hand_id: {hand_id} ({type(hand_id)})")
                print(f"Original note_id: {note_id} ({type(note_id)})")

                # Convert to ObjectId if needed
                if isinstance(hand_id, str):
                    hand_id = ObjectId(hand_id)
                if isinstance(note_id, str):
                    note_id = ObjectId(note_id)
                elif isinstance(hand_id, dict) and '$oid' in hand_id:
                    hand_id = ObjectId(hand_id['$oid'])
                elif isinstance(note_id, dict) and '$oid' in note_id:
                    note_id = ObjectId(note_id['$oid'])

                print(f"Converted hand_id: {hand_id}")
                print(f"Converted note_id: {note_id}")

                # Fetch hand and note from database
                hand = await hands_collection.find_one({"_id": hand_id})
                note = await notes_collection.find_one({"_id": note_id})

                print(f"Found hand: {hand is not None}")
                print(f"Found note: {note is not None}")

                if hand:
                    print(f"Hand preview: {str(hand)[:200]}")
                if note:
                    print(f"Note preview: {str(note)[:200]}")

                if hand and note:
                    # Convert ObjectIds to strings
                    hand_data = convert_objectid_to_str(hand)
                    note_data = convert_objectid_to_str(note)

                    try:
                        # Create Hand and Note objects
                        hand_obj = Hand(**hand_data)
                        note_obj = Note(**note_data)

                        # Add to list
                        hands_and_notes.append(HandNotesPair(hand=hand_obj, note=note_obj))
                        print("Successfully added hand-note pair to list")
                    except Exception as validation_error:
                        print(f"Validation error creating objects: {str(validation_error)}")
                        print(f"Hand data: {hand_data}")
                        print(f"Note data: {note_data}")
                else:
                    print("Skipping hand-note pair as one or both documents not found")

            except Exception as e:
                print(f"Error processing hand reference: {str(e)}")
                continue

        print(f"\nTotal hands and notes processed: {len(hands_and_notes)}")
        
        # Sort by date (newest first)
        if hands_and_notes:
            hands_and_notes.sort(key=lambda x: x.hand.date, reverse=True)
            print("Sorted hands and notes by date")
        
        # Return combined result
        result = PlayerWithHandsAndNotes(
            player=player_obj,
            handAndNotes=hands_and_notes
        )
        print("Successfully created final response object")
        return result

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Unexpected error in get_player_hands_and_notes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch player data: {str(e)}"
        )