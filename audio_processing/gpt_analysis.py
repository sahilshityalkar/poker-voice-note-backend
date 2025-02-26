# gpt_analysis.py

import os
import json
import re
from typing import Dict, Optional, Tuple, Any, List
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
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError: {e}, Trying to fix JSON: {cleaned}") # Add this line to track JSON error.
            # Attempt to fix common JSON errors
            if not cleaned.startswith('{'):
                cleaned = '{' + cleaned
            if not cleaned.endswith('}'):
                cleaned = cleaned + '}'
            try:
                json.loads(cleaned)
                return cleaned  # Try parsing again after fixing
            except json.JSONDecodeError as e2:
                print(f"Failed to fix JSON. Returning empty player list. Error: {e2}")
                return '{"players": []}'  # Return valid empty JSON as fallback

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


def extract_player_names_from_transcript(transcript: str) -> List[str]:
    """Extract player names from transcript using regex patterns"""
    # Convert to lowercase for processing
    transcript_lower = transcript.lower()
    
    # List of words that aren't player names but might be detected
    non_player_words = ['i', 'me', 'my', 'mine', 'pot', 'card', 'hand', 
                        'raise', 'call', 'fold', 'check', 'bet', 'all-in', 
                        'all', 'in', 'flop', 'turn', 'river', 'dealer', 'utg', 
                        'mp', 'co', 'btn', 'sb', 'bb', 'blind', 'position']
    
    # Find potential names - capitalized words or words that appear after "player"
    words = transcript.split()
    potential_names = []
    
    # Look for capitalized words (typical name format)
    capitalized_words = [word.strip(',.!?():;"\'').capitalize() 
                         for word in words 
                         if word[0:1].isupper() and 
                         word.lower().strip(',.!?():;"\'') not in non_player_words and
                         len(word.strip(',.!?():;"\'')) > 1]
    
    # Look for words that appear after "player" keyword
    for i, word in enumerate(words[:-1]):
        if word.lower() == "player" and i+1 < len(words):
            next_word = words[i+1].strip(',.!?():;"\'').capitalize()
            if (len(next_word) > 1 and 
                next_word.lower() not in non_player_words and
                next_word.isalpha()):
                potential_names.append(next_word)
    
    # Look for names in common phrases like "X raised" or "X called"
    actions = ['raised', 'called', 'folded', 'checked', 'bet', 'went']
    for i, word in enumerate(words[:-1]):
        if (i+1 < len(words) and 
            words[i+1].lower() in actions and 
            word.strip(',.!?():;"\'').isalpha() and
            word.lower() not in non_player_words and
            len(word.strip(',.!?():;"\'')) > 1):
            potential_names.append(word.strip(',.!?():;"\'').capitalize())
    
    # Combine all potential names and remove duplicates
    potential_names.extend(capitalized_words)
    potential_names = list(set([name for name in potential_names if name.isalpha()]))
    
    return potential_names


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

    # Extract players using improved function
    player_names = extract_player_names_from_transcript(transcript)
    players = []

    # Process each found player
    for name in player_names:
        # Skip pronouns or short words that might be false positives
        if name.lower() in ['i', 'me', 'he', 'she', 'we', 'us', 'a', 'an', 'the']:
            continue
            
        players.append({
            "name": name.capitalize(),
            "position": get_player_position(name, transcript),
            "won": "won" in transcript and name.lower() in transcript.split("won")[0][-15:]
        })

    print("Extracted Players by basic info: ", players)

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
        print("validation_rules: ", rules)

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
            print("testing - player name", player.get("name", ""))  # Testing name pattern on players.
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
        print("Validation process results in data:", data)  # Check whether it is the validated/modified one

        return True, None
    except Exception as e:
        return False, str(e)


async def validate_player_data(data: Dict) -> Tuple[bool, Dict]:
    """Validates the player data structure from GPT"""
    try:
        if not isinstance(data, dict):
            return False, {"players": []}
            
        if "players" not in data or not isinstance(data["players"], list):
            return False, {"players": []}
            
        # Validate each player
        for player in data["players"]:
            if not isinstance(player, dict):
                continue
                
            # Ensure name is properly formatted
            if "name" not in player or not player["name"]:
                continue  # Skip players without names
                
            player["name"] = player["name"].strip().capitalize()
            
            # Ensure position is valid
            if "position" not in player or not player["position"]:
                player["position"] = "Unknown"
            elif player["position"] not in ["UTG", "MP", "CO", "BTN", "SB", "BB", "Unknown"]:
                player["position"] = "Unknown"
                
            # Ensure won is a boolean
            if "won" not in player:
                player["won"] = False
            else:
                player["won"] = bool(player["won"])
                
        return True, data
    except Exception as e:
        print(f"Error validating player data: {str(e)}")
        return False, {"players": []}


def merge_player_data(hand_players: List[Dict], analysis_players: List[Dict]) -> List[Dict]:
    """Merge player data from hand_data and player_data"""
    # Create a dictionary of players from hand_data for quick lookup
    hand_players_dict = {player["name"].lower(): player for player in hand_players if "name" in player}
    
    # Create a dictionary of players from player_data for quick lookup
    analysis_players_dict = {player["name"].lower(): player for player in analysis_players if "name" in player}
    
    # Merge the two sets of players
    merged_players = []
    
    # First, process all players from hand_data
    for name, player in hand_players_dict.items():
        if name in analysis_players_dict:
            # Merge the two player entries
            merged_player = player.copy()
            # If analysis has position and hand doesn't, use analysis position
            if player.get("position") == "Unknown" and analysis_players_dict[name].get("position") != "Unknown":
                merged_player["position"] = analysis_players_dict[name]["position"]
            # Take won status from either source (prioritize hand_data)
            if not player.get("won", False) and analysis_players_dict[name].get("won", False):
                merged_player["won"] = True
            merged_players.append(merged_player)
        else:
            # If player only in hand_data, add them
            merged_players.append(player)
    
    # Then add any players only in analysis_players
    for name, player in analysis_players_dict.items():
        if name not in hand_players_dict:
            merged_players.append(player)
    
    # If we still have no players, try a more lenient approach with name matching
    if not merged_players and (hand_players or analysis_players):
        all_players = hand_players + analysis_players
        seen_names = set()
        for player in all_players:
            if "name" in player and player["name"] and player["name"].lower() not in seen_names:
                seen_names.add(player["name"].lower())
                merged_players.append(player)
    
    print(f"Merged players: {merged_players}")
    return merged_players


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
        print ("response from the chat completion", response) # testing whole response
        try:
            response_text = response.choices[0].message.content
            cleaned_response = clean_gpt_response(response_text)
            hand_data = json.loads(cleaned_response)
            print("Hand Data extracted before validation:", hand_data)  # Raw hand data extrated
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"Falling back to basic extraction. Error: {e}")
            hand_data = extract_basic_info(transcript)  # Add the hand data variable to ensure basic info is extracted.
            print("falling back to basic info", hand_data)
            return hand_data

        is_valid, error = await validate_hand_data(hand_data)
        if not is_valid:
            print("Hand Data failed validation:", hand_data, "Error:", error)
            hand_data = extract_basic_info(transcript)  # If validation fails, load extract basic info.
            print("Hand data is not valid, extract basic info:", hand_data)
            return hand_data

        print("Hand data validated: ", hand_data)
        return hand_data
    except Exception as e:
        print(f"Error in extract_hand_data: {str(e)}")
        hand_data = extract_basic_info(transcript)  # When exception happened, extract basic info as well.
        print("exception extract basic info", hand_data)
        return hand_data


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
        print ("This the response", response) #checking response
        try:
            response_text = response.choices[0].message.content
            cleaned_response = clean_gpt_response(response_text)
            player_data = json.loads(cleaned_response)
            print("Player data extracted before validation:", player_data)
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"Falling back to basic player extraction. Error: {e}")
            player_data = {"players": extract_basic_info(transcript)["players"]}
            print("player data using basic info", player_data)  # If JSON fail, load basic info.

            return player_data

        is_valid, validated_data = await validate_player_data(player_data)
        if not is_valid or not validated_data.get("players"):
            player_data = {"players": extract_basic_info(transcript)["players"]}  # Use basic extraction as fallback
            print("Using basic info for player data:", player_data)
            return player_data
            
        print("Validated player data:", validated_data)
        return validated_data
    except Exception as e:
        print(f"Error in identify_players: {str(e)}")
        player_data = {"players": extract_basic_info(transcript)["players"]}
        print("player data in exception:", player_data)
        return player_data


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
        print("hand_data after extract_hand_data:", hand_data)
        
        player_data = await identify_players(transcript)
        print("player_data after identify_players:", player_data)
        
        # Merge player data from both sources
        merged_players = merge_player_data(hand_data.get("players", []), player_data.get("players", []))
        
        # Update hand_data with merged players
        hand_data["players"] = merged_players
        print("hand_data with merged players:", hand_data)
        
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