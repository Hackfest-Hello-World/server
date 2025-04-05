import os
from typing import Union, List
from groq import Groq

def groq_llm_promt(
    prompt: str,
    model: str = "llama3-70b-8192",
    max_tokens: int = 4096
) -> Union[str, dict, list]:
    """
    Process multi-platform data with format instructions embedded in the prompt.
    
    Parameters:
    - prompt: Must contain explicit format instructions (e.g., "Return JSON with...")
    - data: Input from social media, surveys, etc. (list or string)
    - model: Groq model to use
    
    Returns formatted response based on prompt instructions
    """
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    # System message to enforce format control
    system_msg = """You are a data processing engine and have to act as an expert in sentiment analysis prediction. Follow these rules:
    1. Strictly adhere to format instructions in the user prompt
    2. Maintain original data semantics from different platforms
    3. Handle emojis, slang, and platform-specific lingo
    4. Return EXACTLY the format requested in the prompt"""

    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            model=model,
            temperature=0.3,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"