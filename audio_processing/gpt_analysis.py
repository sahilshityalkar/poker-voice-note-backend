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
            
        # Handle incomplete JSON (missing closing brace)
        open_braces = cleaned.count('{')
        close_braces = cleaned.count('}')
        if open_braces > close_braces:
            cleaned = cleaned + '}'*(open_braces - close_braces)
            
        # Handle incomplete JSON (missing opening brace)
        if close_braces > open_braces:
            cleaned = '{'*(close_braces - open_braces) + cleaned
            
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
            pattern = r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_])(\s:)'
            cleaned = re.sub(pattern, r'\1"\2"\3', cleaned)
            
            try:
                json.loads(cleaned)
                print(f"Advanced cleaning successful: {cleaned}")
                return cleaned
            except json.JSONDecodeError as e2:
                print(f"Advanced cleaning failed: {e2}, Returning empty JSON")
                return '{"players": []}'
    except Exception as e:
        print(f"Unexpected error in clean_gpt_response: {str(e)}")
        return '{"players": []}'


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

        # Basic structure validation for players
        for player in data["players"]:
            if not isinstance(player, dict):
                continue
            print(f"Player data from GPT: {player}")
            
            # Ensure required fields exist
            if not player.get("name"):
                continue
                
            # Ensure position is set
            if not player.get("position"):
                player["position"] = "MP"
                
            # Ensure win status is set
            if "won" not in player:
                player["won"] = False

        # Ensure myPosition is set
        if not data.get("myPosition"):
            data["myPosition"] = "MP"

        # Ensure iWon is set
        data["iWon"] = bool(data.get("iWon", False))

        # Ensure potSize is set
        if "potSize" not in data:
            data["potSize"] = None
        
        print(f"Validation successful for hand data: {data}")
        return True, None
    except Exception as e:
        print(f"Error in validate_hand_data: {str(e)}")
        return False, str(e)


async def validate_player_data(data: Dict) -> Tuple[bool, Dict]:
    """Validates the player data structure from GPT"""
    try:
        print(f"Validating player data: {data}")
        if not isinstance(data, dict):
            print("Player data is not a dictionary")
            return False, {"players": []}
            
        if "players" not in data or not isinstance(data["players"], list):
            print("Players field missing or not a list")
            return False, {"players": []}
            
        # Basic structure validation
        validated_players = []
        for player in data["players"]:
            if not isinstance(player, dict):
                print(f"Player is not a dictionary: {player}")
                continue
                
            # Ensure name exists
            if not player.get("name"):
                print(f"Player has no name, skipping: {player}")
                continue
                
            # Ensure position is set
            if not player.get("position"):
                player["position"] = "MP"
                
            # Ensure win status is set
            if "won" not in player:
                player["won"] = False
                
            validated_players.append(player)
                
        # Update players with validated list
        data["players"] = validated_players
        
        print(f"Player data validation successful: {data}")
        return True, data
    except Exception as e:
        print(f"Error validating player data: {str(e)}")
        return False, {"players": []}


async def extract_hand_data(transcript: str) -> Dict:
    """Extracts structured hand data from transcript using GPT only"""
    try:
        # Preprocess transcript to correct common errors
        processed_transcript = preprocess_transcript(transcript)
        print(f"Starting GPT call for hand data extraction...")
        
        try:
            # Make the GPT API call
            response = await client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a precise poker hand parser. Extract and return ONLY this JSON structure:
{
    "players": [
        {
            "name": "string (player name)",
            "position": "string (UTG/MP/CO/BTN/SB/BB)",
            "won": boolean
        }
    ],
    "myPosition": "string (UTG/MP/CO/BTN/SB/BB)",
    "iWon": boolean,
    "potSize": number or null
}

Important rules:
1. ALWAYS assign a position for every player and the narrator (myPosition)
2. If position is not explicitly mentioned:
   - Look at betting order to determine positions
   - In a 6-max game, positions are: UTG, MP, CO, BTN, SB, BB
   - In a 3-4 player game, positions are: CO, BTN, SB, BB
   - Never return "Unknown" as a position
3. Detect win/loss status accurately from the transcript context
4. Include all players mentioned in the transcript
5. Set potSize as null if not explicitly mentioned"""
                    },
                    {
                        "role": "user",
                        "content": f"Parse this poker hand and return ONLY the JSON structure. Remember to assign positions for everyone based on betting order: {processed_transcript}"
                    }
                ],
                temperature=0.1
            )
            
            print("GPT API call successful")
            
            if hasattr(response, 'choices') and len(response.choices) > 0:
                response_text = response.choices[0].message.content
                print(f"Raw GPT response: {response_text}")
                
                # Clean and parse the response
                cleaned_response = clean_gpt_response(response_text)
                try:
                    hand_data = json.loads(cleaned_response)
                    print(f"Successfully parsed hand data: {hand_data}")
                    
                    # Validate the hand data
                    is_valid, error = await validate_hand_data(hand_data)
                    if not is_valid:
                        print(f"Validation failed: {error}")
                        return {
                            "players": [],
                            "myPosition": "MP",  # Default to MP instead of Unknown
                            "iWon": False,
                            "potSize": None
                        }
                    
                    # Ensure no Unknown positions
                    if hand_data["myPosition"] == "Unknown":
                        hand_data["myPosition"] = "MP"
                    
                    for player in hand_data["players"]:
                        if player["position"] == "Unknown":
                            player["position"] = "MP"
                    
                    return hand_data
                    
                except json.JSONDecodeError as e:
                    print(f"JSON parsing failed: {e}")
                    return {
                        "players": [],
                        "myPosition": "MP",  # Default to MP instead of Unknown
                        "iWon": False,
                        "potSize": None
                    }
            else:
                print("Invalid GPT response structure")
                return {
                    "players": [],
                    "myPosition": "MP",  # Default to MP instead of Unknown
                    "iWon": False,
                    "potSize": None
                }
                
        except Exception as e:
            print(f"GPT API error: {str(e)}")
            return {
                "players": [],
                "myPosition": "MP",  # Default to MP instead of Unknown
                "iWon": False,
                "potSize": None
            }

    except Exception as e:
        print(f"General error: {str(e)}")
        return {
            "players": [],
            "myPosition": "MP",  # Default to MP instead of Unknown
            "iWon": False,
            "potSize": None
        }

async def identify_players(transcript: str) -> Dict:
    """Identifies and analyzes players from transcript using GPT only"""
    try:
        processed_transcript = preprocess_transcript(transcript)
        print(f"Starting GPT call for player identification...")
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a precise poker player identifier. Return ONLY this JSON structure:
{
    "players": [
        {
            "name": "string (player name)",
            "position": "string (UTG/MP/CO/BTN/SB/BB)",
            "won": boolean
        }
    ]
}

Important rules:
1. ALWAYS assign a position for every player
2. If position is not explicitly mentioned:
   - Look at betting order to determine positions
   - In a 6-max game, positions are: UTG, MP, CO, BTN, SB, BB
   - In a 3-4 player game, positions are: CO, BTN, SB, BB
   - Never return "Unknown" as a position
3. Determine win/loss status from explicit mentions in the transcript
4. Do not include the narrator in this list"""
                    },
                    {
                        "role": "user",
                        "content": f"Identify all players in this poker hand and return ONLY the JSON structure. Remember to assign positions for everyone based on betting order: {processed_transcript}"
                    }
                ],
                temperature=0.1
            )
            
            print("GPT API call successful")
            
            if hasattr(response, 'choices') and len(response.choices) > 0:
                response_text = response.choices[0].message.content
                print(f"Raw GPT response: {response_text}")
                
                cleaned_response = clean_gpt_response(response_text)
                try:
                    player_data = json.loads(cleaned_response)
                    print(f"Successfully parsed player data: {player_data}")
                    
                    is_valid, validated_data = await validate_player_data(player_data)
                    if not is_valid:
                        print("Validation failed")
                        return {"players": []}
                    
                    # Ensure no Unknown positions
                    for player in validated_data["players"]:
                        if player["position"] == "Unknown":
                            player["position"] = "MP"
                    
                    return validated_data
                    
                except json.JSONDecodeError as e:
                    print(f"JSON parsing failed: {e}")
                    return {"players": []}
            else:
                print("Invalid GPT response structure")
                return {"players": []}
                
        except Exception as e:
            print(f"GPT API error: {str(e)}")
            return {"players": []}

    except Exception as e:
        print(f"General error: {str(e)}")
        return {"players": []}

async def generate_summary(transcript: str) -> str:
    """Generates a concise summary of the hand"""
    try:
        # Preprocess transcript to correct common errors
        processed_transcript = preprocess_transcript(transcript)
        print(f"Generating summary for preprocessed transcript")
        
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are a concise poker hand summarizer."
                },
                {
                    "role": "user",
                    "content": SUMMARY_PROMPT.format(transcript=processed_transcript)
                }
            ],
            temperature=0.3  # Lower temperature for more consistent response
        )

        if response and response.choices:
            summary = response.choices[0].message.content.strip()
            print(f"Generated summary: {summary}")
            return summary if summary else "No summary available"
        return "No summary available"
    except Exception as e:
        print(f"Error in generate_summary: {str(e)}")
        return "No summary available"


async def generate_insight(transcript: str) -> str:
    """Generates strategic insights from the hand"""
    try:
        # Preprocess transcript to correct common errors
        processed_transcript = preprocess_transcript(transcript)
        print(f"Generating insights for preprocessed transcript")
        
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise poker hand analyst."
                },
                {
                    "role": "user",
                    "content": INSIGHT_PROMPT.format(transcript=processed_transcript)
                }
            ],
            temperature=0.3  # Lower temperature for more consistent response
        )

        if response and response.choices:
            insight = response.choices[0].message.content.strip()
            print(f"Generated insight: {insight}")
            return insight if insight else "No insights available"
        return "No insights available"
    except Exception as e:
        print(f"Error in generate_insight: {str(e)}")
        return "No insights available"
    
async def process_transcript(transcript: str) -> Dict[str, Any]:
    """Process transcript and return all required data"""
    try:
        print(f"Processing transcript: {transcript}")
        
        # Get hand data directly from GPT
        hand_data = await extract_hand_data(transcript)
        print(f"Hand data extraction complete: {hand_data}")
        
        # Get player data directly from GPT
        player_data = await identify_players(transcript)
        print(f"Player data extraction complete: {player_data}")
        
        # Trust GPT's player data
        hand_data["players"] = player_data.get("players", [])
        print(f"Updated hand_data with players: {hand_data}")
        
        # Generate summary and insight
        summary = await generate_summary(transcript)
        print(f"Summary generation complete")
        
        insight = await generate_insight(transcript)
        print(f"Insight generation complete")

        result = {
            "hand_data": hand_data,
            "player_data": player_data,
            "summary": summary,
            "insight": insight
        }
        
        print(f"Transcript processing complete")
        return result
    except Exception as e:
        print(f"Error in process_transcript: {str(e)}")
        return {
            "hand_data": {
                "players": [],
                "myPosition": "MP",
                "iWon": False,
                "potSize": None
            },
            "player_data": {"players": []},
            "summary": "Error processing transcript",
            "insight": "Error processing transcript"
        }