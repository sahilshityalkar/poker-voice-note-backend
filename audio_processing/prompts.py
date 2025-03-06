# prompts.py

SUMMARY_PROMPT = """
Create a brief, clear summary of this poker hand. Focus on the key actions, decisions, and the outcome.

Keep your summary concise (2-3 sentences) and include:
1. Starting cards (if mentioned)
2. Key betting actions
3. Final outcome
4. Notable plays

Transcript:
{transcript}
"""

INSIGHT_PROMPT = """
Analyze this poker hand and provide strategic insights. Focus on:

1. Notable Player Tendencies: 
   What patterns or tendencies did players exhibit that could be exploited?

2. Key Decision Points:
   Identify 2-3 critical decision points in the hand.

3. Strategic Implications:
   What strategic insights can be drawn from this hand?

Be specific and focus on actionable insights that would help improve play.

Transcript:
{transcript}
"""

def get_validation_rules():
    """Returns validation rules for GPT responses"""
    return {
        "player_extraction": {
            "required_fields": ["players"],
            "name_pattern": r'^[A-Za-z\s]+$'  # Allow letters and spaces in names
        }
    }