from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field, UUID4
from typing import List, Optional
from datetime import datetime
import uuid
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import traceback

# Load environment variables
load_dotenv()

# Create APIRouter instance
router = APIRouter()

# MongoDB Connection (Use the same connection details as your auth setup)
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes  # database name
rooms_collection = db.rooms  # collection name

# Pydantic Models
class RoomCreate(BaseModel):
    room_name: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = None

class Room(BaseModel):
    room_id: UUID4
    room_name: str
    description: Optional[str]
    created_at: datetime
    owner_user_id: UUID4  # Added owner_user_id

class RoomUpdate(BaseModel):
    room_name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = None

# CRUD Operations

@router.post("/rooms", response_model=Room, tags=["Rooms"])
async def create_room(room_data: RoomCreate, user_id: str = Header(None)):
    """Creates a new room."""

    room_id = uuid.uuid4()

    # Check if user_id is provided
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required in the header")

    try:
        uuid.UUID(user_id)  # Validate user_id is a valid UUID
        owner_user_id = user_id
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid User ID format (must be a UUID)")

    room = {
        "room_id": str(room_id),
        "room_name": room_data.room_name,
        "description": room_data.description,
        "created_at": datetime.utcnow(),
        "owner_user_id": owner_user_id  # Store the provided user ID
    }

    try:
        await rooms_collection.insert_one(room)
        print("Room inserted successfully!")
    except Exception as e:
        print(f"Failed to create room: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to create room: {e}")

    return Room(**room)  # Convert the MongoDB document to a Room model.

@router.get("/rooms/{room_id}", response_model=Room, tags=["Rooms"])
async def get_room(room_id: UUID4):
    """Retrieves a room by its ID."""

    room = await rooms_collection.find_one({"room_id": str(room_id)})

    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    return Room(**room)  # Convert the MongoDB document to a Room model.

@router.put("/rooms/{room_id}", response_model=Room, tags=["Rooms"])
async def update_room(room_id: UUID4, room_data: RoomUpdate):
    """Updates a room's information."""

    room = await rooms_collection.find_one({"room_id": str(room_id)})

    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    update_data = room_data.dict(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No data provided for update")

    try:
        await rooms_collection.update_one({"room_id": str(room_id)}, {"$set": update_data})
        updated_room = await rooms_collection.find_one({"room_id": str(room_id)})
        return Room(**updated_room)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update room: {e}")

@router.delete("/rooms/{room_id}", tags=["Rooms"])
async def delete_room(room_id: UUID4):
    """Deletes a room."""

    room = await rooms_collection.find_one({"room_id": str(room_id)})

    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    try:
        delete_result = await rooms_collection.delete_one({"room_id": str(room_id)})
        if delete_result.deleted_count == 0:  # Double check that deletion occurred, though it *should* have worked.
            raise HTTPException(status_code=404, detail="Room not found")
        return {"message": "Room deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete room: {e}")

@router.get("/rooms", response_model=List[Room], tags=["Rooms"])
async def get_all_rooms():
    """Retrieves all rooms."""
    rooms = []
    async for room in rooms_collection.find():
        rooms.append(Room(**room))
    return rooms