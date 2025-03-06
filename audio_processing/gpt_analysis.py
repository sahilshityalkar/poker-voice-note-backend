# gpt_analysis.py

import os
from typing import Dict, Any
from openai import AsyncOpenAI
from dotenv import load_dotenv
from .prompts import (
    SUMMARY_PROMPT,
    INSIGHT_PROMPT
)

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

async def generate_summary(transcript: str) -> str:
    """Generate a summary of the poker hand"""
    try:
        print(f"[GPT] Generating summary for transcript of length {len(transcript)}")
        prompt = SUMMARY_PROMPT.format(transcript=transcript)
        result = await get_gpt_response(
            prompt=prompt,
            system_message="You are a poker assistant. Summarize this hand clearly and concisely."
        )
        print(f"[GPT] Summary generated: {len(result)} characters")
        return result
    except Exception as e:
        print(f"[GPT] Error generating summary: {e}")
        return "Summary generation failed."

async def generate_insight(transcript: str) -> str:
    """Generate insights for the poker hand"""
    try:
        print(f"[GPT] Generating insights for transcript of length {len(transcript)}")
        prompt = INSIGHT_PROMPT.format(transcript=transcript)
        result = await get_gpt_response(
            prompt=prompt,
            system_message="You are a poker coach. Provide insightful analysis."
        )
        print(f"[GPT] Insights generated: {len(result)} characters")
        return result
    except Exception as e:
        print(f"[GPT] Error generating insight: {e}")
        return "Insight generation failed."

# Keep this function for backward compatibility if needed
async def process_transcript(transcript: str) -> Dict[str, Any]:
    """Process a transcript to extract summary and insights"""
    result = {
        "summary": "",
        "insight": ""
    }
    
    print(f"[GPT] Processing transcript: {len(transcript)} characters")
    
    try:
        # Generate summary
        result["summary"] = await generate_summary(transcript)
        
        # Generate insight
        result["insight"] = await generate_insight(transcript)
        
        print("[GPT] Transcript processing complete")
        
    except Exception as e:
        print(f"[GPT] Error in overall transcript processing: {e}")
        result["summary"] = "Summary generation failed."
        result["insight"] = "Insight generation failed."
    
    return result