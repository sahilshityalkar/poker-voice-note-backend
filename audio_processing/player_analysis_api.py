"""
Player Analysis API - Analyze poker player strengths and weaknesses
"""

from fastapi import APIRouter, HTTPException, Header
from typing import Optional, Dict, Any, List
from bson import ObjectId
from datetime import datetime
import asyncio
import json
import traceback
from openai import OpenAI
import os
from dotenv import load_dotenv
from .player_notes_api import db  # Import shared db connection only

# Load environment variables
load_dotenv()

# Get OpenAI API key directly from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Set up router
router = APIRouter(prefix="/player-analysis", tags=["player-analysis"])

# Define collections using the shared db connection
player_analysis_collection = db["player_analysis"]
players_collection = db.players
players_notes_collection = db.players_notes
user_collection = db.users

# Create a shared OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Create indexes for player analysis collection - simplified approach
async def ensure_indexes():
    """Create indexes for player analysis collection"""
    print("[DB] Creating player analysis indexes")
    try:
        # Create simple indexes for player_analysis
        await player_analysis_collection.create_index("player_id")
        await player_analysis_collection.create_index("user_id")
        await player_analysis_collection.create_index([("createdAt", -1)])
        
        print("[DB] Created player analysis indexes")
    except Exception as e:
        print(f"[DB] Error creating player analysis indexes: {e}")

# Player strengths/weaknesses analysis prompt
PLAYER_ANALYSIS_PROMPT = """
You are a professional poker player and coach with expertise in analyzing player tendencies.

I will provide you with a collection of notes about a specific poker player. Based on these notes, create a comprehensive analysis of the player.

Focus on extracting patterns of behavior, decision-making tendencies, emotional responses, and strategic approaches.

Player Notes:
{player_notes}

Create a detailed analysis covering:
1. The player's strengths (at least 2-3 if possible)
2. The player's weaknesses (at least 2-3 if possible)
3. Overall play style and tendencies
4. Strategic recommendations when playing against this player

IMPORTANT INSTRUCTIONS FOR LIMITED DATA:
- If there's only one note, still provide an analysis but clearly indicate it's based on limited data
- If the notes contain very little actionable information, focus on what CAN be determined and acknowledge the limitations
- Even with minimal data, provide at least some tentative analysis rather than saying "not enough information"
- Use phrases like "Based on limited data..." or "Initial observations suggest..." when appropriate

Format your response as JSON:
```json
{
  "analysis_in_text": "Full detailed analysis in plain text format that covers strengths, weaknesses, play style, and recommendations. If based on limited data, this should be clearly stated.",
  "analysis_in_html": "<div class='player-analysis'><h3>Player Analysis</h3><div class='data-notice'><p>This analysis is based on [number] player notes.</p></div><div class='strengths'><h4>Strengths</h4><ul><li>Strength 1</li><li>Strength 2</li></ul></div><div class='weaknesses'><h4>Weaknesses</h4><ul><li>Weakness 1</li><li>Weakness 2</li></ul></div><div class='style'><h4>Play Style</h4><p>Overall style description</p></div><div class='recommendations'><h4>Strategic Recommendations</h4><p>Recommendations when playing against this player</p></div></div>"
}
```

The HTML should be well-formatted with proper sections for:
1. Data notice (indicating how many notes the analysis is based on)
2. Strengths (with bullet points)
3. Weaknesses (with bullet points)
4. Play Style (with descriptive paragraphs)
5. Strategic Recommendations (with actionable advice)

Use appropriate HTML elements including div, h3, h4, ul, li, and p tags with the CSS classes shown in the example.

IMPORTANT: 
1. Return ONLY valid JSON! No explanation text before or after.
2. If there are NO player notes at all, this function won't be called, as the API has checks in place.
"""

# API endpoint to analyze a player
@router.post("/players/{player_id}/analyze")
async def analyze_player(player_id: str, user_id: str = Header(None)):
    """Analyze a player's strengths and weaknesses based on their notes"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")
        
        print(f"[ANALYSIS] Starting player analysis for player {player_id}, user {user_id}")
        
        # Validate player_id
        try:
            player_obj_id = ObjectId(player_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid player ID format")
        
        # Find the player to confirm existence and permission
        player = await players_collection.find_one({
            "_id": player_obj_id
        })
        
        if not player or player.get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="Player not found or you don't have permission to access")
        
        player_name = player.get("name", "Unknown Player")
        print(f"[ANALYSIS] Analyzing player: {player_name}")
        
        # Get all player notes for this player
        player_notes = []
        
        # Check if notes exists and has the correct structure
        if player.get("notes"):
            if all(isinstance(note, dict) for note in player.get("notes", [])):
                # New structure with objects containing player_note_id
                player_note_ids = [ObjectId(note["player_note_id"]) for note in player.get("notes", []) if "player_note_id" in note]
                if player_note_ids:
                    player_notes = await players_notes_collection.find({
                        "_id": {"$in": player_note_ids},
                        "user_id": user_id
                    }).to_list(None)
            else:
                # Legacy structure with just note IDs - try to recover
                print(f"[ANALYSIS] Found legacy notes structure for player {player_id}. Attempting to recover...")
                player_notes = await players_notes_collection.find({
                    "player_id": player_obj_id,
                    "user_id": user_id
                }).to_list(None)
                
                # If found notes, update the player record with correct structure
                if player_notes:
                    new_notes = []
                    for note in player_notes:
                        new_notes.append({
                            "note_id": str(note["note_id"]),
                            "player_note_id": str(note["_id"])
                        })
                    
                    # Update player with correct structure
                    await players_collection.update_one(
                        {"_id": player_obj_id},
                        {"$set": {"notes": new_notes}}
                    )
                    print(f"[ANALYSIS] Updated player {player_id} with correct notes structure")
        
        if not player_notes:
            # One final attempt - try to find any notes directly
            player_notes = await players_notes_collection.find({
                "player_id": player_obj_id,
                "user_id": user_id
            }).to_list(None)
            
            if player_notes:
                print(f"[ANALYSIS] Found {len(player_notes)} player notes for player {player_id} through direct query")
                
                # Update player with correct structure
                new_notes = []
                for note in player_notes:
                    new_notes.append({
                        "note_id": str(note["note_id"]),
                        "player_note_id": str(note["_id"])
                    })
                
                await players_collection.update_one(
                    {"_id": player_obj_id},
                    {"$set": {"notes": new_notes}}
                )
                print(f"[ANALYSIS] Updated player {player_id} with correct notes structure from direct query")
            
        if not player_notes:
            raise HTTPException(status_code=400, detail="No notes available for this player. Analysis cannot be performed.")
        
        # Extract the description_text from each note with more careful handling
        descriptions = []
        for i, note in enumerate(player_notes):
            desc = note.get("description_text", "")
            descriptions.append(f"Note {i+1}: {desc}")
        
        # Join descriptions - using a plain string instead of format to avoid template issues
        all_descriptions = "\n\n".join(descriptions)
        
        # Get user's language preference
        user = await user_collection.find_one({"user_id": user_id})
        language = user.get('notes_language', 'en') if user else 'en'
        
        # Call GPT for analysis
        try:
            print(f"[ANALYSIS] Sending {len(descriptions)} notes to GPT for analysis")
            
            # Instead of using string format, construct the full prompt directly
            full_prompt = PLAYER_ANALYSIS_PROMPT.replace("{player_notes}", all_descriptions)
            
            # Use the shared OpenAI client
            completion = await asyncio.to_thread(
                openai_client.chat.completions.create,
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a professional poker analysis assistant."},
                    {"role": "user", "content": full_prompt}
                ],
                temperature=0.5
            )
            
            # Extract JSON from response
            raw_response = completion.choices[0].message.content
            print(f"[ANALYSIS] GPT raw response (first 200 chars): {raw_response[:200]}")
            
            # Try to clean and parse JSON from response
            if '```json' in raw_response:
                json_content = raw_response.split('```json')[1].split('```')[0].strip()
            elif '```' in raw_response:
                json_content = raw_response.split('```')[1].split('```')[0].strip()
            else:
                json_content = raw_response.strip()
                
            print(f"[ANALYSIS] Cleaned result (first 200 chars): {json_content[:200]}")
            
            analysis_data = json.loads(json_content)
            
            # Create a new analysis document with new fields
            analysis_doc = {
                "user_id": user_id,
                "player_id": player_obj_id,
                "player_name": player_name,
                "analysis_in_text": analysis_data.get("analysis_in_text", ""),
                "analysis_in_html": analysis_data.get("analysis_in_html", ""),
                "based_on_notes_count": len(descriptions),
                "createdAt": datetime.utcnow()
            }
            
            # Insert the analysis
            result = await player_analysis_collection.insert_one(analysis_doc)
            analysis_id = result.inserted_id
            print(f"[ANALYSIS] Created player analysis with ID: {analysis_id}")
            
            # Format the response
            return {
                "success": True,
                "analysis_id": str(analysis_id),
                "player_id": player_id,
                "player_name": player_name,
                "analysis_in_text": analysis_data.get("analysis_in_text", ""),
                "analysis_in_html": analysis_data.get("analysis_in_html", ""),
                "based_on_notes_count": len(descriptions),
                "created_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            print(f"[ANALYSIS] Error in GPT analysis: {e}")
            print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error analyzing player: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ANALYSIS] Error analyzing player: {e}")
        print(f"[ANALYSIS] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

# API endpoint to get history of player analyses
@router.get("/players/{player_id}/analysis-history")
async def get_player_analysis_history(
    player_id: str, 
    user_id: str = Header(None),
    limit: int = 10,
    skip: int = 0
):
    """Get history of player analyses"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")
        
        # Validate player_id
        try:
            player_obj_id = ObjectId(player_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid player ID format")
        
        # Find the player to confirm existence and permission
        player = await players_collection.find_one({
            "_id": player_obj_id
        })
        
        if not player or player.get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="Player not found or you don't have permission to access")
        
        # Count total analyses
        total_count = await player_analysis_collection.count_documents({
            "player_id": player_obj_id,
            "user_id": user_id
        })
        
        # Get analyses with pagination, sorted by creation date (newest first)
        analyses_cursor = player_analysis_collection.find({
            "player_id": player_obj_id,
            "user_id": user_id
        }).sort("createdAt", -1).skip(skip).limit(limit)
        
        analyses = await analyses_cursor.to_list(None)
        
        # Format the analyses
        formatted_analyses = []
        for analysis in analyses:
            formatted_analyses.append({
                "id": str(analysis["_id"]),
                "player_id": player_id,
                "player_name": analysis.get("player_name", "Unknown Player"),
                "analysis_in_text": analysis.get("analysis_in_text", ""),
                "analysis_in_html": analysis.get("analysis_in_html", ""),
                "based_on_notes_count": analysis.get("based_on_notes_count", 0),
                "created_at": analysis.get("createdAt", datetime.utcnow()).isoformat()
            })
        
        return {
            "success": True,
            "total": total_count,
            "analyses": formatted_analyses
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ANALYSIS] Error getting player analysis history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# API endpoint to get the latest analysis for a player
@router.get("/players/{player_id}/latest-analysis")
async def get_latest_player_analysis(player_id: str, user_id: str = Header(None)):
    """Get the latest analysis for a player"""
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID is required in the header")
        
        # Validate player_id
        try:
            player_obj_id = ObjectId(player_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid player ID format")
        
        # Find the player to confirm existence and permission
        player = await players_collection.find_one({
            "_id": player_obj_id
        })
        
        if not player or player.get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="Player not found or you don't have permission to access")
        
        # Get the latest analysis
        latest_analysis = await player_analysis_collection.find_one({
            "player_id": player_obj_id,
            "user_id": user_id
        }, sort=[("createdAt", -1)])
        
        if not latest_analysis:
            return {
                "success": False,
                "message": "No analysis found for this player"
            }
        
        # Format the analysis
        formatted_analysis = {
            "id": str(latest_analysis["_id"]),
            "player_id": player_id,
            "player_name": latest_analysis.get("player_name", "Unknown Player"),
            "analysis_in_text": latest_analysis.get("analysis_in_text", ""),
            "analysis_in_html": latest_analysis.get("analysis_in_html", ""),
            "based_on_notes_count": latest_analysis.get("based_on_notes_count", 0),
            "created_at": latest_analysis.get("createdAt", datetime.utcnow()).isoformat()
        }
        
        return {
            "success": True,
            "analysis": formatted_analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ANALYSIS] Error getting latest player analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 