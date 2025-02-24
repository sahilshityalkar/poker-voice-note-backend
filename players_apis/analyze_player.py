# backend/players_apis/analyze_player.py
import os
import json
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient  # Import for database
from fastapi import APIRouter, HTTPException, status
from bson import ObjectId
from uuid import UUID  # Import UUID
from pydantic import BaseModel, Field
from datetime import datetime
import re

from audio_processing.gpt_analysis import clean_gpt_response

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# MongoDB setup
MONGODB_URL = os.getenv("DATABASE_URL")
db_client = AsyncIOMotorClient(MONGODB_URL)
db = db_client.pokernotes
players_collection = db.players
hands_collection = db.hands
notes_collection = db.notes

# Helper Function (Moved from other files)
def convert_objectid_to_str(data):
    """
    Recursively convert all ObjectId instances to strings in a dictionary or list
    """
    if isinstance(data, dict):
        return {k: convert_objectid_to_str(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_objectid_to_str(item) for item in data]
    elif isinstance(data, ObjectId):
        return str(data)
    else:
        return data

async def analyze_player_strengths_weaknesses(
    player_data: Dict[str, Any],
    hand_and_notes: List[Dict[str, Any]]
) -> Dict[str, List[str]]:
    """
    Analyzes a player's strengths and weaknesses based on structured data using GPT.
    """
    try:
        # Construct the prompt for GPT combining info from all hands
        prompt = f"""
        You are a poker expert analyzing a player's game. Please provide a JSON object containing the player's strengths and weaknesses based on their hand history.
        Make sure the model return valid JSON at all cost.

        Player Name: {player_data["name"]}
        Total Hands Played: {player_data["totalHands"]}
        Total Wins: {player_data["totalWins"]}

        Hand and Notes Data:
        {hand_and_notes}

        Analyze the poker player from the hands provided before. The player name is "{player_data["name"]}". I need to know all the STRENGHTS and WEAKNESSES of the player.
        Even if the player is bad, give me some positive traits that make the player unique.

        If strengths are hard to identify, consider:
          *  Positional awareness
          *  Aggression in certain situations
          *  Risk management
          *  Ability to fold when necessary
          *  Adaptability

        Return the output in the following JSON format:
        {{
          "strengths": [
            "Strength 1",
            "Strength 2",
            ...
          ],
          "weaknesses": [
            "Weakness 1",
            "Weakness 2",
            ...
          ]
        }}

        Ensure the response is valid JSON and nothing else.
        """

        response = await client.chat.completions.create(
            model="gpt-4",  # Or another suitable model
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,  #Adjusted, it's not so important
            max_tokens=500   # Adjust response length, adjust based on your needs
        )

        try:
            response_text = response.choices[0].message.content
            logging.info(f"Raw GPT Response: {response_text}")  # Log the raw response

            # Cleaning data with the function
            cleaned_data = clean_gpt_response(response_text)
            analysis = json.loads(cleaned_data)
            return analysis
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing GPT response: {e}. Raw Response: {response_text}")
            return {"strengths": [], "weaknesses": ["Could not parse GPT analysis"]}

    except Exception as e:
        logging.error(f"Error during OpenAI analysis: {e}")
        return {"strengths": [], "weaknesses": ["Analysis failed due to API error."]}

async def update_player_strengths_weaknesses(player_id: str, analysis: Dict[str, List[str]]):
    """
    Updates the player's strengths and weaknesses in the database.
    """
    try:
        player_obj_id = ObjectId(player_id)  # Convert to ObjectId
        update_result = await players_collection.update_one(
            {"_id": player_obj_id},
            {"$set": {"strengths": analysis["strengths"], "weaknesses": analysis["weaknesses"]}}
        )

        if update_result.modified_count == 1:
            logging.info(f"Successfully updated strengths/weaknesses for player {player_id}")
        else:
            logging.warning(f"Player {player_id} not found or update failed.")

    except Exception as e:
        logging.error(f"Error updating player in database: {e}")
        raise

router = APIRouter()

@router.post("/players/{player_id}/analyze")  # Takes player_id from URL
async def analyze_player(player_id: str):  # Takes *only* player_id
    """
    Analyzes a player's strengths and weaknesses based on the provided data
    and updates their profile in the database.
    """
    try:
        # 1. Fetch Player Data
        player = await players_collection.find_one({"_id": ObjectId(player_id)})

        if not player:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player not found."
            )

        player_data = convert_objectid_to_str(player)

        # 2. Fetch Hand and Note Data
        hand_and_notes = []
        for hand_ref in player_data.get("handReferences", []):
            try:
                hand_id = hand_ref.get("handId")
                note_id = hand_ref.get("noteId")
                hand = await hands_collection.find_one({"_id": hand_id})
                note = await notes_collection.find_one({"_id": note_id})
                if hand and note:
                     hand_data = convert_objectid_to_str(hand)
                     note_data = convert_objectid_to_str(note)
                     hand_and_notes.append({"hand": hand_data, "note": note_data}) #Appending hand object and not Hand instance
            except Exception as e:
                 logging.warning(f"Error fetching hand/note data: {e}")

        # 3. Analyze Player using GPT
        analysis = await analyze_player_strengths_weaknesses(
            player_data=player_data,  # Pass the structured player data
            hand_and_notes=hand_and_notes  # Pass the structured hand/note data
        )

        # 4. Update Player in Database
        await update_player_strengths_weaknesses(player_id=player_id, analysis=analysis)

        # Return the analysis
        return analysis

    except HTTPException as http_exc:
        raise http_exc  # Re-raise HTTP exceptions
    except Exception as e:
        logging.exception(f"Error analyzing player: {e}")  # Log full exception
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze player: {str(e)}"
        )