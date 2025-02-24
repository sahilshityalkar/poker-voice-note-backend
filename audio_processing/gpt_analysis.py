# gpt_analysis.py

import os
import json
import re
from typing import Dict, Optional, Tuple, Any
from openai import AsyncOpenAI
from dotenv import load_dotenv
from .prompts import (
   HAND_DATA_PROMPT, 
   PLAYER_ANALYSIS_PROMPT, 
   SUMMARY_PROMPT, 
   INSIGHT_PROMPT,
   get_validation_rules
)

# Load environment variables
load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def clean_gpt_response(response_text: str) -> str:
   """Clean and prepare GPT response text for JSON parsing"""
   try:
       # Replace problematic newlines and extra spaces
       cleaned = response_text.replace('\n', '').replace('  ', ' ').strip()
       
       # Handle the specific error case we're seeing
       if cleaned.startswith('"players"'):
           cleaned = '{' + cleaned + '}'
       
       # Try to parse as JSON to validate
       try:
           json.loads(cleaned)
           return cleaned
       except json.JSONDecodeError:
           # If parsing fails, try to fix common issues
           if not cleaned.startswith('{'):
               cleaned = '{' + cleaned
           if not cleaned.endswith('}'):
               cleaned = cleaned + '}'
           return cleaned
           
   except Exception as e:
       print(f"Error cleaning GPT response: {e}")
       return '{"players": []}'  # Return valid empty JSON as fallback

def get_player_position(name: str, transcript: str) -> str:
   """Extract player's position from transcript"""
   transcript = transcript.lower()
   name = name.lower()
   
   positions = {
       "UTG": ["under the gun", "utg", "under the turn"],
       "MP": ["middle position", "mp"],
       "CO": ["cutoff", "co"],
       "BTN": ["button", "btn", "bottom position"],
       "SB": ["small blind", "sb"],
       "BB": ["big blind", "bb"]
   }
   
   # Get the sentence containing the player name
   sentences = transcript.split('.')
   for sentence in sentences:
       if name in sentence:
           for pos, terms in positions.items():
               if any(term in sentence for term in terms):
                   return pos
   
   return "Unknown"

def extract_basic_info(transcript: str) -> Dict:
   """Extract basic information from transcript as fallback"""
   transcript = transcript.lower()
   
   # Extract position
   position = "Unknown"
   if "button" in transcript or "bottom position" in transcript:
       position = "BTN"
   elif "under the gun" in transcript or "utg" in transcript or "under the turn" in transcript:
       position = "UTG"
   elif "middle position" in transcript or "mp" in transcript:
       position = "MP"
   elif "cutoff" in transcript or "co" in transcript:
       position = "CO"
   elif "small blind" in transcript or "sb" in transcript:
       position = "SB"
   elif "big blind" in transcript or "bb" in transcript:
       position = "BB"
   
   # Detect if won
   won = any(phrase in transcript for phrase in ["i won", "i want the pot", "i win", "paid off"])
   
   # Extract players (only actual names, not words containing "player")
   players = []
   
   # Find named players using strict word boundaries
   named_players = re.findall(r'\b(?:john|mike|rohit|pradeep)\b', transcript)
   
   # Process each found player
   for name in set(named_players):  # Using set to remove duplicates
       players.append({
           "name": name.capitalize(),
           "position": get_player_position(name, transcript),
           "won": False
       })
   
   return {
       "players": players,
       "myPosition": position,
       "iWon": won,
       "potSize": None
   }

async def validate_hand_data(data: Dict) -> Tuple[bool, Optional[str]]:
   """Validates the hand data structure from GPT"""
   try:
       rules = get_validation_rules()["hand_data"]
       
       if not isinstance(data, dict):
           return False, "Data must be a dictionary"

       # Validate required fields
       for field in rules["required_fields"]:
           if field not in data:
               return False, f"Missing required field: {field}"

       # Validate players array
       if not isinstance(data.get("players", []), list):
           data["players"] = []

       # Validate each player
       for player in data["players"]:
           if not isinstance(player, dict):
               continue
           if not re.match(rules["name_pattern"], player.get("name", "")):
               player["name"] = player.get("name", "Unknown").capitalize()
           player["position"] = player.get("position", "Unknown")
           if player["position"] not in rules["valid_positions"] + ["Unknown"]:
               player["position"] = "Unknown"
           player["won"] = bool(player.get("won", False))

       # Validate myPosition
       if data.get("myPosition") not in rules["valid_positions"] + ["Unknown"]:
           data["myPosition"] = "Unknown"

       # Validate iWon
       data["iWon"] = bool(data.get("iWon", False))

       # Validate potSize
       if "potSize" in data and not isinstance(data["potSize"], (int, float, type(None))):
           data["potSize"] = None

       return True, None
   except Exception as e:
       return False, str(e)

async def extract_hand_data(transcript: str) -> Dict:
   """Extracts structured hand data from transcript"""
   try:
       response = await client.chat.completions.create(
           model="gpt-4",
           messages=[
               {
                   "role": "system", 
                   "content": "You are a precise poker hand parser. Respond with valid JSON only."
               },
               {
                   "role": "user", 
                   "content": HAND_DATA_PROMPT.format(transcript=transcript)
               }
           ],
           response_format={"type": "json_object"}  # Force JSON response
       )
       
       try:
           response_text = response.choices[0].message.content
           cleaned_response = clean_gpt_response(response_text)
           hand_data = json.loads(cleaned_response)
       except (json.JSONDecodeError, AttributeError) as e:
           print(f"Falling back to basic extraction. Error: {e}")
           return extract_basic_info(transcript)

       is_valid, error = await validate_hand_data(hand_data)
       if not is_valid:
           return extract_basic_info(transcript)
           
       return hand_data
   except Exception as e:
       print(f"Error in extract_hand_data: {str(e)}")
       return extract_basic_info(transcript)

async def identify_players(transcript: str) -> Dict:
   """Identifies and analyzes players from transcript"""
   try:
       response = await client.chat.completions.create(
           model="gpt-4",
           messages=[
               {
                   "role": "system", 
                   "content": "You are a precise poker player identifier. Respond with valid JSON only."
               },
               {
                   "role": "user", 
                   "content": PLAYER_ANALYSIS_PROMPT.format(transcript=transcript)
               }
           ],
           response_format={"type": "json_object"}  # Force JSON response
       )
       
       try:
           response_text = response.choices[0].message.content
           cleaned_response = clean_gpt_response(response_text)
           player_data = json.loads(cleaned_response)
       except (json.JSONDecodeError, AttributeError) as e:
           print(f"Falling back to basic player extraction. Error: {e}")
           return {"players": extract_basic_info(transcript)["players"]}

       if not player_data.get("players"):
           return {"players": extract_basic_info(transcript)["players"]}
           
       return player_data
   except Exception as e:
       print(f"Error in identify_players: {str(e)}")
       return {"players": []}

async def generate_summary(transcript: str) -> str:
   """Generates a concise summary of the hand"""
   try:
       response = await client.chat.completions.create(
           model="gpt-4",
           messages=[
               {
                   "role": "system", 
                   "content": "You are a concise poker hand summarizer."
               },
               {
                   "role": "user", 
                   "content": SUMMARY_PROMPT.format(transcript=transcript)
               }
           ]
       )
       
       if response and response.choices:
           summary = response.choices[0].message.content.strip()
           return summary if summary else "No summary available"
       return "No summary available"
   except Exception as e:
       print(f"Error in generate_summary: {str(e)}")
       return "No summary available"

async def generate_insight(transcript: str) -> str:
   """Generates strategic insights from the hand"""
   try:
       response = await client.chat.completions.create(
           model="gpt-4",
           messages=[
               {
                   "role": "system", 
                   "content": "You are a precise poker hand analyst."
               },
               {
                   "role": "user", 
                   "content": INSIGHT_PROMPT.format(transcript=transcript)
               }
           ]
       )
       
       if response and response.choices:
           insight = response.choices[0].message.content.strip()
           return insight if insight else "No insights available"
       return "No insights available"
   except Exception as e:
       print(f"Error in generate_insight: {str(e)}")
       return "No insights available"

async def process_transcript(transcript: str) -> Dict[str, Any]:
   """Process transcript and return all required data"""
   try:
       # Process all data with proper fallbacks
       hand_data = await extract_hand_data(transcript)
       player_data = await identify_players(transcript)
       summary = await generate_summary(transcript)
       insight = await generate_insight(transcript)
       
       return {
           "hand_data": hand_data,
           "player_data": player_data,
           "summary": summary,
           "insight": insight
       }
   except Exception as e:
       print(f"Error in process_transcript: {str(e)}")
       basic_info = extract_basic_info(transcript)
       return {
           "hand_data": basic_info,
           "player_data": {"players": basic_info["players"]},
           "summary": "Error processing transcript",
           "insight": "Error processing transcript"
       }