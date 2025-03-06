from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, UUID4, validator, Field
from datetime import datetime, timedelta
import jwt
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import re
import uuid
from typing import Optional

# Load environment variables
load_dotenv()

# Create APIRouter instance
router = APIRouter()

# MongoDB Connection
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)

try:
    client.admin.command('ping')  # Try to ping the server
    print("Successfully connected to MongoDB")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    raise  # Re-raise the exception to stop the program

db = client.pokernotes
users_collection = db.users

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
STATIC_OTP = "123123"  # Define the static OTP

# Pydantic Models
class AuthRequest(BaseModel):
    phone_number: str = Field(..., description="User's phone number (10-15 digits)")

    @validator("phone_number")
    def phone_number_must_be_valid(cls, phone_number):
        """Validate phone number format (basic example).  Adjust as needed."""
        if not re.match(r"^[0-9]{10,15}$", phone_number):  # Example: 10-15 digits
            raise ValueError("Invalid phone number format.")
        return phone_number

class VerifyOTPRequest(BaseModel):
    phone_number: str
    otp: str

class RegistrationCompleteRequest(BaseModel):
    username: str = Field(..., min_length=3)
    app_language: Optional[str] = Field(default="en")
    notes_language: Optional[str] = Field(default="en")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: Optional[str] = None
    user_id: str
    registration_complete: bool = False

class AuthResponse(BaseModel):
    status: str
    message: str
    username: Optional[str] = None

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/auth", response_model=AuthResponse, tags=["Authentication"])
async def initiate_auth(request: AuthRequest):
    """
    Stage 1: Initiate authentication by sending OTP
    """
    phone_number = request.phone_number
    print(f"Searching for user with phone number: {phone_number}")

    user = await users_collection.find_one({"mobileNumber": phone_number})
    print(f"Query result: {user}")

    if user:
        # User exists, send OTP and return username
        print(f"Sending OTP: {STATIC_OTP} to phone number: {phone_number}")
        return AuthResponse(
            status="success",
            message="OTP sent successfully",
            username=user.get("username")
        )
    else:
        # User doesn't exist, send OTP for registration
        print(f"Sending OTP: {STATIC_OTP} to phone number: {phone_number}")
        return AuthResponse(
            status="user_not_found",
            message="OTP sent successfully"
        )

@router.post("/verifyotp", response_model=TokenResponse, tags=["Authentication"])
async def verify_otp(request: VerifyOTPRequest):
    """
    Stage 2: Verify OTP and return user data
    """
    phone_number = request.phone_number
    otp = request.otp

    user = await users_collection.find_one({"mobileNumber": phone_number})

    if otp != STATIC_OTP:
        raise HTTPException(status_code=400, detail="Invalid OTP. Please try again.")

    if user:
        # Existing user, log in
        access_token = create_access_token(
            data={"sub": user["username"], "user_id": user["user_id"]}
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            username=user["username"],
            user_id=user["user_id"],
            registration_complete=True
        )
    else:
        # New user, create temporary user with registration_complete=False
        user_id = str(uuid.uuid4())
        user_doc = {
            "user_id": user_id,
            "mobileNumber": phone_number,
            "registration_complete": False,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        }

        try:
            await users_collection.insert_one(user_doc)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create temporary user: {str(e)}"
            )

        access_token = create_access_token(
            data={"sub": user_id, "user_id": user_id}
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=user_id,
            registration_complete=False
        )

@router.post("/complete-registration/{user_id}", response_model=TokenResponse, tags=["Authentication"])
async def complete_registration(user_id: str, request: RegistrationCompleteRequest):
    """
    Stage 3: Complete registration with user details
    """
    user = await users_collection.find_one({"user_id": user_id})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.get("registration_complete", False):
        raise HTTPException(status_code=400, detail="Registration already completed")

    # Update user with registration details
    update_data = {
        "username": request.username,
        "app_language": request.app_language or "en",  # Default to English if not provided
        "notes_language": request.notes_language or "en",  # Default to English if not provided
        "registration_complete": True,
        "updatedAt": datetime.utcnow()
    }

    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": update_data}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to complete registration: {str(e)}"
        )

    # Create new access token
    access_token = create_access_token(
        data={"sub": request.username, "user_id": user_id}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        username=request.username,
        user_id=user_id,
        registration_complete=True
    )