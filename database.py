import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_database_connection(provided_loop=None):
    """
    Get a database connection with either a provided event loop or the current one
    
    Args:
        provided_loop: Optional event loop to use instead of creating a new one
    
    Returns:
        AsyncIOMotorClient connected to the current or provided event loop
    """
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
            
        # Use the provided loop or get the current one
        loop_to_use = provided_loop or asyncio.get_event_loop()
        
        # Always create a fresh client connected to the specified event loop
        # This ensures we don't reuse connections from closed loops
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI, io_loop=loop_to_use)
        
        # Log the connection
        print(f"[DB] Created new MongoDB connection with event loop {id(loop_to_use)}")
        
        return client
    except Exception as e:
        print(f"[DB] Error creating database connection: {e}")
        raise 