from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, UUID4, validator
from typing import Optional
from datetime import datetime, timedelta
import jwt
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import uuid
import re  # Import the regular expression module

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
STATIC_OTP = "123123"  # Define the static OTP

# Pydantic Models
class UserCreateRequest(BaseModel):
    phone_number: str

    @validator("phone_number")
    def phone_number_must_be_valid(cls, phone_number):
        """Validate phone number format (basic example).  Adjust as needed."""
        if not re.match(r"^[0-9]{10,15}$", phone_number):  # Example: 10-15 digits
            raise ValueError("Invalid phone number format.")
        return phone_number

class VerifyOTPRequest(BaseModel):
    username: str
    phone_number: str
    otp: str

class UserResponse(BaseModel):
    user_id: UUID4
    username: str
    phone_number: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    user_id: UUID4  # Include user_id in the response

class RegisterResponse(BaseModel):
    status: str
    message: str

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/register/requestotp", response_model=RegisterResponse, tags=["Authentication"])
async def register_request_otp(user_create: UserCreateRequest):
    """
    Checks if the phone number is already registered. If not,
    it simulates sending an OTP to the phone number.
    """

    # Check if phone number already exists
    if await users_collection.find_one({"phone_number": user_create.phone_number}):
        raise HTTPException(
            status_code=400,
            detail="Phone number already registered"
        )

    # In a real application, you would send the OTP to the phone number here.
    # For now, just print it for debugging.
    print(f"Simulating sending OTP: {STATIC_OTP} to phone number: {user_create.phone_number}")

    return RegisterResponse(status="success", message="OTP sent to phone number.")


@router.post("/register/verifyotp", response_model=TokenResponse, tags=["Authentication"])
async def register_verify_otp(verify_data: VerifyOTPRequest):
    """
    Verifies the OTP, creates the user profile, and returns a token.
    """

    if verify_data.otp != STATIC_OTP:
        raise HTTPException(
            status_code=400,
            detail="Invalid OTP."
        )

    # Check one last time if phone number is already registered (race condition).
    if await users_collection.find_one({"phone_number": verify_data.phone_number}):
        raise HTTPException(
            status_code=400,
            detail="Phone number already registered"
        )

    # Generate a UUID for the user
    user_id = uuid.uuid4()

    # Create user document
    user_doc = {
        "user_id": str(user_id),  # Store user_id as a string
        "username": verify_data.username,
        "phone_number": verify_data.phone_number,
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
        data={"sub": verify_data.username, "user_id": str(user_id)}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        username=verify_data.username,
        user_id=user_id
    )