from fastapi import APIRouter, HTTPException, Header
from typing import Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId
import os
from datetime import datetime

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
notes_collection = db.notes
hands_collection = db.hands
players_collection = db.players

def serialize_object_id(obj):
    """Helper function to serialize ObjectId to string."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()  # Convert datetime objects to ISO format
    return obj

@router.get("/note/{note_id}", response_model=Dict[str, Any])
async def get_note_details(note_id: str, user_id: str = Header(None)):
    """
    Get detailed information about a specific note including:
    - Note data (transcript, summary, insight)
    - Hand data (positions, outcome)
    - Player information
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        # Convert string ID to ObjectId
        try:
            note_object_id = ObjectId(note_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid note ID format")

        # Aggregate pipeline to get note with related data
        pipeline = [
            # Match the specific note
            {
                "$match": {
                    "_id": note_object_id,
                    "user_id": user_id
                }
            },
            # Lookup hand data
            {
                "$lookup": {
                    "from": "hands",
                    "localField": "handId",
                    "foreignField": "_id",
                    "as": "hand"
                }
            },
            # Unwind the hand array
            {
                "$unwind": {
                    "path": "$hand",
                    "preserveNullAndEmptyArrays": True
                }
            },
            # Lookup player details for each player in the hand
            {
                "$lookup": {
                    "from": "players",
                    "let": { "playerIds": "$hand.players.playerId" },
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$in": ["$_id", "$$playerIds"]
                                }
                            }
                        },
                        {
                            "$project": {
                                "_id": 1,
                                "name": 1,
                                "totalHands": 1,
                                "totalWins": 1
                            }
                        }
                    ],
                    "as": "playerDetails"
                }
            },
            # Project the final structure
            {
                "$project": {
                    "_id": {"$toString": "$_id"},
                    "date": 1,
                    "audioFileUrl": 1,
                    "transcriptFromDeepgram": 1,
                    "summaryFromGPT": 1,
                    "insightFromGPT": 1,
                    "handId": {"$toString": "$handId"},
                    "hand": {
                        "_id": {"$toString": "$hand._id"},
                        "myPosition": "$hand.myPosition",
                        "iWon": "$hand.iWon",
                        "potSize": "$hand.potSize",
                        "players": {
                            "$map": {
                                "input": "$hand.players",
                                "as": "player",
                                "in": {
                                    "playerId": {"$toString": "$$player.playerId"},
                                    "name": "$$player.name",
                                    "position": "$$player.position",
                                    "won": "$$player.won",
                                    "stats": {
                                        "$let": {
                                            "vars": {
                                                "playerDetail": {
                                                    "$arrayElemAt": [
                                                        {
                                                            "$filter": {
                                                                "input": "$playerDetails",
                                                                "cond": {
                                                                    "$eq": ["$$this._id", "$$player.playerId"]
                                                                }
                                                            }
                                                        },
                                                        0
                                                    ]
                                                }
                                            },
                                            "in": {
                                                "totalHands": "$$playerDetail.totalHands",
                                                "totalWins": "$$playerDetail.totalWins"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "createdAt": 1,
                    "updatedAt": 1
                }
            }
        ]

        # Execute the aggregation
        async for note in notes_collection.aggregate(pipeline):
            # Serialize ObjectIds to strings after fetching from MongoDB
            note = {k: serialize_object_id(v) for k, v in note.items()}
            return note

        # If no note found
        raise HTTPException(status_code=404, detail="Note not found")

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving note details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/notes", response_model=List[Dict[str, Any]])
async def get_all_notes_by_user(user_id: str = Header(None)):
    """
    Get all notes associated with a specific user ID.
    Returns a list of note objects.
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")

        notes = []
        async for note in notes_collection.find({"user_id": user_id}):
            # Serialize ObjectIds to strings
            note = {k: serialize_object_id(v) for k, v in note.items()}
            notes.append(note)

        return notes

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error retrieving notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))