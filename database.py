import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_database_connection():
    """Get a database connection with the current event loop"""
    # Import here to avoid circular imports
    import motor.motor_asyncio
    
    try:
        # Get the MongoDB URI from environment variables - try multiple common variable names
        MONGODB_URI = os.getenv("MONGODB_URL")  # Try this first (used in player_notes_api.py)
        
        # If not found, try alternative environment variable names
        if not MONGODB_URI:
            MONGODB_URI = os.getenv("DATABASE_URL")
        
        if not MONGODB_URI:
            MONGODB_URI = os.getenv("MONGO_URI")
            
        if not MONGODB_URI:
            MONGODB_URI = os.getenv("MONGODB_URI")
            
        # Last resort fallback
        if not MONGODB_URI:
            print("[DB] WARNING: MongoDB URL environment variable not found, using localhost")
            MONGODB_URI = "mongodb://localhost:27017"
        else:
            print(f"[DB] Using MongoDB connection from environment variables")
            
        # Always create a fresh client connected to the current event loop
        # This ensures we don't reuse connections from closed loops
        current_loop = asyncio.get_event_loop()
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI, io_loop=current_loop)
        
        # Log the connection
        print(f"[DB] Created new MongoDB connection with event loop {id(current_loop)}")
        
        return client
    except Exception as e:
        print(f"[DB] Error creating database connection: {e}")
        raise 