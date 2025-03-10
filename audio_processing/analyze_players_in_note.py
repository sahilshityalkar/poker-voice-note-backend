"""
Self-contained module for player analysis with proper event loop handling
"""
import asyncio
import json
import re
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime
from bson import ObjectId

# GPT analysis function
async def get_player_analysis(transcript: str, user_language: str, player_names: List[str] = None, *, gpt_client=None):
    """Get player analysis using OpenAI GPT"""
    # Import here to avoid circular imports
    from audio_processing.gpt_analysis import get_gpt_response
    
    # If player names is provided, create a matching request, otherwise do general extraction
    if player_names and len(player_names) > 0:
        system_message = f"You are a poker analysis expert. Analyze players from the transcript and return valid JSON. ALL content must be in {user_language}. If any player name matches or is similar to one in this list: {', '.join(player_names)}, use the exact name from the list."
    else:
        system_message = f"""You are a poker analysis expert. Your task is to extract and analyze ALL players mentioned in the transcript.
For each player:
1. Extract their exact name as mentioned
2. Analyze their play style, decisions, and strategic patterns
3. Return a detailed analysis in {user_language}

IMPORTANT: Extract EVERY player mentioned in the transcript, including those mentioned only once.
Format your response as valid JSON with a 'players' array."""

    # Prompt template
    prompt = """Analyze the poker players mentioned in this transcript and provide a detailed breakdown of each player's:

1. Preflop strategy (tight/loose, passive/aggressive)
2. Postflop tendencies (betting patterns, bluffing frequency)
3. Key metrics (estimated VPIP, aggression factor)
4. Strategic leaks & tilt detection
5. Exploitation strategies

For each player, format your response as a JSON object with these fields:
- playername: The player's name
- description_text: A detailed plain text analysis (500-800 chars)
- description_html: The same analysis in simple HTML with paragraph tags and basic formatting

Transcript:
{transcript}

{available_players_text}

Return ONLY valid JSON containing an array of player objects. Each player object should include playername, description_text, and description_html.
"""
    
    formatted_prompt = prompt.format(
        transcript=transcript,
        available_players_text=f"Available players: {', '.join(player_names)}" if player_names else ""
    )
    
    # Get GPT response with player analysis
    try:
        if gpt_client:
            # Use provided client if available
            raw_response = await gpt_client.get_completion(formatted_prompt, system_message)
        else:
            # Use default function
            raw_response = await get_gpt_response(prompt=formatted_prompt, system_message=system_message)
        
        # Parse the JSON from GPT
        return parse_gpt_player_response(raw_response)
    except Exception as e:
        print(f"[ANALYSIS] Error getting player analysis: {e}")
        traceback.print_exc()
        return {"players": []}

def parse_gpt_player_response(raw_response: str) -> Dict:
    """Parse the GPT response for player analysis"""
    try:
        # Clean up the response
        response = raw_response.strip()
        
        # Check for code blocks
        if "```json" in response:
            # Extract content between ```json and ```
            start_idx = response.find("```json") + 7
            end_idx = response.find("```", start_idx)
            if end_idx > start_idx:
                response = response[start_idx:end_idx].strip()
        elif "```" in response:
            # Extract content between ``` and ```
            start_idx = response.find("```") + 3
            end_idx = response.find("```", start_idx)
            if end_idx > start_idx:
                response = response[start_idx:end_idx].strip()
                
        # Remove any non-JSON text before the first {
        if "{" in response:
            start_idx = response.find("{")
            response = response[start_idx:]
            
        # Remove any non-JSON text after the last }
        if "}" in response:
            end_idx = response.rfind("}") + 1
            response = response[:end_idx]
            
        print(f"[ANALYSIS] Cleaned player analysis response: {response[:200]}...")
        
        # Parse the JSON
        result = json.loads(response)
        
        # Ensure we have a 'players' key with an array
        if 'players' not in result:
            if isinstance(result, list):
                return {"players": result}
            else:
                # If we get a different structure, try to adapt it
                player_array = []
                
                # Check for common patterns in the response
                for key, value in result.items():
                    if key.lower().startswith("player") or "name" in key.lower():
                        # This might be a player entry
                        if isinstance(value, dict):
                            player_array.append(value)
                        elif isinstance(value, str):
                            # Simple player name, create minimal object
                            player_array.append({
                                "playername": value,
                                "description_text": f"Player {value} appeared in the transcript.",
                                "description_html": f"<p>Player {value} appeared in the transcript.</p>"
                            })
                
                if player_array:
                    return {"players": player_array}
                else:
                    # Wrap the entire result as a single player if needed
                    if "name" in result or "playername" in result:
                        return {"players": [result]}
                    else:
                        print(f"[ANALYSIS] Could not adapt response to player format: {result}")
                        return {"players": []}
                        
        return result
    except json.JSONDecodeError as json_err:
        print(f"[ANALYSIS] Error parsing player analysis JSON: {json_err}")
        print(f"[ANALYSIS] Raw response: {raw_response}")
        return {"players": []}
    except Exception as e:
        print(f"[ANALYSIS] Error processing player analysis response: {e}")
        traceback.print_exc()
        return {"players": []}

async def analyze_players_completely(
    note_id: str,
    user_id: str,
    transcript: str,
    language: str,
    db_connection
) -> Dict[str, Any]:
    """
    Completely self-contained function to analyze players in a note
    
    This function handles its own database connections and event loops
    """
    try:
        # Extract collections from the provided connection
        players_coll = db_connection['players']
        player_notes_coll = db_connection['players_notes'] 
        
        # Clean up any existing player notes for this note
        print(f"[ANALYSIS] Cleaning up existing player notes for note {note_id}")
        try:
            # Delete any existing player notes
            delete_result = await player_notes_coll.delete_many({"note_id": note_id})
            print(f"[ANALYSIS] Deleted {delete_result.deleted_count} existing player notes")
            
            # Find and update any players that reference this note
            players_with_refs = await players_coll.find(
                {"notes.note_id": note_id}
            ).to_list(length=100)
            
            for player in players_with_refs:
                await players_coll.update_one(
                    {"_id": player["_id"]},
                    {"$pull": {"notes": {"note_id": note_id}}}
                )
                
            print(f"[ANALYSIS] Removed note references from {len(players_with_refs)} players")
        except Exception as e:
            print(f"[ANALYSIS] Error during cleanup: {e}")
            traceback.print_exc()
            
        # Get player analysis
        player_analysis = await get_player_analysis(transcript, language)
        
        if not player_analysis or not player_analysis.get("players"):
            print(f"[ANALYSIS] No players found in transcript")
            return {
                "success": True,
                "message": "No players found in transcript",
                "player_notes": []
            }
            
        players_data = player_analysis.get("players", [])
        print(f"[ANALYSIS] Found {len(players_data)} players in transcript")
        
        # Process each player
        player_notes = []
        for player_data in players_data:
            try:
                # Extract player name and descriptions
                player_name = player_data.get("playername", "").strip()
                if not player_name:
                    print(f"[ANALYSIS] Skipping player with missing name")
                    continue
                    
                description_text = player_data.get("description_text", "").strip()
                description_html = player_data.get("description_html", "").strip()
                
                if not description_text:
                    description_text = f"{player_name} appeared in this hand."
                    description_html = f"<p>{player_name} appeared in this hand.</p>"
                    
                # Create or update player
                player_doc = {
                    "user_id": user_id,
                    "name": player_name,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "notes": []
                }
                
                # Try to find existing player
                existing_player = await players_coll.find_one({
                    "user_id": user_id, 
                    "name": {"$regex": f"^{re.escape(player_name)}$", "$options": "i"}
                })
                
                if existing_player:
                    player_id = existing_player["_id"]
                    print(f"[ANALYSIS] Using existing player: {player_name} ({player_id})")
                else:
                    # Create new player
                    result = await players_coll.insert_one(player_doc)
                    player_id = result.inserted_id
                    print(f"[ANALYSIS] Created new player: {player_name} ({player_id})")
                
                # Create player note
                player_note_doc = {
                    "user_id": user_id,
                    "player_id": str(player_id),
                    "player_name": player_name,
                    "note_id": note_id,
                    "description_text": description_text,
                    "description_html": description_html,
                    "created_at": datetime.utcnow()
                }
                
                # Insert player note
                note_result = await player_notes_coll.insert_one(player_note_doc)
                player_note_id = note_result.inserted_id
                print(f"[ANALYSIS] Created player note with ID: {player_note_id}")
                
                # Update player with reference to note
                note_ref = {
                    "note_id": note_id,
                    "player_note_id": str(player_note_id),
                    "created_at": datetime.utcnow()
                }
                
                await players_coll.update_one(
                    {"_id": player_id},
                    {"$push": {"notes": note_ref}}
                )
                
                # Add to response
                player_notes.append({
                    "id": str(player_note_id),
                    "player_id": str(player_id),
                    "player_name": player_name,
                    "players_notes_count": 1,
                    "description_text": description_text,
                    "description_html": description_html,
                    "created_at": datetime.utcnow().isoformat()
                })
                
            except Exception as player_ex:
                print(f"[ANALYSIS] Error processing player {player_data.get('playername', 'unknown')}: {player_ex}")
                traceback.print_exc()
                
        return {
            "success": True,
            "player_notes": player_notes
        }
        
    except Exception as e:
        print(f"[ANALYSIS] Error in analyze_players_completely: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "message": str(e),
            "player_notes": []
        } 