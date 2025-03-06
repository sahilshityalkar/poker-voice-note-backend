# gpt_analysis.py

import os
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def get_gpt_response(prompt: str, system_message: str = "You are a helpful assistant.") -> str:
    """Get a response from GPT with the given prompt"""
    try:
        print(f"[GPT] Starting GPT-4o call with prompt: {prompt[:50]}...")
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        
        print("[GPT] GPT-4o API call successful")
        result = response.choices[0].message.content
        return result
    
    except Exception as e:
        print(f"[GPT] Error in GPT-4o API call: {e}")
        return ""

async def process_transcript(transcript: str, language: str = "en") -> Optional[Dict[str, Any]]:
    """Process transcript to generate summary and insight in the specified language"""
    try:
        print(f"[PROCESS] Processing transcript in language: {language}")
        
        # Check if transcript is empty or too short
        if not transcript or len(transcript.strip()) < 10:
            print(f"[PROCESS] Transcript is too short or empty: '{transcript}'")
            return {
                "summary": f"The audio recording was too short or didn't contain any recognizable text in {language}.",
                "insight": f"No poker hand could be analyzed as the recording didn't contain sufficient content in {language}.",
                "players": []
            }
        
        # Create a comprehensive prompt for GPT to analyze the entire hand
        prompt = f"""You are a professional poker analyst with expertise in analyzing poker hands across all languages and speaking styles. Analyze this transcript and provide a complete analysis in {language}.

Transcript:
{transcript}

Your task is to:
1. Determine if this is a valid poker hand discussion by analyzing the content, context, and language patterns
2. If it is a valid hand:
   - Create a clear summary of the hand
   - Provide strategic insights and analysis
   - Identify players and their actions
   - Analyze key decisions and outcomes
3. If it's not a valid hand, explain why

Important Guidelines:
- ALL content must be in {language}, including:
  * Player names (use the most natural form in {language})
  * Player descriptions
  * Summary and insights
  * Error messages
  * All text and HTML content
- Consider all possible ways players might be referenced in {language}
- Account for transcription errors and variations in speech
- Handle any language-specific poker terminology
- Consider cultural and regional variations in poker discussions
- Be flexible with different speaking styles and formats
- Focus on the actual content and context, not just keywords

Format your response as JSON:
{{
    "is_valid_hand": true/false,
    "summary": "A clear, concise summary of the hand in {language}",
    "insight": "Detailed strategic analysis and insights in {language}",
    "players": [
        {{
            "name": "Player name in {language}",
            "description_text": "Detailed analysis of player's actions and decisions in {language}",
            "description_html": "<p><strong>Player Name in {language}</strong> had <em>[cards if known]</em>.</p><p>Their play was <em>[aggressive/passive/balanced]</em>.</p><ul><li><strong>Strengths:</strong> [good decisions in {language}]</li><li><strong>Weaknesses:</strong> [mistakes in {language}]</li><li><strong>Watch for:</strong> [tendencies in {language}]</li><li><strong>Counter-strategy:</strong> [how to play against them in {language}]</li></ul>"
        }}
    ]
}}

If the hand is invalid, return:
{{
    "is_valid_hand": false,
    "error_message": "A clear explanation in {language} of why this is not a valid poker hand"
}}

IMPORTANT: Your response MUST be valid JSON. Do not include any explanations, markdown formatting, code blocks, or text outside of the JSON.
"""
        
        # Get response from GPT
        result = await get_gpt_response(
            prompt=prompt,
            system_message=f"You are a professional poker analyst with expertise in analyzing poker hands in {language}. Your analysis should be thorough, flexible, and consider all possible interpretations. ALL content must be in {language}. ALWAYS return valid JSON only, with no text before or after."
        )
        
        # Print first 200 chars of result for debugging
        print(f"[PROCESS] GPT raw response (first 200 chars): '{result[:200]}'")
        
        # Clean up the response to ensure it's valid JSON
        cleaned_result = result.strip()
        
        # If response is wrapped in ```json and ``` markdown code blocks, remove them
        if cleaned_result.startswith("```json"):
            cleaned_result = cleaned_result.replace("```json", "", 1)
        if cleaned_result.startswith("```"):
            cleaned_result = cleaned_result.replace("```", "", 1)
        if cleaned_result.endswith("```"):
            cleaned_result = cleaned_result[:-3]
            
        # Find JSON content if there's text before or after
        json_start = cleaned_result.find('{')
        json_end = cleaned_result.rfind('}')
        
        if json_start != -1 and json_end != -1 and json_end > json_start:
            # Extract just the JSON part
            cleaned_result = cleaned_result[json_start:json_end+1]
            print(f"[PROCESS] Extracted JSON content from response")
        
        cleaned_result = cleaned_result.strip()
        print(f"[PROCESS] Cleaned result (first 200 chars): '{cleaned_result[:200]}'")
        
        try:
            # Parse the JSON response
            data = json.loads(cleaned_result)
            print(f"[PROCESS] Successfully parsed JSON response")
            
            # If not a valid hand, return error but with a better format
            if not data.get("is_valid_hand", False):
                error_msg = data.get("error_message", f"This doesn't appear to be a valid poker hand discussion in {language}.")
                print(f"[PROCESS] Not a valid hand: {error_msg}")
                return {
                    "summary": f"Not a valid poker hand: {error_msg}",
                    "insight": f"This recording doesn't contain a valid poker hand discussion. {error_msg}",
                    "players": []
                }
            
            # Return the complete analysis
            return {
                "summary": data.get("summary", ""),
                "insight": data.get("insight", ""),
                "players": data.get("players", [])
            }
            
        except json.JSONDecodeError as e:
            print(f"[PROCESS] JSON parsing error: {e}")
            print(f"[PROCESS] Failed to parse: '{cleaned_result[:100]}...'")
            
            # Return a more helpful error message
            fallback_summary = "Unable to analyze this poker hand recording due to processing error."
            fallback_insight = f"The system couldn't properly analyze this recording. It may contain poker content, but our AI couldn't process it correctly. Error: {str(e)}"
            
            # Try to create a simple summary directly from the transcript
            if "raise" in transcript.lower() and "call" in transcript.lower():
                fallback_summary = f"This recording appears to discuss a poker hand (mentions of raises and calls detected), but our system couldn't fully analyze it."
                fallback_insight = f"The recording likely contains poker content, but our AI had trouble processing it. You might want to try recording again with clearer audio or more structured description."
            
            return {
                "summary": fallback_summary,
                "insight": fallback_insight,
                "players": []
            }
        
    except Exception as e:
        print(f"[PROCESS] Error processing transcript: {e}")
        return {
            "summary": f"Error processing transcript in {language}. Please try again.",
            "insight": f"An unexpected error occurred while analyzing this recording: {str(e)}",
            "players": []
        }