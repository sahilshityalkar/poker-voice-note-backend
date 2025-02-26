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

# Poker terminology correction mapping
POKER_TERM_CORRECTIONS = {
    # Card values
    "as": "ace",
    "aces": "ace",
    "spirits": "spades",
    "breads": "hearts", 
    "cubes": "clubs",
    "states": "spades",
    "diamond": "diamonds",
    "heart": "hearts",
    "club": "clubs",
    "spade": "spades",
    "wings": "queens",
    "queen": "queens",
    "tree": "three",
    "tree of": "three of",
    "s of": "ace of",
    "ten": "10",
    "jack": "J",
    "queen": "Q",
    "king": "K",
    
    # Actions
    "raids": "raises",
    "rates": "raises",
    "ipod": "I had",
    "ipot": "I bet",
    "want the pot": "won the pot",
    "want equal house": "won with full house",
    "want": "won",
    "equal house": "full house",
    "e call": "he called",
    "e raised": "he raised",
    "e bet": "he bet",
    "e fold": "he folded",
    "e check": "he checked"
}


def preprocess_transcript(transcript: str) -> str:
    """Preprocess the transcript to correct common transcription errors"""
    try:
        print(f"Original transcript: {transcript}")
        
        # Convert to lowercase for processing
        processed = transcript.lower()
        
        # Replace poker terms with corrections
        for error, correction in POKER_TERM_CORRECTIONS.items():
            # Use word boundaries to avoid partial replacements
            processed = re.sub(r'\b' + re.escape(error) + r'\b', correction, processed)
        
        # Fix common card notation patterns
        # Convert "X of Y" to standard notation
        processed = re.sub(r'(\w+) of (\w+)', r'\1 of \2', processed)
        
        # Fix action verbs
        action_verbs = {
            r'\braid\b': 'raise',
            r'\braids\b': 'raises',
            r'\brate\b': 'raise',
            r'\brates\b': 'raises'
        }
        
        for error_pattern, correction in action_verbs.items():
            processed = re.sub(error_pattern, correction, processed)
        
        print(f"Preprocessed transcript: {processed}")
        return processed
    except Exception as e:
        print(f"Error in preprocess_transcript: {e}")
        # Return original if processing fails
        return transcript


def clean_gpt_response(response_text: str) -> str:
    """Clean and prepare GPT response text for JSON parsing"""
    try:
        print(f"Raw GPT response to clean: '{response_text}'")
        
        # If response is None or empty, return empty JSON
        if not response_text or len(response_text.strip()) == 0:
            print("Empty response received, returning empty player list")
            return '{"players": []}'
            
        # First, try to parse as-is (sometimes it's already valid)
        try:
            json.loads(response_text)
            print("Response is already valid JSON")
            return response_text
        except json.JSONDecodeError:
            # Continue with cleaning if direct parsing fails
            pass
        
        # Replace problematic characters
        cleaned = response_text.replace('\n', ' ').replace('\r', ' ')
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()  # Normalize whitespace
        
        # Handle responses starting with a field instead of an object
        if cleaned.startswith('"players"') or cleaned.startswith("'players'"):
            cleaned = '{' + cleaned + '}'
            print(f"Added braces around response starting with 'players': {cleaned}")
            
        # Handle incomplete JSON (missing closing brace)
        open_braces = cleaned.count('{')
        close_braces = cleaned.count('}')
        if open_braces > close_braces:
            cleaned = cleaned + '}'*(open_braces - close_braces)
            print(f"Added {open_braces - close_braces} closing braces: {cleaned}")
            
        # Handle incomplete JSON (missing opening brace)
        if close_braces > open_braces:
            cleaned = '{'*(close_braces - open_braces) + cleaned
            print(f"Added {close_braces - open_braces} opening braces: {cleaned}")
            
        # Try to parse the cleaned JSON
        try:
            json.loads(cleaned)
            print(f"Successfully cleaned JSON: {cleaned}")
            return cleaned
        except json.JSONDecodeError as e:
            print(f"First cleaning attempt failed: {e}, Trying advanced fixes")
            
            # Try more aggressive fixing methods
            if not cleaned.startswith('{'):
                cleaned = '{' + cleaned
            if not cleaned.endswith('}'):
                cleaned = cleaned + '}'
                
            # Fix trailing commas before closing braces
            cleaned = re.sub(r',\s*}', '}', cleaned)
            
            # Fix missing quotes around keys
            pattern = r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)'
            cleaned = re.sub(pattern, r'\1"\2"\3', cleaned)
            
            try:
                json.loads(cleaned)
                print(f"Advanced cleaning successful: {cleaned}")
                return cleaned
            except json.JSONDecodeError as e2:
                # If all else fails, try to extract just the players array
                print(f"Advanced cleaning failed: {e2}, Attempting to extract players array")
                
                # Try to find a players array using regex
                players_match = re.search(r'"players"\s*:\s*(\[.*?\])', cleaned)
                if players_match:
                    players_array = players_match.group(1)
                    try:
                        # Validate the extracted array
                        json.loads(players_array)
                        return f'{{"players": {players_array}}}'
                    except:
                        pass
                
                # Last resort - return empty valid JSON
                print("All JSON repairs failed. Returning empty player list.")
                return '{"players": []}'
    except Exception as e:
        print(f"Unexpected error in clean_gpt_response: {str(e)}")
        return '{"players": []}'


def detect_player_position(player_name: str, transcript: str, players_list=None) -> str:
    """Enhanced function to detect a player's position from transcript context"""
    transcript = transcript.lower()
    player_name = player_name.lower()
    
    # If players_list is provided, we can make inferences based on betting order
    all_players = []
    if players_list:
        all_players = [p.get("name", "").lower() for p in players_list if p.get("name")]

    # Common position terms
    positions = {
        "UTG": ["under the gun", "utg", "under the turn", "first to act", "first position"],
        "MP": ["middle position", "mp", "mid position"],
        "CO": ["cutoff", "co", "cut off", "hijack"],
        "BTN": ["button", "btn", "bottom position", "dealer", "on the button"],
        "SB": ["small blind", "sb", "small"],
        "BB": ["big blind", "bb", "big"]
    }
    
    # First check for direct position mentions near the player name
    sentences = transcript.split('.')
    for sentence in sentences:
        if player_name in sentence:
            for pos, terms in positions.items():
                if any(term in sentence for term in terms):
                    print(f"Found position {pos} for player {player_name} in sentence: {sentence}")
                    return pos
    
    # Extract betting order from transcript
    betting_pattern = re.compile(r'(\w+)\s+(raises|bets|calls|checks|folds)')
    actions = []
    
    for match in betting_pattern.finditer(transcript):
        actor = match.group(1).lower()
        if actor not in ['i', 'he', 'she', 'they'] and len(actor) > 1:
            if actor not in [a[0] for a in actions]:
                actions.append((actor, match.group(2)))
    
    # Add narrator actions separately
    narrator_pattern = re.compile(r'i\s+(raise|bet|call|check|fold)')
    for match in narrator_pattern.finditer(transcript):
        if 'i' not in [a[0] for a in actions]:
            actions.insert(0, ('i', match.group(1)))
    
    # If we have actions and players
    if actions and (all_players or len(actions) >= 2):
        # Determine if this is a heads-up (1v1) game
        is_headsup = (len(all_players) == 2) or (len(set([a[0] for a in actions])) == 2)
        
        # Get the first actors in the hand
        first_actors = [a[0] for a in actions[:3]]
        
        if player_name == 'i':
            # Logic for assigning positions to the narrator
            if is_headsup:
                return "BTN" if first_actors and first_actors[0] == 'i' else "BB"
            else:
                if first_actors and player_name in first_actors:
                    idx = first_actors.index(player_name)
                    if idx == 0:
                        return "UTG"
                    elif idx == len(first_actors) - 1:
                        return "BB"
                    elif idx == len(first_actors) - 2:
                        return "SB"
                    else:
                        return ["UTG", "MP", "CO", "BTN"][min(idx, 3)]
        else:
            # Logic for assigning positions to other players
            if is_headsup:
                return "BB" if first_actors and first_actors[0] == 'i' else "BTN"
            else:
                if first_actors and player_name in first_actors:
                    idx = first_actors.index(player_name)
                    if idx == 0:
                        return "UTG"
                    elif idx == len(first_actors) - 1:
                        return "BB"
                    elif idx == len(first_actors) - 2:
                        return "SB"
                    else:
                        return ["UTG", "MP", "CO", "BTN"][min(idx, 3)]
    
    # If we couldn't determine a position from context, assign a default position
    # based on player's order in the list
    if all_players and player_name in all_players:
        idx = all_players.index(player_name)
        positions_by_idx = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
        return positions_by_idx[min(idx, len(positions_by_idx)-1)]
    
    # If all else fails, make a reasonable guess based on common scenarios
    return "BTN" if player_name != 'i' else "BB"


def detect_win_status(player_name: str, transcript: str) -> bool:
    """Enhanced function to detect if a player won based on transcript context"""
    transcript = transcript.lower()
    player_name = player_name.lower()
    
    # Direct win phrases
    if "i" == player_name or "me" == player_name:
        # Phrases indicating narrator won
        win_phrases = [
            "i won", "i win", "i got the pot", "i took the pot", 
            "i won with", "i had the best hand", "paid me", "my hand won",
            "i won equal", "i won full", "i want the pot", "i want",
            "i had full house", "i had flush", "i had straight",
            "paid off"
        ]
        if any(phrase in transcript for phrase in win_phrases):
            print(f"Detected narrator win based on direct phrases")
            return True
            
        # Check for winning hands in context of "I"
        winning_hands = ["full house", "flush", "straight", "three of a kind", "two pair"]
        for hand in winning_hands:
            if hand in transcript:
                # Check if "I" is mentioned near the winning hand
                hand_index = transcript.find(hand)
                context = transcript[max(0, hand_index-30):hand_index]
                if "i" in context or "my" in context:
                    print(f"Detected narrator win based on winning hand: {hand}")
                    return True
    else:
        # Phrases indicating another player won
        win_context = [
            f"{player_name} won",
            f"{player_name} win",
            f"{player_name} got the pot",
            f"{player_name} took the pot",
            f"{player_name} had the best hand"
        ]
        
        if any(phrase in transcript for phrase in win_context):
            print(f"Detected win for {player_name} based on direct phrases")
            return True
            
        # Check if player showed winning hand at showdown
        showdown_patterns = [
            f"{player_name} show", 
            f"{player_name} had",
            f"{player_name} revealed"
        ]
        
        for pattern in showdown_patterns:
            if pattern in transcript:
                # Get the context after the showdown pattern
                pattern_index = transcript.find(pattern)
                after_context = transcript[pattern_index:pattern_index+60]
                
                # Check for winning hands in this context
                winning_hands = ["full house", "flush", "straight", "three of a kind", "two pair"]
                if any(hand in after_context for hand in winning_hands):
                    # Make sure no other player is mentioned as winner after this
                    if "won" in transcript[pattern_index:]:
                        won_index = transcript.find("won", pattern_index)
                        pre_win_context = transcript[won_index-20:won_index]
                        if player_name in pre_win_context:
                            print(f"Detected win for {player_name} based on showdown with winning hand")
                            return True
    
    # No win detected
    return False


def extract_player_names_from_transcript(transcript: str) -> List[str]:
    """Extract player names from transcript using regex patterns"""
    # Convert to lowercase for processing
    transcript_lower = transcript.lower()
    
    # List of words that aren't player names but might be detected
    non_player_words = ['i', 'me', 'my', 'mine', 'pot', 'card', 'hand', 
                       'raise', 'call', 'fold', 'check', 'bet', 'all-in', 
                       'all', 'in', 'flop', 'turn', 'river', 'dealer', 'utg', 
                       'mp', 'co', 'btn', 'sb', 'bb', 'blind', 'position',
                       'ace', 'king', 'queen', 'jack', 'club', 'heart', 'diamond', 'spade',
                       'full', 'house', 'flush', 'straight', 'pair', 'high']
    
    # Find potential names - capitalized words or words that appear before actions
    words = transcript.split()
    potential_names = []
    
    # Look for capitalized words (typical name format)
    capitalized_words = [word.strip(',.!?():;"\'').capitalize() 
                         for word in words 
                         if word and word[0:1].isupper() and 
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
    actions = ['raised', 'raise', 'raises', 'called', 'calls', 'folded', 'folds', 
              'checked', 'checks', 'bet', 'bets', 'went', 'goes', 'jams', 'shoved']
    for i, word in enumerate(words[:-1]):
        if (i+1 < len(words) and 
            words[i+1].lower() in actions and 
            word.strip(',.!?():;"\'').isalpha() and
            word.lower() not in non_player_words and
            len(word.strip(',.!?():;"\'')) > 1):
            potential_names.append(word.strip(',.!?():;"\'').capitalize())
    
    # Combine all potential names and remove duplicates
    potential_names.extend(capitalized_words)
    potential_names = list(set([name for name in potential_names if name.isalpha() and len(name) > 1]))
    
    print(f"Extracted potential player names: {potential_names}")
    return potential_names


def extract_basic_info(transcript: str) -> Dict:
    """Extract basic information from transcript as fallback"""
    # Preprocess the transcript to correct common errors
    processed_transcript = preprocess_transcript(transcript)
    print(f"Extracting basic info from preprocessed transcript: {processed_transcript}")

    # Extract players first so we can use them for position detection
    player_names = extract_player_names_from_transcript(processed_transcript)
    players = []

    # Process each found player to create initial player objects
    for name in player_names:
        # Skip pronouns or short words that might be false positives
        if name.lower() in ['i', 'me', 'he', 'she', 'we', 'us', 'a', 'an', 'the']:
            continue
            
        # Initially set position as Unknown, will update later
        player_won = detect_win_status(name, processed_transcript)
        
        players.append({
            "name": name.capitalize(),
            "position": "Unknown",  # Temporary placeholder
            "won": player_won
        })

    # Now determine position for the narrator
    my_position = detect_player_position("i", processed_transcript, players)
    
    # Update positions for all players
    for player in players:
        player["position"] = detect_player_position(player["name"].lower(), processed_transcript, players)
    
    # Detect if narrator won
    won = detect_win_status("i", processed_transcript)

    print(f"Extracted Players by basic info: {players}")
    print(f"Extracted position: {my_position}")
    print(f"Detected narrator won: {won}")

    return {
        "players": players,
        "myPosition": my_position,
        "iWon": won,
        "potSize": None
    }


async def validate_hand_data(data: Dict) -> Tuple[bool, Optional[str]]:
    """Validates the hand data structure from GPT"""
    try:
        rules = get_validation_rules()["hand_data"]
        print(f"Validating hand data: {data}")

        if not isinstance(data, dict):
            return False, "Data must be a dictionary"

        # Validate required fields
        for field in rules["required_fields"]:
            if field not in data:
                return False, f"Missing required field: {field}"

        # Validate players array
        if not isinstance(data.get("players", []), list):
            data["players"] = []
            print("Players field was not a list, set to empty list")

        # Validate each player
        validated_players = []
        for player in data["players"]:
            if not isinstance(player, dict):
                continue
            print(f"Validating player: {player}")
            
            # Ensure name exists and is valid
            if not player.get("name"):
                print(f"Player has no name, skipping: {player}")
                continue
                
            # Clean player name
            clean_name = player.get("name", "Unknown").strip()
            if not re.match(rules["name_pattern"], clean_name):
                clean_name = re.sub(r'[^A-Za-z\s]', '', clean_name).strip().capitalize()
                if not clean_name or len(clean_name) < 2:
                    print(f"Invalid player name after cleaning, skipping: {player}")
                    continue
                    
            # Validate position
            position = player.get("position", "MP")  # Default to MP instead of Unknown
            if position not in rules["valid_positions"]:
                position = "MP"  # Default to middle position
                print(f"Invalid position '{player.get('position')}', set to MP")
            
            # Add validated player
            validated_players.append({
                "name": clean_name,
                "position": position,
                "won": bool(player.get("won", False))
            })
            
        # Update players with validated list
        data["players"] = validated_players

        # Validate myPosition with default
        if data.get("myPosition") not in rules["valid_positions"]:
            data["myPosition"] = "BB"  # Default to BB for the narrator
            print(f"Invalid myPosition '{data.get('myPosition')}', set to BB")

        # Validate iWon
        data["iWon"] = bool(data.get("iWon", False))
        print(f"iWon status: {data['iWon']}")

        # Validate potSize
        if "potSize" in data and not isinstance(data["potSize"], (int, float, type(None))):
            data["potSize"] = None
            print(f"Invalid potSize type, set to None")
        
        print(f"Validation successful for hand data: {data}")
        return True, None
    except Exception as e:
        print(f"Error in validate_hand_data: {str(e)}")
        return False, str(e)


async def validate_player_data(data: Dict) -> Tuple[bool, Dict]:
    """Validates the player data structure from GPT"""
    try:
        rules = get_validation_rules()["player_data"]
        print(f"Validating player data: {data}")
        if not isinstance(data, dict):
            print("Player data is not a dictionary")
            return False, {"players": []}
            
        if "players" not in data or not isinstance(data["players"], list):
            print("Players field missing or not a list")
            return False, {"players": []}
            
        # Validate each player
        validated_players = []
        for player in data["players"]:
            if not isinstance(player, dict):
                print(f"Player is not a dictionary: {player}")
                continue
                
            # Ensure name is properly formatted
            if "name" not in player or not player["name"]:
                print(f"Player has no name, skipping: {player}")
                continue
                
            # Clean player name
            clean_name = player["name"].strip().capitalize()
            if not clean_name or len(clean_name) < 2:
                print(f"Invalid player name after cleaning, skipping: {player}")
                continue
                
            # Ensure position is valid
            position = player.get("position", "MP")  # Default to MP
            if position not in rules["valid_positions"]:
                position = "MP"  # Default to middle position
                print(f"Invalid position for {clean_name}: {position}, set to MP")
                
            # Add validated player
            validated_players.append({
                "name": clean_name,
                "position": position,
                "won": bool(player.get("won", False))
            })
                
        # Update players with validated list
        data["players"] = validated_players
        
        print(f"Player data validation successful: {data}")
        return True, data
    except Exception as e:
        print(f"Error validating player data: {str(e)}")
        return False, {"players": []}


def merge_player_data(hand_players: List[Dict], analysis_players: List[Dict]) -> List[Dict]:
    """Merge player data from hand_data and player_data"""
    print(f"Merging player data:\nHand players: {hand_players}\nAnalysis players: {analysis_players}")
    
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
        print("No exact name matches found, trying fuzzy matching")
        all_players = hand_players + analysis_players
        seen_names = set()
        for player in all_players:
            if "name" in player and player["name"] and player["name"].lower() not in seen_names:
                seen_names.add(player["name"].lower())
                merged_players.append(player)
    
    # Ensure all players have valid positions (not "Unknown")
    for player in merged_players:
        if player.get("position") == "Unknown":
            # Default to MP if position is Unknown
            player["position"] = "MP"
    
    print(f"Merged players result: {merged_players}")
    return merged_players


async def extract_hand_data(transcript: str) -> Dict:
    """Extracts structured hand data from transcript"""
    try:
        # Preprocess transcript to correct common errors
        processed_transcript = preprocess_transcript(transcript)
        print(f"Extracting hand data from preprocessed transcript")
        
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
                        "content": HAND_DATA_PROMPT.format(transcript=processed_transcript)
                    }
                ],
                response_format={"type": "json_object"},  # Force JSON response
                temperature=0.1  # Lower temperature for more consistent responses
            )
            
            print(f"GPT response received for hand data")
            
            if hasattr(response, 'choices') and len(response.choices) > 0:
                response_text = response.choices[0].message.content
                print(f"Raw hand data response: '{response_text}'")
                
                cleaned_response = clean_gpt_response(response_text)
                try:
                    hand_data = json.loads(cleaned_response)
                    print(f"Parsed hand data: {hand_data}")
                except json.JSONDecodeError as json_err:
                    print(f"Failed to parse hand data JSON after cleaning: {json_err}")
                    hand_data = extract_basic_info(processed_transcript)
                    print(f"Used basic extraction as fallback: {hand_data}")
                    return hand_data
            else:
                print("Invalid response structure from GPT API")
                hand_data = extract_basic_info(processed_transcript)
                return hand_data
                
        except Exception as api_error:
            print(f"Error calling GPT API: {str(api_error)}")
            hand_data = extract_basic_info(processed_transcript)
            return hand_data

        is_valid, error = await validate_hand_data(hand_data)
        if not is_valid:
            print(f"Hand Data failed validation: {error}")
            hand_data = extract_basic_info(processed_transcript)
            return hand_data

        return hand_data
    except Exception as e:
        print(f"Error in extract_hand_data: {str(e)}")
        hand_data = extract_basic_info(processed_transcript)
        return hand_data
    
async def identify_players(transcript: str) -> Dict:
    """Identifies and analyzes players from transcript"""
    try:
        # Preprocess transcript to correct common errors
        processed_transcript = preprocess_transcript(transcript)
        print(f"Identifying players from preprocessed transcript")
        
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
                        "content": PLAYER_ANALYSIS_PROMPT.format(transcript=processed_transcript)
                    }
                ],
                response_format={"type": "json_object"},  # Force JSON response
                temperature=0.1  # Lower temperature for more consistent responses
            )
            
            print(f"GPT response received for player analysis")
            
            if hasattr(response, 'choices') and len(response.choices) > 0:
                response_text = response.choices[0].message.content
                print(f"Raw player analysis response: '{response_text}'")
                
                cleaned_response = clean_gpt_response(response_text)
                try:
                    player_data = json.loads(cleaned_response)
                    print(f"Parsed player data: {player_data}")
                except json.JSONDecodeError as json_err:
                    print(f"Failed to parse player data JSON after cleaning: {json_err}")
                    player_data = {"players": extract_basic_info(processed_transcript)["players"]}
                    print(f"Used basic extraction as fallback: {player_data}")
                    return player_data
            else:
                print("Invalid response structure from GPT API")
                player_data = {"players": extract_basic_info(processed_transcript)["players"]}
                return player_data
                
        except Exception as api_error:
            print(f"Error calling GPT API: {str(api_error)}")
            player_data = {"players": extract_basic_info(processed_transcript)["players"]}
            return player_data

        is_valid, validated_data = await validate_player_data(player_data)
        if not is_valid or not validated_data.get("players"):
            print("Player data failed validation or has no players")
            player_data = {"players": extract_basic_info(processed_transcript)["players"]}
            return player_data
            
        return validated_data
    except Exception as e:
        print(f"Error in identify_players: {str(e)}")
        player_data = {"players": extract_basic_info(processed_transcript)["players"]}
        return player_data