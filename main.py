# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import os
from dotenv import load_dotenv
from openai import OpenAI
import hashlib
from datetime import datetime, timedelta
import asyncio
from audio_processing.audio_api import router as audio_router  # Import the audio router
from auth.login import router as login_router
from audio_processing.get_all_notes_data import router as notes_router
from audio_processing.get_note_details import router as note_details_router
from profile_apis.profile_api import router as profile_router
from audio_processing.player_notes_api import router as player_notes_router  # Import for player notes
from audio_processing.player_analysis_api import router as player_analysis_router  # Import for player analysis
from players_apis.players_apis import router as players_apis_router  # Import for players APIs
from players_apis.player_analysis_get_apis import router as player_analysis_get_router  # Import for player analysis get APIs
from players_apis.player_delete_apis import router as player_delete_router  # Import for player delete APIs
# Remove all hand-related imports and players_apis

# Import Celery app for task management
# This is just to ensure Celery is initialized when the app starts
from cel_main import app as celery_app

# Create Celery instance reference
celery = celery_app

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(audio_router, prefix="/audio", tags=["audio"])
app.include_router(login_router, prefix="/auth", tags=["Authentication"])
app.include_router(notes_router, prefix="/notes", tags=["notes"])
app.include_router(note_details_router, prefix="/notes", tags=["notes"])
app.include_router(profile_router, prefix="/profile", tags=["profile"])
app.include_router(player_notes_router, prefix="/player-notes", tags=["player-notes"])
app.include_router(player_analysis_router, tags=["player-analysis"])  # No prefix because it's already defined in the router
app.include_router(players_apis_router, prefix="/players-api", tags=["players"])  # New players APIs
app.include_router(player_analysis_get_router, prefix="/player-analysis", tags=["player-analysis"])  # Player analysis get APIs
app.include_router(player_delete_router, tags=["player-delete"])  # Player delete APIs

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Define request model
class GameNotes(BaseModel):
    notes: List[str]

class CacheEntry:
    def __init__(self, analysis: str):
        self.analysis = analysis
        self.timestamp = datetime.now()

class AnalysisCache:
    def __init__(self, expiry_minutes: int = 60):
        self.cache: Dict[str, CacheEntry] = {}
        self.expiry_minutes = expiry_minutes

    def get_cache_key(self, notes: List[str]) -> str:
        # Create a unique key from the sorted notes
        notes_str = ''.join(sorted(notes))
        return hashlib.md5(notes_str.encode()).hexdigest()

    def get(self, notes: List[str]) -> str:
        key = self.get_cache_key(notes)
        entry = self.cache.get(key)
        
        if entry is None:
            return None

        # Check if cache entry has expired
        if datetime.now() - entry.timestamp > timedelta(minutes=self.expiry_minutes):
            del self.cache[key]
            return None

        return entry.analysis

    def set(self, notes: List[str], analysis: str):
        key = self.get_cache_key(notes)
        self.cache[key] = CacheEntry(analysis)

# Initialize cache
analysis_cache = AnalysisCache(expiry_minutes=60)

# Create startup event to initialize indexes
@app.on_event("startup")
async def startup_event():
    try:
        from audio_processing.player_notes_api import setup_indexes as setup_player_notes_indexes
        from audio_processing.player_analysis_api import ensure_indexes as ensure_player_analysis_indexes
        
        # Ensure database indexes exist
        try:
            await setup_player_notes_indexes()
        except Exception as e:
            print(f"Warning: Error creating player notes indexes: {e}")
            
        try:
            await ensure_player_analysis_indexes()
        except Exception as e:
            print(f"Warning: Error creating player analysis indexes: {e}")
            
        print("Application started, database setup complete.")
    except Exception as e:
        print(f"Warning: Error during startup: {e}")
        # Continue anyway to avoid startup failures

def create_analysis_prompt(notes: List[str]) -> str:
    """Create a detailed, structured prompt for GPT analysis."""
    game_text = "\n".join(notes)  # Each note on a new line for readability
    return f"""
You are a world-class poker analyst, providing expert feedback to help players improve their game. Your analysis should be concise, but insightful and directly actionable. Focus on identifying leaks and suggesting immediate improvements.

**Game Notes:**
{game_text}

**Analysis Guidelines:**

1.  **Summary of Key Decisions:** Briefly summarize the most important decisions the player made in the hand.  Focus on pre-flop, flop, turn, and river actions.

2.  **Strategic Evaluation:**  Evaluate the player's decisions based on poker theory and common strategies. Consider factors like:
    *   Hand strength and range
    *   Position
    *   Opponent tendencies (if known/implied in notes)
    *   Board texture
    *   Pot odds and implied odds
    *   Bet sizing

3.  **Identified Leaks:** Pinpoint specific mistakes or areas where the player deviated from optimal strategy.  Be direct and clear about the issues.

4.  **Actionable Improvements:**  Provide 2-3 concrete, actionable steps the player can take to improve their game. These should be specific and directly related to the hand.  For example, "Consider a smaller continuation bet on the flop," or "Be more selective with calling ranges from middle position."

5.  **Overall Assessment:** Provide a very short final assessment of the hand.

**Example Output Format:**

**Summary of Key Decisions:**  Raised pre-flop, bet flop, checked turn, folded river.

**Strategic Evaluation:** Pre-flop raise was standard. Flop bet was reasonable. Turn check was passive. River fold was likely correct given the pot odds and opponent's aggressive action.

**Identified Leaks:**  Checking the turn allowed the opponent to control the action and potentially bluff.

**Actionable Improvements:**
*   Consider betting the turn for value or protection.
*   Analyze opponent's tendencies to better assess the river all-in.

**Overall Assessment:** The player made some standard plays but could have played the turn more aggressively.
"""

async def get_gpt_analysis(prompt: str) -> str:
    """Get analysis from GPT with optimized parameters."""
    try:
        response = await asyncio.to_thread(client.chat.completions.create,  # Use asyncio.to_thread
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a poker coach. Be brief and specific."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,  # Reduced tokens for faster response
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error during OpenAI call: {e}")
        raise

@app.get("/")
async def root():
    """Test endpoint to verify API is running"""
    return {"message": "Poker Analysis API is running"}

@app.post("/analyze-game")
async def analyze_game(game: GameNotes):
    """Endpoint to analyze poker game notes with caching"""
    try:
        # Check cache first
        cached_result = analysis_cache.get(game.notes)
        if cached_result:
            return {
                "success": True,
                "analysis": cached_result,
                "source": "cache"
            }

        # If not in cache, get new analysis
        prompt = create_analysis_prompt(game.notes)
        analysis = await get_gpt_analysis(prompt)

        # Save to cache
        analysis_cache.set(game.notes, analysis)

        return {
            "success": True,
            "analysis": analysis,
            "source": "gpt"
        }

    except Exception as e:
        print(f"Error during analysis: {e}")  # Log the error
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)