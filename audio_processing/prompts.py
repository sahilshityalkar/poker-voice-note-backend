# prompts.py

HAND_DATA_PROMPT = """
You are a professional poker data analyzer specializing in hand history extraction. Extract the following JSON structure from the transcript:

{{
"players": [
{{
"name": "string (exactly as mentioned in the transcript)",
"position": "string (must be UTG/MP/CO/BTN/SB/BB only)",
"won": "boolean (true/false)"
}}
],
"myPosition": "string (must be UTG/MP/CO/BTN/SB/BB only)",
"iWon": "boolean (did I win the hand, true/false)",
"potSize": "number or null (in big blinds, or null if not specifically mentioned)"
}}

CRITICAL RULES:

Player Names vs. Positions:

Player names are ALWAYS actual names (e.g., Ryan, Bob). NEVER use positional terms (e.g., "button", "BB") as names.

If the transcript says "Button raises" or "BB calls", associate these actions with the player already assigned to that position (e.g., if "Ryan is on the button", then "Button raises" = Ryan's action).

Position labels (BTN, SB, BB, etc.) are NOT player names unless explicitly part of a name (e.g., a player named "BTN Smith").

Position Inference:

If positions are not explicitly stated, infer them strictly using:

Betting order (first preflop actor = UTG, last = BB).

Action sequence (post-flop actions hint at positions).

Explicit context (e.g., "Ryan is the dealer" = BTN).

Example: If the transcript says "Ryan bets, Bob folds, Martin checks", infer positions as UTG (Ryan), MP (Bob), CO (Martin) based on betting order.

Win Detection:

For the narrator ("I"), check phrases like "I won" or "my flush took the pot".

For others, use explicit wins (e.g., "Martin showed a straight and won") or showdown results.

REQUIREMENTS:

ALL players must have a position (UTG/MP/CO/BTN/SB/BB). NO "Unknown".

Names must match the transcript EXACTLY (e.g., "Ryan", not "Button").

If the transcript uses positional terms (e.g., "SB") without a name, infer the name from prior context (e.g., "Bob posted the SB" → SB = Bob).

EXAMPLE:
Transcript:
"Ryan (BTN) raised. Martin in SB called. BB folded. Ryan won with a flush."

Output:
{{
"players": [
{{"name": "Ryan", "position": "BTN", "won": true}},
{{"name": "Martin", "position": "SB", "won": false}}
],
"myPosition": "BTN",
"iWon": true,
"potSize": null
}}

Transcript to Analyze:
{transcript}

Return ONLY JSON. No explanations.
"""

PLAYER_ANALYSIS_PROMPT = """
You are a professional poker player analyst. Extract player information in this exact JSON format:

{
    "players": [
        {
            "name": "string (exact name as mentioned in the transcript)",
            "position": "string (UTG/MP/CO/BTN/SB/BB)",
            "actions": [
                "string (specific action taken, e.g., raised to X BB, called, folded)"
            ],
            "won": "boolean (true/false, based on explicit statements in the transcript)"
        }
    ]
}

IMPORTANT: When positions aren't explicitly stated, you must infer them based on:
1. Betting order (first to act preflop is typically UTG, followed by MP, CO, BTN, SB, BB)
2. Action sequence (the order players act can reveal their positions)
3. Context clues (references to position even if abbreviations aren't used)

Position Inference Guidelines:
- First player to act pre-flop is typically UTG (Under the Gun)
- Last player to act pre-flop is typically BB (Big Blind)
- Second-to-last player to act pre-flop is typically SB (Small Blind) 
- Player acting right before SB is typically BTN (Button)
- If only 2-3 players are mentioned, use context to determine if they're in late positions (BTN/SB/BB)
- DO NOT leave positions as "Unknown" - make a reasonable inference based on betting sequence

Player Identification Methods:
1. Look for proper nouns (capitalized words) that are used with action verbs
2. Look for consistent references to the same entity throughout the transcript
3. Handle transcription errors - names might be misspelled or incorrectly transcribed
4. The word "I" always refers to the narrator, not a player name

Position Mapping:
- "under the gun" or "utg" or "under the turn" or "first to act" = "UTG"
- "middle position" or "mp" or "mid position" = "MP"
- "cutoff" or "co" or "cut off" = "CO"
- "button" or "btn" or "bottom position" or "dealer" = "BTN"
- "small blind" or "sb" = "SB"
- "big blind" or "bb" = "BB"

Win Detection:
- Look for explicit statements about who won the hand
- Check for phrases like "won the pot", "took down the pot", "won with", etc.
- If a player shows a winning hand at showdown, mark them as winner
- If the transcript mentions "full house", "flush", etc. for a player, they likely won

Requirements:
1. Only include actual player names mentioned in the transcript
2. ALWAYS assign positions for each player - NEVER use "Unknown" for position
3. Include specific actions taken by each player, as stated in the transcript
4. Track who won or lost the hand based on explicit statements
5. Handle transcription errors by using context to determine actual player names and actions

Here is the transcript:
{transcript}

Return ONLY the JSON structure with no introductory or explanatory text. ENSURE every player has a position assigned (no "Unknown" positions).
"""

SUMMARY_PROMPT = """
Create a clear, concise summary of this poker hand. Focus on information stated or clearly implied in the transcript.

To account for possible transcription errors:
1. Try to understand the poker context
2. Correct obvious transcription errors when creating the summary
3. Use your understanding of poker terminology to interpret unclear phrases

Include:
1. Who did what (using actual names from the transcript)
2. Specific positions of players (if mentioned or inferable)
3. Bet sizes, if mentioned in big blinds
4. The final outcome (who won, if explicitly stated)
5. Key hands shown at showdown (if mentioned)

DO NOT include:
- Generic strategy advice
- Assumptions about unseen cards
- Commentary about play style or player tendencies
- Information not directly present or strongly implied in the transcript

Maximum length: 2-3 sentences.

Here is the transcript:
{transcript}
"""

INSIGHT_PROMPT = """
Analyze this poker hand and provide strategic insights based on the information stated or clearly implied in the transcript.

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
            "valid_positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
            "name_pattern": r'^[A-Za-z\s]+$'  # Allow letters and spaces in names
        },
        "player_data": {
            "required_fields": ["players"],
            "player_fields": ["name", "position", "actions", "won"],  # Fields for each player object
            "valid_positions": ["UTG", "MP", "CO", "BTN", "SB", "BB"],
            "name_pattern": r'^[A-Za-z\s]+$'  # Allow letters and spaces in names
    }
}