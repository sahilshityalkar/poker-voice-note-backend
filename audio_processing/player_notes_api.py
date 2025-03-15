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
from pymongo import TEXT, ASCENDING
import sys

# Add parent directory to path to allow imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import the get_database_connection function
from database import get_database_connection

# Define the logger
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

router = APIRouter()

# MongoDB setup - Use the new connection function
MONGODB_URL = os.getenv("DATABASE_URL")
# Create a fresh connection with the current event loop
client = get_database_connection()
db = client.pokernotes

# Collections
players_collection = db.players
notes_collection = db.notes
players_notes_collection = db.players_notes

# Export collections for direct import
__all__ = ['players_collection', 'notes_collection', 'players_notes_collection', 'db']

# Function to get a fresh database connection with the current event loop
def get_fresh_connection(loop=None):
    """Get a fresh database connection with the current event loop or a provided one"""
    try:
        # Import the function to avoid circular imports
        from database import get_database_connection
        
        # Get a fresh connection with the specified loop or current one
        fresh_client = get_database_connection(loop)
        fresh_db = fresh_client.pokernotes
        
        # Return updated collections
        return {
            'client': fresh_client,
            'db': fresh_db,
            'players': fresh_db.players,
            'notes': fresh_db.notes,
            'players_notes': fresh_db.players_notes
        }
    except Exception as e:
        print(f"[DB] Error getting fresh connection: {e}")
        # Fall back to existing connection
        return {
            'client': client,
            'db': db,
            'players': players_collection,
            'notes': notes_collection,
            'players_notes': players_notes_collection
        }

# Set up indexes for better performance
async def ensure_indexes():
    """Create indexes for collections used in this module"""
    try:
        # Create text index on description_text field in player_notes collection
        await players_notes_collection.create_index([("description_text", TEXT)])
        print("[DB] Created text index on description_text in player_notes collection")
        
        # Create index on user_id and player_id in player_notes collection
        await players_notes_collection.create_index([("user_id", ASCENDING), ("player_id", ASCENDING)])
        print("[DB] Created index on user_id and player_id in player_notes collection")
        
        # Create index on note_id in player_notes collection
        await players_notes_collection.create_index([("note_id", ASCENDING)])
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

# Instead of calling asyncio.create_task directly, create a setup function
# that can be called from FastAPI startup event
async def setup_indexes():
    await ensure_indexes()

# Player analysis prompt template
PLAYER_ANALYSIS_PROMPT = """
You are a top-level professional quality poker analysis and educator 
Analyze the entire poker hand history transcript from the user's perspective and extract every insightful detail regarding all players involved. Focus on capturing both the strategic and emotional dimensions of each player's play.

IMPORTANT INSTRUCTION: Your ENTIRE response including ALL player names, descriptions, and analysis MUST be in {language}. Do NOT use any English in your response.

Specifically:

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
- "description_text": A concise yet compelling text-formatted summary that includes only the relevant fields. Ensure your text covers the following strong sections. This MUST be in {language}.
- "description_html": A concise yet compelling HTML-formatted summary that includes only the relevant fields. Ensure your HTML covers the following strong sections. This MUST be in {language}:
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

REMEMBER: ALL content MUST be in {language}. This includes player names, descriptions (both text and HTML), analysis - everything.

Example output for a player might look like:
- Player had limped preflop, suggesting a moderate range
- Raised on the flop and later went all-in on the river, indicating opportunistic aggression
- VPIP appears moderate to low with inconsistent aggression
- The sudden all-in on the river hints at potential tilt or mis-timed aggression
- Exploitation recommendation: Value bet strong hands and apply pressure on later streets

Transcript:
{transcript}

IMPORTANT: Return ONLY valid JSON! No explanation text before or after. ALL content MUST be in {language}.

Objective:
Deliver a comprehensive, HTML-enhanced analysis that allows the user to quickly grasp each player's tendencies and adjust their strategy accordingly.
"""

# Follow-up player analysis prompt template to find any missed players
PLAYER_ANALYSIS_FOLLOWUP_PROMPT = """
You are a top-level professional quality poker analysis and educator. Your task is to review a poker transcript and VERIFY that ALL players have been identified correctly in the initial analysis.

IMPORTANT INSTRUCTION: Your ENTIRE response including ALL player names, descriptions, and analysis MUST be in {language}. Do NOT use any English in your response.

FIRST ANALYSIS RESULTS:
{first_analysis}

Original Transcript:
{transcript}

CRITICAL TASK: Review the transcript carefully and identify ANY players that might have been missed in the first analysis.

Focus on these potential reasons for missed players:
1. Names mentioned only once or briefly
2. Unusual or misspelled player names
3. Indirect references to players
4. Players mentioned in complex contexts
5. Names that might be confused with other terms
6. Referenced players who didn't take obvious actions

Return a valid JSON object containing only a "missed_players" array (empty if none found):
```json
{{
  "missed_players": [
    {{
      "playername": "Player Name",
      "description_text": "Detailed plain text analysis in {language} (500-800 chars)",
      "description_html": "The same analysis in {language} with HTML formatting <strong>tags</strong>"
    }}
  ]
}}
```

If no missed players are found, return:
```json
{{
  "missed_players": []
}}
```

REMEMBER: ALL content MUST be in {language}. This includes player names, descriptions (both text and HTML), analysis - everything.

ONLY return valid JSON with a 'missed_players' array.
"""

async def get_available_players(user_id: str) -> List[Dict[str, str]]:
    """Get all available players for a user"""
    try:
        players = await players_collection.find({"user_id": user_id}).to_list(length=100)
        return [{"id": str(player["_id"]), "name": player["name"]} for player in players]
    except Exception as e:
        print(f"Error getting available players: {e}")
        return []

async def create_or_update_player(user_id, player_name, player_data=None, custom_collection=None):
    """
    Create a new player if it doesn't exist or update an existing one
    
    Args:
        user_id: User ID
        player_name: Player name to create or update
        player_data: Optional additional player data
        custom_collection: Optional custom players collection to use (for fresh connections)
    
    Returns:
        Tuple of (player_id, is_new) where is_new is True if player was created, False if updated
    """
    try:
        # Use the provided collection or fall back to global
        p_collection = custom_collection if custom_collection is not None else players_collection
        
        # Clean player name
        player_name = player_name.strip()
        if not player_name:
            print(f"[PLAYER] Invalid player name: {player_name}")
            return None, False
            
        # Try to find the player by name
        existing_player = await p_collection.find_one({
            "user_id": user_id,
            "name": {"$regex": f"^{re.escape(player_name)}$", "$options": "i"}
        })
        
        is_new = False
        current_time = datetime.utcnow()
        
        if existing_player:
            # Update existing player
            player_id = existing_player["_id"]
            print(f"[PLAYER] Updating existing player: {player_name} ({player_id})")
            
            # Default update data
            update_data = {
                "updated_at": current_time
            }
            
            # Add any additional player data
            if player_data:
                for key, value in player_data.items():
                    if key not in ["_id", "user_id", "name", "created_at"]:
                        update_data[key] = value
            
            # Update the player
            await p_collection.update_one(
                {"_id": player_id},
                {"$set": update_data}
            )
        else:
            # Create new player
            is_new = True
            print(f"[PLAYER] Creating new player: {player_name}")
            
            # Default player document
            player_doc = {
                "user_id": user_id,
                "name": player_name,
                "created_at": current_time,
                "updated_at": current_time,
                "notes": []
            }
            
            # Add any additional player data
            if player_data:
                for key, value in player_data.items():
                    if key not in ["_id", "user_id", "name", "created_at"]:
                        player_doc[key] = value
            
            # Insert the player
            result = await p_collection.insert_one(player_doc)
            player_id = result.inserted_id
            
        return player_id, is_new
    except Exception as e:
        print(f"[PLAYER] Error in create_or_update_player: {e}")
        traceback.print_exc()
        print(f"[PLAYER] Traceback: {traceback.format_exc()}")
        return None, False

def parse_gpt_player_response(raw_response: str) -> Dict:
    """Parse the raw GPT response and extract JSON content"""
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
        
        # Validate the result - handle both "players" and "missed_players" format
        if "players" not in analysis_result and "missed_players" not in analysis_result:
            print(f"[ANALYSIS] Invalid response format (missing players or missed_players array): {cleaned_result[:200]}")
            # Create a default structure with empty arrays
            analysis_result = {"players": [], "missed_players": []}
        
        # Ensure "players" exists even if only "missed_players" is in the response
        if "players" not in analysis_result:
            analysis_result["players"] = []
            
        # Ensure "missed_players" exists even if only "players" is in the response
        if "missed_players" not in analysis_result:
            analysis_result["missed_players"] = []
            
        return analysis_result
    
    except json.JSONDecodeError as e:
        print(f"[ANALYSIS] JSON decode error: {e}")
        print(f"[ANALYSIS] Attempted to parse: {raw_response[:200]}...")
        # Return empty result on failure
        return {"players": [], "missed_players": []}
    
    except Exception as e:
        print(f"[ANALYSIS] Error parsing GPT response: {e}")
        # Return empty result on failure
        return {"players": [], "missed_players": []}

async def analyze_players_in_note(note_id: str, user_id: str, retry_count: int = 3, is_update: bool = False, loop=None) -> Dict[str, Any]:
    """
    Analyze players in a note using GPT-4o and store the results
    
    Args:
        note_id: The ID of the note to analyze
        user_id: The user ID of the note owner
        retry_count: Number of retries for GPT calls
        is_update: Whether this is being called during a transcript update
                  (if True, matching to existing players is skipped)
        loop: Optional event loop to use (to prevent using different loops)
    """
    try:
        # Log start of player analysis
        print(f"[PLAYERS] Starting player analysis for note {note_id} (is_update={is_update})")
        
        # Get fresh database connections for this operation - use provided loop if available
        print(f"[PLAYERS] Getting fresh database connections for note {note_id}")
        conn = get_fresh_connection(loop)
        p_collection = conn['players']
        pn_collection = conn['players_notes']
        n_collection = conn['notes']
        fresh_db = conn['db']
        
        # If this is an update, verify cleanup was done
        if is_update:
            # Double check that there are no existing player notes for this note
            existing_notes = await pn_collection.count_documents({"note_id": note_id})
            if existing_notes > 0:
                print(f"[PLAYERS] WARNING: Found {existing_notes} player notes for note {note_id} - should be 0 in update mode!")
                print(f"[PLAYERS] Ensuring cleanup of existing player notes")
                try:
                    # Emergency cleanup - should've been done already but just in case
                    await pn_collection.delete_many({"note_id": note_id})
                    
                    # Also check for any players still referencing this note
                    players_with_refs = await p_collection.find({"notes.note_id": note_id}).to_list(length=100)
                    for player in players_with_refs:
                        await p_collection.update_one(
                            {"_id": player["_id"]},
                            {"$pull": {"notes": {"note_id": note_id}}}
                        )
                    print(f"[PLAYERS] Emergency cleanup completed for {len(players_with_refs)} players")
                except Exception as ex:
                    print(f"[PLAYERS] Error during emergency cleanup: {ex}")
        
        # Get the note
        note_obj_id = ObjectId(note_id)
        # Try to find the note with the user_id as is (UUID format)
        note = await n_collection.find_one({"_id": note_obj_id, "user_id": user_id})
        
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
        user = await fresh_db.users.find_one({"user_id": user_id})
        language = user.get("notes_language", "en") if user else "en"
        print(f"[ANALYSIS] Using language {language} for player analysis")
        
        # Initialize player_names to empty list
        player_names = []
        
        # Get available players
        available_players = []
        if not is_update:
            # Only retrieve existing players when not updating
            available_players = await get_available_players(user_id)
            player_names = [player["name"] for player in available_players]
            print(f"[ANALYSIS] Available players for user {user_id}: {player_names}")
        else:
            # If this is an update, we don't want to match to existing players
            print(f"[ANALYSIS] Update mode: Not matching to existing players")
            
        # Create the prompt - without requiring matching to existing players during update
        if is_update:
            # For updates, don't try to match existing players but focus on extracting all players
            system_message = f"""You are a poker analysis expert. Your task is to extract and analyze ALL players mentioned in the transcript.
For each player:
1. Extract their exact name as mentioned
2. Analyze their play style, decisions, and strategic patterns
3. Return a detailed analysis in {language}

IMPORTANT: Extract EVERY player mentioned in the transcript, including those mentioned only once.
ALL content including HTML and plain text descriptions MUST be in {language}. Do not use English at all in your response.
Format your response as valid JSON with a 'players' array."""
        else:
            # For regular analysis, try to match to existing players
            system_message = f"You are a poker analysis expert. Analyze players from the transcript and return valid JSON. ALL content including player names, descriptions and HTML must be in {language}. Do not use English at all in your response. If any player name matches or is similar to one in this list: {', '.join(player_names)}, use the exact name from the list."
                
        prompt = PLAYER_ANALYSIS_PROMPT.format(
            transcript=transcript,
            available_players=", ".join(player_names) if player_names else "",
            language=language
        )
        
        # Try multiple times to get a valid GPT response with players
        for attempt in range(retry_count):
            try:
                # Get GPT response with poker analysis
                raw_response = await get_gpt_response(
                    prompt=prompt,
                    system_message=system_message
                )
                
                # Parse the JSON from the GPT response
                result_json = parse_gpt_player_response(raw_response)
                if result_json.get("players", []):
                    player_count = len(result_json.get("players", []))
                    print(f"[ANALYSIS] Successfully parsed JSON with {player_count} players")
                    
                    # Perform a follow-up analysis to find any missed players
                    print(f"[ANALYSIS] Performing follow-up analysis to find any missed players")
                    
                    try:
                        # Create a summary of the first analysis to include in the follow-up prompt
                        first_analysis_summary = json.dumps({"players": [{"playername": p["playername"]} for p in result_json.get("players", [])]})
                        
                        # Create the follow-up prompt
                        followup_prompt = PLAYER_ANALYSIS_FOLLOWUP_PROMPT.format(
                            first_analysis=first_analysis_summary,
                            transcript=transcript,
                            available_players=", ".join(player_names) if player_names else "",
                            language=language
                        )
                        
                        # Get follow-up GPT response with a timeout to prevent blocking
                        followup_raw_response = await asyncio.wait_for(
                            get_gpt_response(
                                prompt=followup_prompt,
                                system_message=f"You are a poker analysis expert. Your task is to find ANY missed players from the transcript that weren't caught in the first analysis. Return valid JSON. ALL content must be in {language}."
                            ),
                            timeout=60  # 60 second timeout for the follow-up request
                        )
                        
                        # Parse the follow-up response
                        followup_json = parse_gpt_player_response(followup_raw_response)
                        missed_players = followup_json.get("missed_players", [])
                        
                        if missed_players:
                            print(f"[ANALYSIS] Found {len(missed_players)} additional players in follow-up analysis")
                            
                            # Add the missed players to the original result
                            result_json["players"].extend(missed_players)
                            print(f"[ANALYSIS] Combined result now has {len(result_json['players'])} players")
                        else:
                            print(f"[ANALYSIS] No additional players found in follow-up analysis")
                    except asyncio.TimeoutError:
                        print(f"[ANALYSIS] Follow-up analysis timed out, continuing with original players")
                    except Exception as e:
                        print(f"[ANALYSIS] Error during follow-up analysis: {e}")
                        print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
                        print(f"[ANALYSIS] Continuing with original players")
                    
                    # Process the combined players result
                    player_notes = await process_players_analysis(result_json, note_id, user_id, transcript, is_update=is_update)
                    
                    # Return the result
                    return {
                        "success": True,
                        "player_notes": player_notes
                    }
                else:
                    if attempt < retry_count - 1:
                        print(f"[ANALYSIS] No players found in analysis attempt {attempt+1}, retrying...")
                        continue
                    else:
                        print(f"[ANALYSIS] No players found after {retry_count} attempts")
                        return {
                            "success": True,
                            "message": "No players identified in transcript",
                            "player_notes": []
                        }
            except json.JSONDecodeError as json_err:
                print(f"[ANALYSIS] JSON parse error on attempt {attempt+1}: {json_err}")
                if attempt < retry_count - 1:
                    continue
                else:
                    return {
                        "success": False,
                        "message": f"Failed to parse player analysis after {retry_count} attempts",
                        "error": str(json_err)
                    }
            except Exception as e:
                print(f"[ANALYSIS] Error processing player analysis on attempt {attempt+1}: {e}")
                traceback.print_exc()
                print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
                if attempt < retry_count - 1:
                    continue
                else:
                    return {
                        "success": False,
                        "message": f"Error processing player analysis after {retry_count} attempts",
                        "error": str(e)
                    }
                
    except Exception as e:
        print(f"[ANALYSIS] Error analyzing players in note: {e}")
        traceback.print_exc()
        print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
        return {
            "success": False,
            "message": str(e),
            "player_notes": []
        }

async def process_players_analysis(result: Dict, note_id: str, user_id: str, transcript: str, is_update: bool = False) -> List[Dict]:
    """Process the player analysis result and store player notes"""
    players = result.get("players", [])
    print(f"[ANALYSIS] Processing {len(players)} players from analysis")
    
    # Now process each player from the analysis
    player_notes = []

    # Get fresh connections for this operation
    print(f"[ANALYSIS] Getting fresh database connections for note {note_id}")
    conn = get_fresh_connection()
    p_collection = conn['players']
    pn_collection = conn['players_notes']
    
    # If this is an update, ensure all player references are properly deleted first
    # We're adding this as a double-check since the deletion in update_transcript_directly sometimes might not be complete
    if is_update:
        try:
            print(f"[ANALYSIS] Double-checking cleanup for note {note_id} (update mode)")
            
            # First ensure all player notes for this note are deleted
            delete_result = await pn_collection.delete_many({"note_id": note_id})
            print(f"[ANALYSIS] Deleted {delete_result.deleted_count} lingering player notes during double-check")
            
            # Also ensure all player references to this note are removed
            # Find players with references to this note
            players_with_refs = await p_collection.find(
                {"notes.note_id": note_id}
            ).to_list(length=100)
            
            if players_with_refs:
                print(f"[ANALYSIS] Found {len(players_with_refs)} players still referencing note {note_id}")
                for player in players_with_refs:
                    try:
                        # Remove references to this note from each player
                        await p_collection.update_one(
                            {"_id": player["_id"]},
                            {"$pull": {"notes": {"note_id": note_id}}}
                        )
                    except Exception as e:
                        print(f"[ANALYSIS] Error removing note reference from player {player['_id']}: {e}")
        except Exception as cleanup_ex:
            print(f"[ANALYSIS] Error during additional cleanup: {cleanup_ex}")
            # Continue with processing even if cleanup fails
    
    for player_data in players:
        try:
            # Extract player name from the analysis
            player_name = player_data.get("playername", "").strip()
            if not player_name:
                print(f"[ANALYSIS] Skipping player with missing name: {player_data}")
                continue
                
            # Extract descriptions, defaulting to empty strings if missing
            description_text = player_data.get("description_text", "").strip()
            description_html = player_data.get("description_html", "").strip()
            
            if not description_text:
                # Generate a basic description if none provided
                description_text = f"{player_name} appeared in this hand."
                description_html = f"<p>{player_name} appeared in this hand.</p>"
                
            # Match to existing player or create a new one
            player_id = None
            
            if is_update:
                # In update mode, we always create new player records
                print(f"[PLAYER] Creating new player: {player_name}")
                player_result = await create_or_update_player(user_id, player_name, custom_collection=p_collection)
                # Extract just the player_id from the tuple (player_id, is_new)
                player_id = player_result[0] if player_result and player_result[0] else None
            else:
                # Try to match to an existing player by name
                existing_players = await p_collection.find({"user_id": user_id, "name": {"$regex": f"^{re.escape(player_name)}$", "$options": "i"}}).to_list(length=1)
                
                if existing_players:
                    matched_player = existing_players[0]
                    player_id = matched_player["_id"]
                    print(f"[ANALYSIS] Matched player name '{player_name}' to existing player '{matched_player['name']}'")
                    print(f"[PLAYER] Updating existing player: {matched_player['name']}")
                else:
                    # Create new player
                    print(f"[PLAYER] Creating new player: {player_name}")
                    player_result = await create_or_update_player(user_id, player_name, custom_collection=p_collection)
                    # Extract just the player_id from the tuple (player_id, is_new)
                    player_id = player_result[0] if player_result and player_result[0] else None
            
            if not player_id:
                print(f"[ANALYSIS] Failed to create or match player: {player_name}")
                continue
                
            # Create the player note
            player_note_doc = {
                "user_id": user_id,
                "player_id": str(player_id),
                "player_name": player_name,
                "note_id": note_id,
                "description_text": description_text,
                "description_html": description_html,
                "created_at": datetime.utcnow()
            }
            
            # Insert the player note
            player_note_result = await pn_collection.insert_one(player_note_doc)
            player_note_id = player_note_result.inserted_id
            print(f"[ANALYSIS] Created player note with ID: {player_note_id}")
            
            # Update player document with link to this note
            note_ref = {
                "note_id": note_id,
                "player_note_id": str(player_note_id),
                "created_at": datetime.utcnow()
            }
            
            # Use the correct ObjectId for the player update
            await p_collection.update_one(
                {"_id": player_id},  # player_id is already an ObjectId
                {"$push": {"notes": note_ref}}
            )
            print(f"[ANALYSIS] Linked player note ID {player_note_id} to player {player_id}")
            
            # Add to the response
            player_notes.append({
                "id": str(player_note_id),
                "player_id": str(player_id),
                "player_name": player_name,
                "players_notes_count": 1,  # We don't have this info readily available
                "description_text": description_text,
                "description_html": description_html,
                "created_at": datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            print(f"[ANALYSIS] Error processing player {player_data.get('playername', 'unknown')}: {e}")
            traceback.print_exc()
            print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
    
    return player_notes

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
    """
    Analyze the most recent notes for a user.
    
    This will:
    1. Get the most recent notes for a user
    2. For each note, run the player analysis if it hasn't been run already
    
    Returns:
    - A list of notes with their analysis status
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Get the most recent notes for the user
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$sort": {"createdAt": -1}},
            {"$limit": limit}
        ]
        
        notes = await notes_collection.aggregate(pipeline).to_list(length=limit)
        results = []
        
        for note in notes:
            note_id = str(note["_id"])
            
            # Check if this note has already been analyzed
            player_notes = await players_notes_collection.find({"note_id": note["_id"]}).to_list(length=100)
            is_analyzed = len(player_notes) > 0
            
            if not is_analyzed:
                # Analyze the note
                try:
                    await analyze_players_in_note(note_id, user_id)
                    results.append({
                        "note_id": note_id,
                        "is_analyzed": True,
                        "message": "Analysis completed successfully"
                    })
                except Exception as e:
                    results.append({
                        "note_id": note_id,
                        "is_analyzed": False,
                        "message": f"Error analyzing note: {str(e)}"
                    })
            else:
                results.append({
                    "note_id": note_id,
                    "is_analyzed": True,
                    "message": "Note was already analyzed"
                })
        
        return {
            "success": True,
            "analyzed_notes": results
        }
        
    except Exception as e:
        print(f"Error analyzing recent notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/notes/user")
async def delete_all_user_notes(user_id: str = Header(None)):
    """
    Delete all notes and their associated player notes for a specific user.
    
    This will:
    1. Delete all records from the notes collection for the user
    2. Delete all records from the players_notes collection that reference those notes
    
    Returns:
    - Success message with counts of deleted notes
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Get all note IDs for this user
        user_notes = await notes_collection.find({"user_id": user_id}).to_list(length=1000)
        note_ids = [note["_id"] for note in user_notes]
        
        # Delete all player notes associated with these notes
        player_notes_delete_result = await players_notes_collection.delete_many({
            "user_id": user_id,
            "note_id": {"$in": note_ids}
        })
        
        # Delete all notes for this user
        notes_delete_result = await notes_collection.delete_many({
            "user_id": user_id
        })
        
        # Update player documents to remove references to deleted notes
        # This is a more complex operation, but we'll do a basic cleanup
        await players_collection.update_many(
            {"user_id": user_id},
            {"$pull": {"notes": {"note_id": {"$in": [str(note_id) for note_id in note_ids]}}}}
        )
        
        return {
            "success": True,
            "message": "All notes and associated player notes deleted successfully",
            "notes_deleted_count": notes_delete_result.deleted_count,
            "player_notes_deleted_count": player_notes_delete_result.deleted_count
        }
    
    except Exception as e:
        print(f"[DELETE] Error deleting all user notes: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete all user notes: {str(e)}")

@router.delete("/notes/{note_id}")
async def delete_specific_note(note_id: str, user_id: str = Header(None)):
    """
    Delete a specific note and its associated player notes.
    
    This will:
    1. Delete the note from the notes collection
    2. Delete all player notes that reference this note
    3. Update player documents to remove references to this note
    
    Returns:
    - Success message with counts of deleted notes
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Validate note_id format
        try:
            note_obj_id = ObjectId(note_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid note ID format")
        
        # Check if note exists and belongs to user
        note = await notes_collection.find_one({"_id": note_obj_id, "user_id": user_id})
        if not note:
            raise HTTPException(status_code=404, detail="Note not found or does not belong to this user")
        
        # Delete all player notes associated with this note
        player_notes_delete_result = await players_notes_collection.delete_many({
            "note_id": note_obj_id,
            "user_id": user_id
        })
        
        # Delete the note
        note_delete_result = await notes_collection.delete_one({
            "_id": note_obj_id,
            "user_id": user_id
        })
        
        # Update player documents to remove references to this note
        await players_collection.update_many(
            {"user_id": user_id},
            {"$pull": {"notes": {"note_id": note_id}}}
        )
        
        return {
            "success": True,
            "message": f"Note and associated player notes deleted successfully",
            "note_deleted": note_delete_result.deleted_count > 0,
            "player_notes_deleted_count": player_notes_delete_result.deleted_count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error deleting note: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete note: {str(e)}")

@router.delete("/notes/{note_id}/note-only")
async def delete_note_only(note_id: str, user_id: str = Header(None)):
    """
    Delete a specific note WITHOUT deleting its associated player notes.
    
    This will:
    1. Delete ONLY the note from the notes collection
    2. Leave all player notes and player references intact
    
    This is useful when you want to remove a note but keep the player analysis data.
    
    Returns:
    - Success message confirming note deletion
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Validate note_id format
        try:
            note_obj_id = ObjectId(note_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid note ID format")
        
        # Check if note exists and belongs to user
        note = await notes_collection.find_one({"_id": note_obj_id, "user_id": user_id})
        if not note:
            raise HTTPException(status_code=404, detail="Note not found or does not belong to this user")
        
        # Delete ONLY the note itself
        note_delete_result = await notes_collection.delete_one({
            "_id": note_obj_id,
            "user_id": user_id
        })
        
        return {
            "success": True,
            "message": f"Note deleted successfully (player notes preserved)",
            "note_deleted": note_delete_result.deleted_count > 0
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DELETE] Error deleting note only: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete note: {str(e)}")

@router.delete("/notes/user/notes-only")
async def delete_all_user_notes_only(user_id: str = Header(None)):
    """
    Delete all notes for a specific user WITHOUT deleting any associated player notes.
    
    This will:
    1. Delete ONLY the notes from the notes collection
    2. Leave all player notes and player references intact
    
    This is useful when you want to clear a user's note history but preserve all player analysis data.
    
    Returns:
    - Success message with count of deleted notes
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required")
        
        # Delete all notes for this user
        notes_delete_result = await notes_collection.delete_many({
            "user_id": user_id
        })
        
        return {
            "success": True,
            "message": "All notes deleted successfully (player notes preserved)",
            "notes_deleted_count": notes_delete_result.deleted_count
        }
    
    except Exception as e:
        print(f"[DELETE] Error deleting all user notes only: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete all user notes: {str(e)}") 