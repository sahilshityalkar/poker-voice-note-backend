# prompts.py

HAND_DATA_PROMPT = """
You are a poker hand data extractor. Extract the following exact JSON structure from the transcript:

{
    "players": [
        {
            "name": "string (exactly as mentioned)",
            "position": "string (must be UTG/MP/CO/BTN/SB/BB only)",
            "won": "boolean (true/false)"
        }
    ],
    "myPosition": "string (must be UTG/MP/CO/BTN/SB/BB only)",
    "iWon": "boolean (did I win the hand)",
    "potSize": "number or null (in big blinds)"
}

Position Mapping:
- "under the gun" or "utg" or "under the turn" = "UTG"
- "middle position" or "mp" = "MP"
- "cutoff" or "co" = "CO"
- "button" or "btn" or "bottom position" = "BTN"
- "small blind" or "sb" = "SB"
- "big blind" or "bb" = "BB"

Requirements:
1. Only include actually mentioned players
2. Use exact position abbreviations as specified above
3. Detect win/loss based on phrases like "i won", "i want the pot", "paid off"
4. Extract actual names only, not words that contain "player"
5. Only include pot size if specifically mentioned in big blinds

Here is the transcript:
{transcript}

Return ONLY the JSON data structure with the extracted information. Nothing else.
"""

PLAYER_ANALYSIS_PROMPT = """
You are a poker player analyzer. Extract player information in this exact JSON format:

{
    "players": [
        {
            "name": "string (exact name as mentioned)",
            "position": "string (UTG/MP/CO/BTN/SB/BB)",
            "actions": [
                "string (specific actions taken)"
            ],
            "won": "boolean (true/false)"
        }
    ]
}

Requirements:
1. Only include actual player names (John, Mike, etc.)
2. Do not include words that contain "player" as names
3. Include specific actions like "raised to X BB", "called", "folded"
4. Use exact position abbreviations (UTG, MP, CO, BTN, SB, BB)
5. Track who won or lost the hand

Here is the transcript:
{transcript}

Return ONLY the JSON structure. No additional text.
"""

SUMMARY_PROMPT = """
Create a clear, concise summary of this poker hand. Focus on:

1. Who did what (using actual names)
2. Specific positions and actions
3. Bet sizes in big blinds
4. Final outcome

DO NOT include:
- Generic strategy advice
- Assumptions about unseen cards
- Commentary about play style
- Information not in the transcript

Maximum length: 2-3 sentences.

Here is the transcript:
{transcript}
"""

INSIGHT_PROMPT = """
Analyze this poker hand and provide strategic insights. Focus on:

1. Player-specific tendencies shown
2. Position-based decisions
3. Betting patterns
4. Specific outcomes and their implications

Format your response as:
1. Notable Player Tendencies: (specific to players mentioned)
2. Key Decision Points: (actual decisions made)
3. Strategic Implications: (based only on what happened)

Use only information from the transcript:
{transcript}
"""

def get_validation_rules():
    """Returns validation rules for GPT responses"""
    return {
        "hand_data": {
            "required_fields": ["players", "myPosition", "iWon"],
            "optional_fields": ["potSize"],
            "valid_positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
            "name_pattern": r'^[A-Z][a-z]+$'  # Proper names only
        },
        "player_data": {
            "required_fields": ["name", "position", "actions", "won"],
            "valid_positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
            "name_pattern": r'^[A-Z][a-z]+$'  # Proper names only
        }
    }