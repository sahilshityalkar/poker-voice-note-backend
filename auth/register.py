# register.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field, UUID4
from typing import Optional
from datetime import datetime, timedelta
import jwt
# from passlib.context import CryptContext  # Remove passlib import
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import uuid

# Load environment variables
load_dotenv()

# Create APIRouter instance
router = APIRouter()

# MongoDB Connection
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes  # database name
users_collection = db.users  # collection name

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")  # Please set this in .env
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password Hashing
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") # Remove password context

# Pydantic Models
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserResponse(BaseModel):
    user_id: UUID4
    username: str
    email: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    user_id: UUID4  # Include user_id in the response

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/register", response_model=TokenResponse, tags=["Authentication"])
async def register_user(user: UserCreate):
    # Check if username already exists
    if await users_collection.find_one({"username": user.username}):
        raise HTTPException(
            status_code=400,
            detail="Username already registered"
        )
    
    # Check if email already exists
    if await users_collection.find_one({"email": user.email}):
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )
    
    # Hash the password
    # hashed_password = pwd_context.hash(user.password)  # Remove hashing
    
    # Generate a UUID for the user
    user_id = uuid.uuid4()
    
    # Create user document
    user_doc = {
        "user_id": str(user_id),  # Store user_id as a string
        "username": user.username,
        "email": user.email,
        "password": user.password,  # Store password as is
        "created_at": datetime.utcnow()
    }
    
    # Insert into database
    try:
        await users_collection.insert_one(user_doc)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to register user: {str(e)}"
        )
    
    # Create access token
    access_token = create_access_token(
        data={"sub": user.username, "user_id": str(user_id)}
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        username=user.username,
        user_id=user_id
    )