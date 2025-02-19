# login.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, UUID4
from datetime import datetime, timedelta
import jwt
# from passlib.context import CryptContext # Remove passlib import
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create APIRouter instance
router = APIRouter()

# MongoDB Connection
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes
users_collection = db.users

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password Hashing
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") # Remove password context

# Pydantic Models
class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    user_id: UUID4  # Add user_id to the response

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/login", response_model=TokenResponse, tags=["Authentication"])
async def login_user(user_credentials: UserLogin):
    # Find user by email
    user = await users_collection.find_one({"email": user_credentials.email})

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Verify password
    # if not pwd_context.verify(user_credentials.password, user["hashed_password"]): # Remove bcrypt password verification
    if user_credentials.password != user["password"]:  # Compare plain text passwords
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    # Create access token
    access_token = create_access_token(
        data={"sub": user["username"], "user_id": user["user_id"]}  # Include user_id in token data
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        username=user["username"],
        user_id=user["user_id"]  # Return the user_id
    )