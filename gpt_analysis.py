# gpt_analysis.py

import os
import openai
from dotenv import load_dotenv
from prompts import SUMMARY_PROMPT, INSIGHT_PROMPT

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

async def generate_summary(transcript: str) -> str:
    """Generates a summary of the transcript using GPT."""
    prompt = SUMMARY_PROMPT.format(transcript=transcript)
    try:
        completion = openai.chat.completions.create(
            model="gpt-3.5-turbo",  # Or your preferred model
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            n=1,
            stop=None,
            temperature=0.7,
        )
        summary = completion.choices[0].message.content.strip()
        return summary
    except Exception as e:
        print(f"Error generating summary: {e}")
        return None

async def generate_insight(transcript: str) -> str:
    """Generates insights from the transcript using GPT."""
    prompt = INSIGHT_PROMPT.format(transcript=transcript)
    try:
        completion = openai.chat.completions.create(
            model="gpt-3.5-turbo",  # Or your preferred model
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            n=1,
            stop=None,
            temperature=0.7,
        )
        insight = completion.choices[0].message.content.strip()
        return insight
    except Exception as e:
        print(f"Error generating insight: {e}")
        return None