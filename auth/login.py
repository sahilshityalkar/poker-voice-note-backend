from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, UUID4, validator
from datetime import datetime, timedelta
import jwt
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import re

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
STATIC_OTP = "123123"  # Define the static OTP

# Pydantic Models
class SendOTPRequest(BaseModel):
    phone_number: str

    @validator("phone_number")
    def phone_number_must_be_valid(cls, phone_number):
        """Validate phone number format (basic example).  Adjust as needed."""
        if not re.match(r"^[0-9]{10,15}$", phone_number):  # Example: 10-15 digits
            raise ValueError("Invalid phone number format.")
        return phone_number

class VerifyOTPRequest(BaseModel):
    phone_number: str  # Need phone number to identify the user
    otp: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    user_id: UUID4

class SendOTPResponse(BaseModel):
    status: str
    message: str

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


@router.post("/sendotp", response_model=SendOTPResponse, tags=["Authentication"])
async def send_otp(request: SendOTPRequest):
    """Sends the OTP (static in this case) to the user."""
    phone_number = request.phone_number

    # Find user by phone number
    user = await users_collection.find_one({"phone_number": phone_number})

    if not user:
        raise HTTPException(status_code=404, detail="User with this phone number not found. Please register.")
        # Or, if you prefer a redirect response (not standard for APIs):
        # return RedirectResponse("/register", status_code=303)

    # In a real application, you'd send the OTP here (SMS, etc.).
    # Since it's static, we just log it for debugging purposes.
    print(f"Sending OTP: {STATIC_OTP} to phone number: {phone_number}")

    return SendOTPResponse(status="success", message="OTP sent successfully")


@router.post("/verifyotp", response_model=TokenResponse, tags=["Authentication"])
async def verify_otp(request: VerifyOTPRequest):
    """Verifies the OTP and returns a token if valid."""
    phone_number = request.phone_number
    otp = request.otp

    # Find user by phone number
    user = await users_collection.find_one({"phone_number": phone_number})

    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if otp != STATIC_OTP:
        raise HTTPException(status_code=400, detail="Invalid OTP. Please try again.")

    # Create access token
    access_token = create_access_token(
        data={"sub": user["username"], "user_id": user["user_id"]}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        username=user["username"],
        user_id=user["user_id"]
    )