# player_notes_api.py
from fastapi import APIRouter, HTTPException, Header
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional
import json
import asyncio
from .gpt_analysis import get_gpt_response
import traceback
import re
import logging

# Define the logger
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.pokernotes

# Collections
players_collection = db.players
notes_collection = db.notes
players_notes_collection = db.players_notes

# Set up indexes for better performance
async def ensure_indexes():
    """Create indexes for collections used in this module"""
    try:
        # Create text index on description_text field in player_notes collection
        await players_notes_collection.create_index([("description_text", TEXT)])
        print("[DB] Created text index on description_text in player_notes collection")
        
        # Create index on user_id and player_id in player_notes collection
        await players_notes_collection.create_index([("user_id", 1), ("player_id", 1)])
        print("[DB] Created index on user_id and player_id in player_notes collection")
        
        # Create index on note_id in player_notes collection
        await players_notes_collection.create_index([("note_id", 1)])
        print("[DB] Created index on note_id in player_notes collection")
        
        # Run migration to remove name_lower field from existing records
        await migrate_remove_name_lower()
        await migrate_fix_player_notes_structure()
    except Exception as e:
        print(f"[DB] Error creating indexes: {e}")

# Migration function to remove name_lower field
async def migrate_remove_name_lower():
    """Remove name_lower field from existing documents"""
    try:
        # Check if there are documents with name_lower field
        count = await players_collection.count_documents({"name_lower": {"$exists": True}})
        
        if count > 0:
            print(f"[MIGRATION] Removing name_lower field from {count} player documents")
            # Remove name_lower field from all documents
            result = await players_collection.update_many(
                {"name_lower": {"$exists": True}},
                {"$unset": {"name_lower": ""}}
            )
            print(f"[MIGRATION] Removed name_lower field from {result.modified_count} documents")
        else:
            print("[MIGRATION] No documents with name_lower field found")
    except Exception as e:
        print(f"[MIGRATION] Error removing name_lower field: {e}")

async def migrate_fix_player_notes_structure():
    """Fix player notes structure to use objects instead of just IDs"""
    try:
        # Find players with notes that are not objects (they're probably just strings)
        affected_players = []
        async for player in players_collection.find({"notes": {"$exists": True}}):
            if player.get("notes") and len(player["notes"]) > 0:
                # Check if any note in the array is not a dict/object
                if any(not isinstance(note, dict) for note in player["notes"]):
                    affected_players.append(player)
        
        print(f"[MIGRATION] Found {len(affected_players)} players with incorrect notes structure")
        
        # Fix each player
        for player in affected_players:
            player_id = player["_id"]
            user_id = player["user_id"]
            
            # Get all player notes for this player from players_notes collection
            player_notes = await players_notes_collection.find({
                "player_id": player_id,
                "user_id": user_id
            }).to_list(None)
            
            # Create new notes array with correct format
            new_notes = []
            for player_note in player_notes:
                new_notes.append({
                    "note_id": str(player_note["note_id"]),
                    "player_note_id": str(player_note["_id"])
                })
            
            # Update the player with the correct notes structure
            result = await players_collection.update_one(
                {"_id": player_id},
                {"$set": {"notes": new_notes}}
            )
            
            print(f"[MIGRATION] Fixed notes for player {player['name']} (ID: {player_id})")
        
        print(f"[MIGRATION] Successfully fixed notes structure for {len(affected_players)} players")
    except Exception as e:
        print(f"[MIGRATION] Error fixing player notes structure: {e}")
        print(f"[MIGRATION] Traceback: {traceback.format_exc()}")

# Create indexes on startup
asyncio.create_task(ensure_indexes())

# Player analysis prompt template
PLAYER_ANALYSIS_PROMPT = """
You are a top-level professional quality poker analysis and educator 
Analyze the entire poker hand history transcript from the user's perspective and extract every insightful detail regarding all players involved. Focus on capturing both the strategic and emotional dimensions of each player's play. Specifically:

1. Player Analysis: For each player in the transcript (use a placeholder list such as [PLAYER_NAMES] to cover all known players, ensuring no spelling mistakes), evaluate their preflop and postflop decisions, identifying key strategic tendencies.
2. Metrics Calculation: For opponents, include estimated VPIP (Voluntarily Put Money in Pot) and Aggression Frequency metrics to assess their exploitability.
3. Strategic Leaks: Detail any observable leaks such as overly loose preflop calling, inconsistent postflop aggression, or hesitation in high-pressure spots.
4. Tilt Detection: Look for signs of emotional play (tilt), such as sudden over-aggression or inexplicable all-in moves after adverse outcomes.
5. Exploitation Tips: Provide actionable strategies on how the user can exploit these tendencies (e.g., value betting when holding strong hands or applying pressure in marginal spots).
6. Additional Insights: Include any extra details or insights that may be extracted from every note in the transcript that could be valuable for a deeper strategic understanding. Specifically, add:
   - <strong>Board Texture Analysis:</strong> Evaluate how the board interacts with typical ranges and the potential impact on each player's decisions.
   - <strong>Stack Size Consideration:</strong> Consider any hints about stack sizes or tournament dynamics that may affect aggression levels and strategic choices.
   - <strong>Positional Dynamics:</strong> Explicitly address how a player's position (e.g., button, blinds) may influence their decision-making and overall strategy.
   CORE PRINCIPLES FOR PLAYER IDENTIFICATION:
1. Context is Everything:
   - Look for ANY mention of a name in a player context
   - Consider ALL possible ways players might be referenced
   - Pay attention to the surrounding words and actions
   - Look for patterns in how names are used

2. Name Variations:
   - Names might be split or combined incorrectly
   - Names might have spelling variations
   - Names might be shortened or lengthened
   - Names might be referenced in different ways

3. Player Indicators:
   - Any action taken by a player (raised, called, folded, etc.)
   - Any possession (X's hand, X's cards)
   - Any position reference (X in the BB, X on the button)
   - Any result (X won, X lost)
   - Any interaction (against X, X vs Y)
   - Any description (X played well, X made a mistake)

   Output your findings as a JSON object (or an array of JSON objects if there are multiple players), where each object contains:

- "playername": The player's name (from the provided placeholder list [PLAYER_NAMES]).
- "description_text": A concise yet compelling text-formatted summary that includes only the relevant fields. Ensure your text covers the following strong sections.
- "description_html": A concise yet compelling HTML-formatted summary that includes only the relevant fields. Ensure your HTML covers the following strong sections:
  - <strong>Preflop:</strong> Describe the player's actions and range preflop.
  - <strong>Postflop:</strong> Analyze their behavior on the flop, turn, and river.
  - <strong>Metrics:</strong> (For opponents) Provide estimates like VPIP and Aggression Frequency.
  - <strong>Strategic Leaks & Tilt Detection:</strong> Highlight any observable weaknesses or signs of emotional play.
  - <strong>Exploitation Tips:</strong> Offer actionable strategies for how the user can exploit these tendencies.
  - <strong>Additional Insights:</strong> Include any extra information that deepens the strategic analysis, specifically addressing board texture, stack sizes, and positional dynamics.


5. CRITICAL - MATCHING EXISTING PLAYERS:
   - If a player name in the transcript seems to match or is similar to one in the available players list, ALWAYS use the EXACT name from the list
   - Even if there are slight spelling variations or differences in case, use the exact name from the available players list
   - This ensures consistent player tracking across multiple recordings
   - The list of available players is: {available_players}

JSON FORMAT:
{{
  "players": [
    {{
      "playername": "ExactPlayerName",
      "description_text": "Player Name had [cards if known]. Their preflop strategy was [tight/loose/balanced]. Postflop they played [aggressive/passive/balanced]. Key metrics: VPIP ~[X]%, Aggression ~[Y]%. Strategic leaks include [specific weaknesses]. Signs of tilt: [emotional patterns]. Exploitation strategy: [specific recommendations]. Board texture impact: [analysis]. Stack dynamics: [considerations]. Position influence: [observations].",
        "description_html": "<p><strong>Preflop:</strong> Lucas limped in, suggesting a moderate range.</p><p><strong>Postflop:</strong> He raised on the flop and later went all-in on the river, indicating opportunistic aggression.</p><p><strong>Metrics:</strong> VPIP appears moderate to low with inconsistent aggression.</p><p><strong>Strategic Leaks & Tilt Detection:</strong> The sudden all-in on the river hints at potential tilt or mis-timed aggression.</p><p><strong>Exploitation Tips:</strong> Value bet strong hands and apply pressure on later streets when Lucas hesitates.</p><p><strong>Additional Insights:</strong> His play on a board that favors connected ranges, combined with his position and potential short stack dynamics, suggests exploitable weaknesses in his decision-making.</p>"
    }}
  ]
}}

Example output for a player might look like:
- Player had limped preflop, suggesting a moderate range
- Raised on the flop and later went all-in on the river, indicating opportunistic aggression
- VPIP appears moderate to low with inconsistent aggression
- The sudden all-in on the river hints at potential tilt or mis-timed aggression
- Exploitation recommendation: Value bet strong hands and apply pressure on later streets

Transcript:
{transcript}

IMPORTANT: Return ONLY valid JSON! No explanation text before or after.

Objective:
Deliver a comprehensive, HTML-enhanced analysis that allows the user to quickly grasp each player's tendencies and adjust their strategy accordingly.
"""

async def get_available_players(user_id: str) -> List[Dict[str, str]]:
    """Get all available players for a user"""
    try:
        players = await players_collection.find({"user_id": user_id}).to_list(length=100)
        return [{"id": str(player["_id"]), "name": player["name"]} for player in players]
    except Exception as e:
        print(f"Error getting available players: {e}")
        return []

async def create_or_update_player(user_id, player_name, player_data=None):
    """Create a new player or update an existing one."""
    try:
        if not player_name:
            print("[PLAYER] Skipping player with empty name")
            return None, None
            
        # First try to find an exact match
        existing_player = await players_collection.find_one({
            "user_id": user_id,
            "name": player_name
        })
        
        # If no exact match, try case-insensitive match
        if not existing_player:
            all_user_players = await players_collection.find({"user_id": user_id}).to_list(length=None)
            
            # Manual case-insensitive matching in Python
            player_name_lower = player_name.lower()
            for player in all_user_players:
                if player.get("name", "").lower() == player_name_lower:
                    existing_player = player
                    break
        
        if existing_player:
            print(f"[PLAYER] Updating existing player: {player_name}")
            
            # Update fields if player_data is provided
            if player_data:
                update_data = {
                    "$set": {
                        "updated_at": datetime.now()
                    }
                }
                
                # Add other fields from player_data - EXCLUDE analysis-specific fields
                # that should only be in player_notes collection
                excluded_fields = ["_id", "user_id", "name", "notes", "note_id", "player_note_id", 
                                 "description_text", "description_html", "playername"]
                
                for key, value in player_data.items():
                    if key not in excluded_fields:
                        update_data["$set"][key] = value
                
                # Add the note ID to the notes array if it's not already present
                if "note_id" in player_data and "player_note_id" in player_data:
                    update_data["$addToSet"] = {
                        "notes": {
                            "note_id": str(player_data["note_id"]), 
                            "player_note_id": str(player_data["player_note_id"])
                        }
                    }
                
                result = await players_collection.update_one(
                    {"_id": existing_player["_id"]},
                    update_data
                )
                
                return existing_player["_id"], True
            
            return existing_player["_id"], False
        else:
            print(f"[PLAYER] Creating new player: {player_name}")
            # Create new player document
            new_player = {
                "user_id": user_id,
                "name": player_name,
                "notes": [],
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            }
            
            # Add player_data fields if provided
            if player_data:
                if "note_id" in player_data and "player_note_id" in player_data:
                    new_player["notes"].append({
                        "note_id": str(player_data["note_id"]),
                        "player_note_id": str(player_data["player_note_id"])
                    })
                
                # Add other fields from player_data - EXCLUDE analysis-specific fields
                # that should only be in player_notes collection
                excluded_fields = ["_id", "user_id", "name", "notes", "note_id", "player_note_id", 
                                 "description_text", "description_html", "playername"]
                
                for key, value in player_data.items():
                    if key not in excluded_fields:
                        new_player[key] = value
            
            # Verify one last time that we don't already have this player with different case
            player_name_lower = player_name.lower()
            existing_players = await players_collection.find({"user_id": user_id}).to_list(length=None)
            for existing in existing_players:
                if existing.get("name", "").lower() == player_name_lower:
                    # We found a match, so use that player instead of creating a new one
                    print(f"[PLAYER] Found existing player with different case: {existing['name']}")
                    
                    # Update notes if needed
                    if player_data and "note_id" in player_data and "player_note_id" in player_data:
                        await players_collection.update_one(
                            {"_id": existing["_id"]},
                            {"$addToSet": {
                                "notes": {
                                    "note_id": str(player_data["note_id"]),
                                    "player_note_id": str(player_data["player_note_id"])
                                }
                            }}
                        )
                    
                    return existing["_id"], True
            
            # If we reach here, it's safe to insert the new player
            result = await players_collection.insert_one(new_player)
            return result.inserted_id, True
    
    except Exception as e:
        print(f"[PLAYER] Error in create_or_update_player: {str(e)}")
        print(f"[PLAYER] Traceback: {traceback.format_exc()}")
        return None, False

async def analyze_players_in_note(note_id: str, user_id: str, retry_count: int = 3) -> Dict[str, Any]:
    """Analyze players in a note using GPT-4o and store the results"""
    try:
        # Get the note
        note_obj_id = ObjectId(note_id)
        # Try to find the note with the user_id as is (UUID format)
        note = await notes_collection.find_one({"_id": note_obj_id, "user_id": user_id})
        
        # If not found, try with ObjectId conversion as fallback (for backward compatibility)
        if not note:
            try:
                pass
            except:
                # If conversion fails, it's not an ObjectId format
                pass
                
        if not note:
            print(f"[ANALYSIS] Note not found: {note_id}")
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Get the transcript
        transcript = note.get("transcript", "")
        if not transcript:
            print(f"[ANALYSIS] No transcript found in note: {note_id}")
            return {"success": False, "message": "No transcript found in note"}
            
        # Get the user's language preference
        user = await db.users.find_one({"user_id": user_id})
        language = user.get("notes_language", "en") if user else "en"
        print(f"[ANALYSIS] Using language {language} for player analysis")
        
        # Get available players
        available_players = await get_available_players(user_id)
        player_names = [player["name"] for player in available_players]
        
        print(f"[ANALYSIS] Available players for user {user_id}: {player_names}")
        
        # Create the prompt with more emphasis on matching existing players
        prompt = PLAYER_ANALYSIS_PROMPT.format(
            transcript=transcript,
            available_players=", ".join(player_names)
        )
        
        # Try to get analysis from GPT with retries
        analysis_result = None
        raw_response = ""
        
        for attempt in range(retry_count):
            print(f"[ANALYSIS] Attempt {attempt+1} to analyze players with GPT-4o")
            
            # Call GPT-4o with the prompt
            raw_response = await get_gpt_response(
                prompt=prompt,
                system_message=f"You are a poker analysis expert. Analyze players from the transcript and return valid JSON. ALL content must be in {language}. If any player name matches or is similar to one in this list: {', '.join(player_names)}, use the exact name from the list."
            )
            
            # Try to parse JSON from the response
            try:
                # Clean the response first
                cleaned_result = raw_response.strip()
                if cleaned_result.startswith("```json"):
                    cleaned_result = cleaned_result.replace("```json", "", 1)
                    if cleaned_result.endswith("```"):
                        cleaned_result = cleaned_result[:-3]
                elif cleaned_result.startswith("```"):
                    cleaned_result = cleaned_result.replace("```", "", 1)
                    if cleaned_result.endswith("```"):
                        cleaned_result = cleaned_result[:-3]
                
                # Find the JSON part
                json_start = cleaned_result.find('{')
                json_end = cleaned_result.rfind('}')
                
                if json_start >= 0 and json_end > json_start:
                    cleaned_result = cleaned_result[json_start:json_end+1]
                
                # Parse the JSON
                analysis_result = json.loads(cleaned_result)
                print(f"[ANALYSIS] Successfully parsed JSON response")
                
                # Validate the result
                if "players" not in analysis_result or not isinstance(analysis_result["players"], list):
                    print(f"[ANALYSIS] Invalid response format (missing players array): {cleaned_result[:200]}")
                    analysis_result = None
                    continue
                
                # If we got valid JSON with players, break the loop
                if analysis_result.get("players"):
                    print(f"[ANALYSIS] Successfully parsed JSON with {len(analysis_result['players'])} players")
                    break
                else:
                    print(f"[ANALYSIS] Empty players list in response, retrying...")
                    analysis_result = None
                
            except json.JSONDecodeError as e:
                print(f"[ANALYSIS] JSON decode error on attempt {attempt+1}: {e}")
                print(f"[ANALYSIS] Attempted to parse: {raw_response[:200]}...")
                await asyncio.sleep(2)  # Wait before retrying
            except Exception as e:
                print(f"[ANALYSIS] Error in GPT analysis attempt {attempt+1}: {e}")
                await asyncio.sleep(2)  # Wait before retrying
        
        # If we failed to get a valid analysis, create a fallback
        if not analysis_result:
            print(f"[ANALYSIS] Failed to get valid analysis after {retry_count} attempts. Creating fallback analysis.")
            
            # Create a very simple fallback analysis by looking for potential player names in the transcript
            words = transcript.split()
            potential_players = []
            
            for word in words:
                # Simple heuristic: words that start with uppercase and aren't common words might be names
                if word and word[0].isupper() and len(word) > 2 and word.lower() not in ["the", "and", "but", "for", "with"]:
                    potential_players.append(word)
            
            # Remove duplicates
            potential_players = list(set(potential_players))
            
            # Create a fallback analysis
            analysis_result = {
                "players": [
                    {
                        "playername": player,
                        "description_text": f"{player} appeared in the transcript but no detailed analysis could be generated.",
                        "description_html": f"<p><strong>{player}</strong> appeared in the transcript but no detailed analysis could be generated.</p>"
                    } for player in potential_players[:5]  # Limit to first 5 potential players
                ]
            }
            
            print(f"[ANALYSIS] Created fallback analysis with {len(analysis_result['players'])} potential players")
        
        # Now process each player from the analysis
        player_notes = []
        print(f"[ANALYSIS] Processing {len(analysis_result.get('players', []))} players from analysis")
        
        # Create a mapping of player names for exact case matching
        # We'll use a database query for matching instead of a map
        
        for player_data in analysis_result.get("players", []):
            try:
                # Extract player name from the analysis
                raw_player_name = player_data.get("playername", "").strip()
                if not raw_player_name:
                    print(f"[ANALYSIS] Skipping player with empty name")
                    continue
                
                # Set player name
                player_name = raw_player_name
                
                # Find if this matches an existing player (case-insensitive)
                existing_player = await players_collection.find_one({
                    "user_id": user_id,
                    "name": {"$regex": f"^{re.escape(raw_player_name)}$", "$options": "i"}
                })
                
                if existing_player:
                    # Use the existing name with its original case
                    player_name = existing_player["name"]
                    print(f"[ANALYSIS] Matched player name '{raw_player_name}' to existing player '{player_name}'")
                
                # Create or update the player record
                player_id, is_new = await create_or_update_player(user_id, player_name, player_data)
                if not player_id:
                    print(f"[ANALYSIS] Failed to create/update player: {player_name}")
                    continue
                
                # Create player note document
                player_note = {
                    "user_id": user_id,
                    "player_id": player_id,
                    "note_id": note_obj_id,
                    "player_name": player_name,
                    "description_text": player_data.get("description_text", ""),
                    "description_html": player_data.get("description_html", ""),
                    "createdAt": datetime.utcnow(),
                    "updatedAt": datetime.utcnow()
                }
                
                # Insert into players_notes collection
                result = await players_notes_collection.insert_one(player_note)
                player_note_id = result.inserted_id
                print(f"[ANALYSIS] Created player note with ID: {player_note_id}")
                
                # Update the player record to add this player_note_id and note_id
                # Create player data with player note ID for proper linking
                updated_player_data = {"player_note_id": player_note_id, "note_id": note_obj_id}
                await players_collection.update_one(
                    {"_id": player_id},
                    {"$push": {"notes": {"player_note_id": str(player_note_id), "note_id": str(note_obj_id)}}}
                )
                print(f"[ANALYSIS] Linked player note ID {player_note_id} to player {player_id}")
                
                # Add formatted player note to results
                formatted_player_note = {
                    "id": str(player_note_id),
                    "player_id": str(player_id),
                    "player_name": player_name,
                    "players_notes_count": 1,  # Set to 1 for newly created player notes
                    "description_text": player_data.get("description_text", ""),
                    "description_html": player_data.get("description_html", ""),
                    "created_at": datetime.utcnow().isoformat()
                }
                player_notes.append(formatted_player_note)
                
            except Exception as e:
                print(f"[ANALYSIS] Error processing player {player_data.get('playername', 'unknown')}: {e}")
                print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
        
        return {
            "success": True,
            "player_notes": player_notes
        }
    
    except Exception as e:
        print(f"[ANALYSIS] Error analyzing players in note: {e}")
        print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "message": str(e),
            "player_notes": []
        }

@router.post("/notes/{note_id}/analyze-players")
async def analyze_players_endpoint(note_id: str, user_id: str = Header(None)):
    """Endpoint to analyze players in a note"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")
            
        print(f"[API] Analyzing players in note {note_id} for user {user_id}")
        
        result = await analyze_players_in_note(note_id, user_id)
        return result
        
    except HTTPException as e:
        # Pass through HTTP exceptions
        raise
    except Exception as e:
        print(f"[API] Error in analyze_players_endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/notes/{note_id}/player-notes")
async def get_player_notes(note_id: str, user_id: str = Header(None)):
    """Get all player notes for a specific note"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
            
        # Convert string ID to ObjectId
        note_obj_id = ObjectId(note_id)
        
        # Get the note to ensure it exists and belongs to this user
        note = await notes_collection.find_one({
            "_id": note_obj_id,
            "user_id": user_id
        })
        
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
            
        # Get all player notes for this note
        player_notes = await players_notes_collection.find({
            "note_id": note_obj_id,
            "user_id": user_id
        }).sort("createdAt", -1).to_list(length=100)  # Sort by createdAt in descending order (newest first)
        
        # Get all player IDs
        player_ids = [ObjectId(note["player_id"]) for note in player_notes if "player_id" in note]
        
        # Get all players
        players = []
        if player_ids:
            players = await players_collection.find({
                "_id": {"$in": player_ids}
            }).to_list(length=100)
            
            # Create a map of player IDs to player objects for quick lookup
            player_map = {str(player["_id"]): player for player in players}
        
        # Format the results
        formatted_player_notes = []
        for player_note in player_notes:
            player_id = str(player_note["player_id"]) if "player_id" in player_note else None
            player = player_map.get(player_id, {}) if player_id else {}
            
            formatted_player_note = {
                "id": str(player_note["_id"]),
                "player_id": player_id,
                "player_name": player_note.get("player_name", "Unknown Player"),
                "players_notes_count": player.get("players_notes_count", 0),
                "description_text": player_note.get("description_text", ""),
                "description_html": player_note.get("description_html", ""),
                "created_at": player_note.get("createdAt", datetime.utcnow()).isoformat()
            }
            formatted_player_notes.append(formatted_player_note)
        
        return {
            "note_id": note_id,
            "player_notes": formatted_player_notes
        }
        
    except Exception as e:
        print(f"[API] Error getting player notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/players/{player_id}/notes")
async def get_notes_for_player(player_id: str, user_id: str = Header(None)):
    """Get all notes for a specific player"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
            
        # Convert string ID to ObjectId
        player_obj_id = ObjectId(player_id)
        
        # Get the player to ensure it exists and belongs to this user
        player = await players_collection.find_one({
            "_id": player_obj_id,
            "user_id": user_id
        })
        
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
            
        # Get all player notes through the embedded notes array in the player document
        player_note_ids = [ObjectId(note["player_note_id"]) for note in player.get("notes", [])]
        
        # If there are no notes, return an empty array
        if not player_note_ids:
            return {
                "player_id": player_id,
                "player_name": player["name"],
                "notes": []
            }
            
        # Fetch all player notes in one query
        player_notes = await players_notes_collection.find({
            "_id": {"$in": player_note_ids}
        }).to_list(length=100)
        
        # For each player note, get the associated note
        result_notes = []
        for player_note in player_notes:
            # Get the original note
            note = await notes_collection.find_one({"_id": player_note["note_id"]})
            if note:
                result_notes.append({
                    "id": str(player_note["_id"]),
                    "note_id": str(note["_id"]),
                    "date": player_note.get("createdAt", datetime.utcnow()).isoformat(),
                    "transcript": note.get("transcript", "")[:100] + "...",
                    "summary": note.get("summary", "")[:100] + "...",
                    "description_text": player_note.get("description_text", ""),
                    "description_html": player_note.get("description_html", "")
                })
        
        # Sort the notes by date (newest first)
        result_notes.sort(key=lambda x: x["date"], reverse=True)
        
        return {
            "player_id": player_id,
            "player_name": player["name"],
            "notes": result_notes
        }
            
    except Exception as e:
        print(f"[API] Error getting notes for player: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/players")
async def get_players(user_id: str = Header(None), limit: int = 100, skip: int = 0):
    """Get all players for a user with pagination"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
            
        # Query to get players for this user
        total_count = await players_collection.count_documents({"user_id": user_id})
        
        # Get players with pagination, sorted by players_notes_count (most frequent first)
        players_cursor = players_collection.find({"user_id": user_id}) \
            .sort("players_notes_count", -1) \
            .skip(skip) \
            .limit(limit)
            
        # Convert cursor to list
        players = await players_cursor.to_list(length=limit)
        
        # Format the results
        formatted_players = []
        for player in players:
            formatted_player = {
                "id": str(player["_id"]),
                "name": player["name"],
                "players_notes_count": player.get("players_notes_count", 0),
                "note_count": len(player.get("notes", [])),
                "first_seen": player.get("createdAt", datetime.utcnow()).isoformat(),
                "last_updated": player.get("updatedAt", datetime.utcnow()).isoformat()
            }
            formatted_players.append(formatted_player)
        
        return {
            "total_count": total_count,
            "limit": limit,
            "skip": skip,
            "players": formatted_players
        }
    
    except Exception as e:
        print(f"[API] Error in get_players: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/players/{player_id}/statistics")
async def get_player_statistics(player_id: str, user_id: str = Header(None)):
    """Get statistics and data for a specific player"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
            
        # Convert string ID to ObjectId
        player_obj_id = ObjectId(player_id)
        
        # Get the player to ensure it exists and belongs to this user
        player = await players_collection.find_one({
            "_id": player_obj_id,
            "user_id": user_id
        })
        
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
            
        player_name = player["name"]
        players_notes_count = player.get("players_notes_count", 0)
        first_seen = player.get("createdAt", datetime.utcnow()).isoformat()
        most_recent = player.get("updatedAt", datetime.utcnow()).isoformat()
        
        # Get statistics from the notes array
        note_count = len(player.get("notes", []))
        
        # If there are no notes, return basic statistics
        if note_count == 0:
            return {
                "player_id": player_id,
                "player_name": player_name,
                "statistics": {
                    "players_notes_count": players_notes_count,
                    "note_count": note_count,
                    "first_seen": first_seen,
                    "most_recent": most_recent,
                    "tendencies": [],
                    "common_words": []
                }
            }
            
        # Get player notes for detailed analysis
        player_note_ids = [ObjectId(note["player_note_id"]) for note in player.get("notes", [])]
        player_notes = await players_notes_collection.find({
            "_id": {"$in": player_note_ids}
        }).to_list(length=100)
        
        # Analyze descriptions for common words and tendencies
        all_text = " ".join([note.get("description_text", "") for note in player_notes])
        
        # Extract common words (excluding stop words)
        stop_words = ["the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", 
                      "by", "about", "as", "of", "was", "were", "is", "are", "player", "had", "has", 
                      "their", "they", "this", "that", "these", "those", "would", "could", "should"]
        
        words = all_text.lower().replace(".", " ").replace(",", " ").replace("!", " ").replace("?", " ").split()
        word_counts = {}
        
        for word in words:
            if len(word) > 3 and word not in stop_words:
                word_counts[word] = word_counts.get(word, 0) + 1
                
        # Sort by frequency and get top 10
        common_words = [{"word": word, "count": count} 
                        for word, count in sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:10]]
        
        # Look for tendencies (sentences with keywords)
        tendency_keywords = ["tendency", "tendencies", "habit", "habits", "pattern", "patterns", 
                             "style", "styles", "play", "plays", "strategy", "strategies", 
                             "approach", "approaches", "watch for", "look for"]
        
        tendencies = []
        for note in player_notes:
            text = note.get("description_text", "")
            sentences = text.split(".")
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                    
                # Check if sentence contains any tendency keyword
                if any(keyword in sentence.lower() for keyword in tendency_keywords):
                    # Don't add duplicate tendencies
                    if sentence not in tendencies:
                        tendencies.append(sentence)
        
        # Limit to top 5 tendencies
        tendencies = tendencies[:5]
        
        return {
            "player_id": player_id,
            "player_name": player_name,
            "statistics": {
                "players_notes_count": players_notes_count,
                "note_count": note_count,
                "first_seen": first_seen,
                "most_recent": most_recent,
                "tendencies": tendencies,
                "common_words": common_words
            }
        }
            
    except Exception as e:
        print(f"[API] Error getting statistics for player: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
@router.post("/analyze-recent-notes")
async def analyze_recent_notes(user_id: str = Header(None), limit: int = 10):
    """Analyze the most recent notes for comprehensive player insights"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")
            
        # Get notes without player notes
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$lookup": {
                "from": "players_notes",
                "localField": "_id",
                "foreignField": "note_id",
                "as": "player_notes"
            }},
            {"$match": {"player_notes": {"$size": 0}}},  # Notes with no player notes
            {"$sort": {"createdAt": -1}},
            {"$limit": limit}
        ]
        
        notes = await notes_collection.aggregate(pipeline).to_list(length=limit)
        
        if not notes:
            return {
                "success": True,
                "message": "No notes found that need analysis",
                "notes_analyzed": 0
            }
            
        # Start analysis for each note
        analysis_tasks = []
        for note in notes:
            analysis_tasks.append(analyze_players_in_note(str(note["_id"]), user_id))
            
        # Wait for all analyses to complete
        results = await asyncio.gather(*analysis_tasks)
        
        # Count successful analyses
        successful = sum(1 for result in results if result.get("success", False))
        
        return {
            "success": True,
            "message": f"Analysis complete for {successful} out of {len(notes)} notes",
            "notes_analyzed": successful
        }
        
    except Exception as e:
        print(f"[ANALYSIS] Error analyzing recent notes: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 