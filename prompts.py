# prompts.py

SUMMARY_PROMPT = """
You are a poker game summarization expert. Your task is to create a concise and informative summary of a conversation.

The conversation involves one or more players discussing a poker game.  The summary should:

*   Provide a high-level overview of the key events, decisions, and statements made by the players.
*   Identify any key players and their actions, if they are mentioned by name.
*   Capture the overall sentiment or tone of the conversation (e.g., excitement, frustration, strategic discussion).
* Focus on the core subject the players are discussing.

Here is the conversation:
{transcript}
"""

INSIGHT_PROMPT = """
You are a poker game analysis expert. Your task is to extract key insights from a conversation of poker players.

The conversation involves one or more players discussing a poker game.  The insights should include:

*   Potential player strategies being discussed or employed.
*   Any specific hands or situations that are analyzed or debated.
*   Information about table dynamics, player tendencies, or perceived advantages/disadvantages.
*   Key areas of focus: The player names or the core game they are playing.

Here is the conversation:
{transcript}
"""