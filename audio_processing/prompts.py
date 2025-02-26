# prompts.py

HAND_DATA_PROMPT = """
You are a poker hand data extractor. Extract the following exact JSON structure from the transcript:

{
    "players": [
        {
            "name": "string (exactly as mentioned in the transcript)",
            "position": "string (must be UTG/MP/CO/BTN/SB/BB only, or Unknown if position is not explicitly mentioned)",
            "won": "boolean (true/false)"
        }
    ],
    "myPosition": "string (must be UTG/MP/CO/BTN/SB/BB only, or Unknown if position is not explicitly mentioned)",
    "iWon": "boolean (did I win the hand, true/false)",
    "potSize": "number or null (in big blinds, or null if not specifically mentioned)"
}

Player Identification Guidelines:
1. Look for proper nouns that represent player names (typically capitalized in the transcript)
2. Look for phrases like "X raised", "X bet", "X called", "X checked", "X folded" where X is likely a player name
3. Words like "I", "me", "my" refer to the narrator and are not considered player names
4. Common poker terms (flop, turn, river, pot, etc.) are not player names
5. Automated transcription may contain errors - use context to identify likely player names
6. A player name could be any word except poker terminology that is followed by an action verb

Position Mapping (use exact abbreviations):
- "under the gun" or "utg" or "under the turn" = "UTG"
- "middle position" or "mp" = "MP"
- "cutoff" or "co" = "CO"
- "button" or "btn" or "bottom position" = "BTN"
- "small blind" or "sb" = "SB"
- "big blind" or "bb" = "BB"

Win Detection:
- For the narrator ("I"): Look for phrases like "i won", "i want the pot", "i win", "i got paid off", "equal house", "full house"
- For other players: Check if the transcript says they won or shows them winning with a better hand
- If the transcript mentions a showdown, determine the winner based on the hands shown

Requirements:
1. Include ALL players explicitly mentioned in the transcript, even if their position is unknown
2. Use exact position abbreviations as specified above. If position is not explicitly stated, set to "Unknown"
3. Detect win/loss for each player based on the transcript context
4. Extract player names exactly as they appear in the transcript
5. Only include the pot size if it is explicitly mentioned in big blinds
6. Be precise and only include data directly stated in the transcript
7. The transcript may contain transcription errors - try to understand the poker context

Here is the transcript:
{transcript}

Return ONLY the JSON data structure with the extracted information. Ensure the JSON is valid and parsable. Do NOT include any introductory or explanatory text. If you cannot reliably extract the required information, return an empty JSON object: `{}`
"""

PLAYER_ANALYSIS_PROMPT = """
You are a poker player analyzer. Extract player information in this exact JSON format:

{
    "players": [
        {
            "name": "string (exact name as mentioned in the transcript)",
            "position": "string (UTG/MP/CO/BTN/SB/BB, or Unknown if not explicitly mentioned)",
            "actions": [
                "string (specific action taken, e.g., raised to X BB, called, folded)"
            ],
            "won": "boolean (true/false, based on explicit statements in the transcript)"
        }
    ]
}

Player Identification Methods:
1. Look for proper nouns (capitalized words) that are used with action verbs (raised, bet, called, checked, folded)
2. Look for phrases like "Player X" where X might be a name or identifier
3. Identify names by context - look for consistent references to the same entity throughout the transcript
4. Handle transcription errors - names might be misspelled or incorrectly transcribed
5. The word "I" always refers to the narrator, not a player name

Position Identification:
- "under the gun" or "utg" or "under the turn" = "UTG"
- "middle position" or "mp" = "MP"
- "cutoff" or "co" = "CO"
- "button" or "btn" or "bottom position" = "BTN"
- "small blind" or "sb" = "SB"
- "big blind" or "bb" = "BB"

Win Detection:
- Look for explicit statements about who won the hand
- Check for phrases like "won the pot", "took down the pot", "won with", etc.
- If a player shows a winning hand at showdown, mark them as winner
- If the transcript mentions "full house", "equal house", etc. for a player and they won with it

Requirements:
1. Only include actual player names explicitly mentioned in the transcript - no generic terms
2. Don't include words that contain "player" as names unless it's clearly a name
3. Include specific actions taken by each player, as stated in the transcript
4. Use exact position abbreviations (UTG, MP, CO, BTN, SB, BB) or "Unknown"
5. Track who won or lost the hand based on explicit statements in the transcript
6. Capitalize player names properly
7. Handle transcription errors by using context to determine actual player names

Here is the transcript:
{transcript}

Return ONLY the JSON structure. Ensure the JSON is valid and parsable. Do NOT include any introductory or explanatory text. If you cannot reliably extract the required information, return an empty JSON object: `{}`
"""

SUMMARY_PROMPT = """
Create a clear, concise summary of this poker hand. Focus only on information explicitly stated in the transcript.

To account for possible transcription errors:
1. Try to understand the poker context
2. Correct obvious transcription errors when creating the summary
3. Use your understanding of poker terminology to interpret unclear phrases

Include:
1. Who did what (using actual names from the transcript)
2. Specific positions (if mentioned) and actions taken
3. Bet sizes, if mentioned in big blinds
4. The final outcome (who won, if explicitly stated)
5. Key hands shown at showdown (if mentioned)

DO NOT include:
- Generic strategy advice
- Assumptions about unseen cards
- Commentary about play style or player tendencies
- Information not directly present in the transcript

Maximum length: 2-3 sentences.

Here is the transcript:
{transcript}
"""

INSIGHT_PROMPT = """
Analyze this poker hand and provide strategic insights based only on the information explicitly stated in the transcript.

When analyzing, keep in mind that the transcript may contain errors from automated transcription. Try to understand the poker context and interpret accordingly.

Format your response as follows:

1. Notable Player Tendencies: (List any specific actions or tendencies explicitly attributed to players in the transcript. If none, state "None").
2. Key Decision Points: (Identify any critical decisions made in the hand, as stated in the transcript. If none, state "None").
3. Strategic Implications: (Provide strategic implications based only on what happened in this hand, not general poker advice. If none, state "None").

Use only information from the transcript:
{transcript}
"""

def get_validation_rules():
    """Returns validation rules for GPT responses"""
    return {
        "hand_data": {
            "required_fields": ["players", "myPosition", "iWon"],
            "optional_fields": ["potSize"],
            "valid_positions": ["UTG", "MP", "CO", "BTN", "SB", "BB", "Unknown"],
            "name_pattern": r'^[A-Za-z\s]+$'  # Allow letters and spaces in names
        },
        "player_data": {
            "required_fields": ["players"],
            "player_fields": ["name", "position", "actions", "won"],  # Fields for each player object
            "valid_positions": ["UTG", "MP", "CO", "BTN", "SB", "BB", "Unknown"],
            "name_pattern": r'^[A-Za-z\s]+$'  # Allow letters and spaces in names
        }
    }