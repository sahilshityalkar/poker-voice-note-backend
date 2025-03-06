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

# Player analysis prompt template
PLAYER_ANALYSIS_PROMPT = """
You are a professional poker analyst. Extract players and provide detailed analysis from this poker transcript.

INSTRUCTIONS:
1. Identify ALL player names mentioned in the transcript (be thorough)
2. For each player, provide a detailed, structured analysis
3. Format your response as valid JSON only!

JSON FORMAT:
{{
  "players": [
    {{
      "playername": "PlayerName",
      "description_text": "Player Name had [cards if known]. Their play was [aggressive/passive/balanced]. They made good decisions by [specific actions]. Their mistakes included [specific mistakes]. Next time, watch for [tendencies]. Against this player, consider [counter-strategy].",
      "description_html": "<p><strong>Player Name</strong> had <em>[cards if known]</em>.</p><p>Their play was <em>[aggressive/passive/balanced]</em>.</p><ul><li><strong>Strengths:</strong> [good decisions]</li><li><strong>Weaknesses:</strong> [mistakes]</li><li><strong>Watch for:</strong> [tendencies]</li><li><strong>Counter-strategy:</strong> [how to play against them]</li></ul>"
    }}
  ]
}}

Available players in database (use exact names if they appear): {available_players}

IMPORTANT DETAILS:
- Be thorough in finding ALL players mentioned
- Include even briefly mentioned players
- Limit to real player names (not positions like "button" or "BB")
- If names are unclear but someone is mentioned, use their apparent role

Transcript:
{transcript}

IMPORTANT: Return ONLY valid JSON! No explanation text before or after.
"""

async def get_available_players(user_id: str) -> List[Dict[str, str]]:
    """Get all available players for a user"""
    try:
        players = await players_collection.find({"user_id": user_id}).to_list(length=100)
        return [{"id": str(player["_id"]), "name": player["name"]} for player in players]
    except Exception as e:
        print(f"Error getting available players: {e}")
        return []

async def create_or_update_player(user_id: str, player_name: str, note_id: Optional[ObjectId] = None, player_note_id: Optional[ObjectId] = None) -> Optional[ObjectId]:
    """Create or update a player record"""
    try:
        if not player_name:
            print(f"[PLAYER] Skipping player without name")
            return None
            
        # Clean up player name - remove extra spaces, capitalize properly
        player_name = player_name.strip()
        
        # Skip if the name is too short or not valid
        if not player_name or len(player_name) < 2:
            print(f"[PLAYER] Skipping invalid player name: '{player_name}'")
            return None
            
        # Skip common non-player words that might be misidentified
        non_player_words = ["player", "user", "button", "small", "big", "blind", "utg", "dealer"]
        if player_name.lower() in non_player_words:
            print(f"[PLAYER] Skipping common non-player word: '{player_name}'")
            return None
            
        # Capitalize the name
        player_name = player_name.capitalize()
        
        print(f"[PLAYER] Processing player: {player_name}")
        
        # Check if player exists for this user
        existing_player = await players_collection.find_one({
            "user_id": user_id,
            "name": player_name
        })

        if existing_player:
            print(f"[PLAYER] Updating existing player: {player_name} with ID: {existing_player['_id']}")
            
            update_data = {"updatedAt": datetime.utcnow()}
            
            # Add note_id to notes_ids array if provided
            if note_id:
                update_data["$addToSet"] = update_data.get("$addToSet", {})
                update_data["$addToSet"]["notes_ids"] = note_id
                
            # Add player_note_id to player_notes_ids array if provided
            if player_note_id:
                if "$addToSet" not in update_data:
                    update_data["$addToSet"] = {}
                update_data["$addToSet"]["player_notes_ids"] = player_note_id
            
            # Update the player document
            await players_collection.update_one(
                {"_id": existing_player["_id"]},
                update_data
            )
            return existing_player["_id"]
        else:
            print(f"[PLAYER] Creating new player: {player_name}")
            # Create new player with arrays for notes and player notes
            new_player = {
                "user_id": user_id,
                "name": player_name,
                "notes_ids": [note_id] if note_id else [],
                "player_notes_ids": [player_note_id] if player_note_id else [],
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }
            result = await players_collection.insert_one(new_player)
            print(f"[PLAYER] Created new player with ID: {result.inserted_id}")
            return result.inserted_id

    except Exception as e:
        print(f"[PLAYER] Error in create_or_update_player: {e}")
        return None

async def analyze_players_in_note(note_id: str, user_id: str, retry_count: int = 3) -> Dict[str, Any]:
    """Analyze players in a note using GPT-4o and store the results"""
    try:
        # Get the note
        note_obj_id = ObjectId(note_id)
        note = await notes_collection.find_one({"_id": note_obj_id, "user_id": user_id})
        if not note:
            print(f"[ANALYSIS] Note not found: {note_id}")
            raise HTTPException(status_code=404, detail="Note not found")
        
        # Get the transcript
        transcript = note.get("transcriptFromDeepgram", "")
        if not transcript:
            print(f"[ANALYSIS] No transcript found in note: {note_id}")
            return {"success": False, "message": "No transcript found in note"}
        
        # Get available players
        available_players = await get_available_players(user_id)
        player_names = [player["name"] for player in available_players]
        
        print(f"[ANALYSIS] Available players for user {user_id}: {player_names}")
        
        # Create the prompt
        prompt = PLAYER_ANALYSIS_PROMPT.format(
            transcript=transcript,
            available_players=", ".join(player_names)
        )
        
        # Try to get analysis from GPT with retries
        analysis_result = None
        raw_response = ""
        
        for attempt in range(retry_count):
            try:
                print(f"[ANALYSIS] Attempt {attempt+1} to analyze players with GPT-4o")
                raw_response = await get_gpt_response(
                    prompt=prompt,
                    system_message="You are a poker analysis expert. Analyze players from the transcript and return valid JSON."
                )
                
                print(f"[ANALYSIS] Raw GPT-4o response: {raw_response[:200]}...")
                
                # Clean and parse the response
                cleaned_json = raw_response.strip()
                
                # Find JSON content if wrapped in markdown code blocks or other text
                json_start = cleaned_json.find('{')
                json_end = cleaned_json.rfind('}')
                
                if json_start != -1 and json_end != -1 and json_end > json_start:
                    # Extract just the JSON part
                    cleaned_json = cleaned_json[json_start:json_end+1]
                    print(f"[ANALYSIS] Extracted JSON: {cleaned_json[:100]}...")
                else:
                    # If we can't find JSON markers, try other cleaning methods
                    if cleaned_json.startswith("```json"):
                        cleaned_json = cleaned_json.replace("```json", "", 1)
                    if cleaned_json.startswith("```"):
                        cleaned_json = cleaned_json.replace("```", "", 1)
                    if cleaned_json.endswith("```"):
                        cleaned_json = cleaned_json.rstrip("```")
                    cleaned_json = cleaned_json.strip()
                
                # Try to parse the JSON
                analysis_result = json.loads(cleaned_json)
                
                # Validate the result structure
                if "players" not in analysis_result or not isinstance(analysis_result["players"], list):
                    print(f"[ANALYSIS] Invalid response structure: {analysis_result}")
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
        
        # If we failed to get a valid response after all retries, create a fallback response
        if not analysis_result:
            print(f"[ANALYSIS] Failed to get valid player analysis from GPT-4o, creating fallback")
            
            # Extract potential player names from transcript
            words = transcript.split()
            potential_players = []
            
            # Look for capitalized words that could be names
            for word in words:
                word = word.strip(",.!?;:\"'()[]{}")
                if word and word[0].isupper() and len(word) > 2 and word.lower() not in ["the", "and", "but", "for", "with"]:
                    potential_players.append(word)
            
            # Remove duplicates
            potential_players = list(set(potential_players))
            
            # Create a fallback analysis result
            analysis_result = {
                "players": [
                    {
                        "playername": player,
                        "description_text": f"Player mentioned in transcript.",
                        "description_html": f"<p><strong>{player}</strong> was mentioned in the transcript.</p>"
                    } for player in potential_players[:5]  # Limit to first 5 potential players
                ]
            }
            
            print(f"[ANALYSIS] Created fallback analysis with {len(analysis_result['players'])} potential players")
        
        # Process each player in the analysis
        player_notes = []
        
        print(f"[ANALYSIS] Processing {len(analysis_result.get('players', []))} players from analysis")
        
        for player_data in analysis_result.get("players", []):
            player_name = player_data.get("playername", "")
            if not player_name:
                print(f"[ANALYSIS] Skipping player with no name")
                continue
            
            print(f"[ANALYSIS] Processing player: {player_name}")
            
            # Create player note first
            player_note = {
                "user_id": user_id,
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
            print(f"[ANALYSIS] Created player note with ID: {player_note_id} for player: {player_name}")
                
            # Create or update the player with references to both note and player note
            player_id = await create_or_update_player(
                user_id=user_id, 
                player_name=player_name,
                note_id=note_obj_id,
                player_note_id=player_note_id
            )
            
            if player_id:
                # Update the player note with the player ID
                await players_notes_collection.update_one(
                    {"_id": player_note_id},
                    {"$set": {"player_id": player_id}}
                )
                
                player_notes.append({
                    "id": str(player_note_id),
                    "player_id": str(player_id),
                    "player_name": player_name,
                    "description_text": player_data.get("description_text", ""),
                    "description_html": player_data.get("description_html", "")
                })
                
                print(f"[ANALYSIS] Successfully processed player: {player_name} with ID: {player_id}")
            else:
                print(f"[ANALYSIS] Failed to create or update player: {player_name}")
        
        print(f"[ANALYSIS] Completed analysis for note {note_id} with {len(player_notes)} player notes")
        
        return {
            "success": True,
            "note_id": note_id,
            "player_notes": player_notes
        }
    
    except Exception as e:
        print(f"[ANALYSIS] Error analyzing players in note: {e}")
        print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
        return {"success": False, "message": str(e)}

@router.post("/notes/{note_id}/analyze-players")
async def analyze_players_endpoint(note_id: str, user_id: str = Header(None)):
    """Endpoint to analyze players in a note"""
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
        
    result = await analyze_players_in_note(note_id, user_id)
    
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("message", "Failed to analyze players"))
        
    return result

@router.get("/notes/{note_id}/player-notes")
async def get_player_notes(note_id: str, user_id: str = Header(None)):
    """Get all player notes for a note"""
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
        
    try:
        # Convert note_id to ObjectId
        note_obj_id = ObjectId(note_id)
        
        # Get player notes
        player_notes = await players_notes_collection.find({
            "user_id": user_id,
            "note_id": note_obj_id
        }).to_list(length=100)
        
        # Format response
        formatted_notes = []
        for note in player_notes:
            formatted_notes.append({
                "id": str(note["_id"]),
                "player_id": str(note["player_id"]),
                "player_name": note["player_name"],
                "description_text": note.get("description_text", ""),
                "description_html": note.get("description_html", ""),
                "createdAt": note.get("createdAt", datetime.utcnow()).isoformat(),
                "updatedAt": note.get("updatedAt", datetime.utcnow()).isoformat()
            })
            
        return {
            "success": True,
            "note_id": note_id,
            "player_notes": formatted_notes
        }
    
    except Exception as e:
        print(f"Error getting player notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/players/{player_id}/notes")
async def get_notes_for_player(player_id: str, user_id: str = Header(None)):
    """Get all notes for a player"""
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
        
    try:
        # Convert player_id to ObjectId
        player_obj_id = ObjectId(player_id)
        
        # Get player notes
        player_notes = await players_notes_collection.find({
            "user_id": user_id,
            "player_id": player_obj_id
        }).to_list(length=100)
        
        # Format response
        formatted_notes = []
        for note in player_notes:
            # Get the associated note
            original_note = await notes_collection.find_one({"_id": note["note_id"]})
            
            formatted_notes.append({
                "id": str(note["_id"]),
                "note_id": str(note["note_id"]),
                "note_summary": original_note.get("summaryFromGPT", "") if original_note else "",
                "note_date": original_note.get("createdAt", datetime.utcnow()).isoformat() if original_note else "",
                "description_text": note.get("description_text", ""),
                "description_html": note.get("description_html", ""),
                "createdAt": note.get("createdAt", datetime.utcnow()).isoformat(),
                "updatedAt": note.get("updatedAt", datetime.utcnow()).isoformat()
            })
            
        return {
            "success": True,
            "player_id": player_id,
            "player_notes": formatted_notes
        }
    
    except Exception as e:
        print(f"Error getting notes for player: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 