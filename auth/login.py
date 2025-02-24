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
    username: Optional[str] = Field(None, description="Username required for new users")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    user_id: UUID4


class AuthResponse(BaseModel):
    status: str
    message: str
    username: Optional[str] = None  # Username returned if user exists


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


@router.post("/auth", response_model=AuthResponse, tags=["Authentication"])
async def authenticate(request: AuthRequest):
    """
    Authenticates a user or initiates registration.

    1. Checks if the phone number exists in the database.
    2. If it exists, sends an OTP and returns the username (if available).
    3. If it doesn't exist, sends an OTP and indicates the user needs to register.
    """
    phone_number = request.phone_number
    print(f"Searching for user with phone number: {phone_number}")  # Debug print

    user = await users_collection.find_one({"mobileNumber": phone_number})
    print(f"Query result: {user}")  # Debug Print


    if user:
        # User exists, send OTP and return username (if it has)
        print(f"Sending OTP: {STATIC_OTP} to phone number: {phone_number}")

        # Return username if exists
        return AuthResponse(
            status="success", message="OTP sent successfully", username=user.get("username", None)
        )
    else:
        # User doesn't exist, require username for registering
        print(f"Sending OTP: {STATIC_OTP} to phone number: {phone_number}")
        return AuthResponse(
            status="user_not_found", message="OTP sent.  Please verify OTP and provide a username to complete registration."
        )

@router.post("/verifyotp", response_model=TokenResponse, tags=["Authentication"])
async def verify_otp(request: VerifyOTPRequest):
    """
    Verifies the OTP.  If valid, either logs in an existing user or registers a new user.
    """
    phone_number = request.phone_number
    otp = request.otp
    username = request.username

    user = await users_collection.find_one({"mobileNumber": phone_number})

    if otp != STATIC_OTP:
        raise HTTPException(status_code=400, detail="Invalid OTP. Please try again.")


    if user:
        # Existing user, log in.

        access_token = create_access_token(
            data={"sub": user["username"], "user_id": user["user_id"]}
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            username=user["username"],
            user_id=user["user_id"]
        )
    else:
        # User doesn't exist, register.
        if not username:
            raise HTTPException(status_code=400, detail="Username is required for registration.")

        existing_user = await users_collection.find_one({"mobileNumber": phone_number})
        if existing_user:
          raise HTTPException(
              status_code=400,
              detail="Phone number already registered."
          )

        user_id = uuid.uuid4()
        user_doc = {
            "user_id": str(user_id),
            "mobileNumber": phone_number,
            "username": username,
            "profilePic": "",  # Empty string for profile picture
            "isVerified": True,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        }

        try:
            await users_collection.insert_one(user_doc)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to register user: {str(e)}"
            )

        access_token = create_access_token(
            data={"sub": username, "user_id": str(user_id)}
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            username=username,
            user_id=user_id
        )