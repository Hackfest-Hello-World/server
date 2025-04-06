from  groq_service.groq_promt import groq_llm_promt
import json
from pymongo import MongoClient
from dotenv import load_dotenv
import os
print("[INFO] Connecting to MongoDB...")
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.event_monitoring
print("[INFO] MongoDB connection established.")



def alert(message,id,url,source):
    print("sentiment analysis not found in response")
    prompt = '''You are an Event Issue Detection System analyzing attendee feedback at live events. Your task is to determine if a message contains a complaint or issue that requires organizer attention.

    ## Classification Task:
    Analyze the provided message and classify it as either "ISSUE" (requires attention) or "NOT_ISSUE" (general comment, positive feedback, or question).

    ## Issue Categories to Monitor:
    1. Wait Times - Long queues at entrances, food stalls, bathrooms, etc.
    2. Technical Problems - Audio/visual issues, streaming problems, app malfunctions
    3. Comfort & Amenities - Temperature issues, seating problems, facility cleanliness
    4. Overcrowding - Dangerous congestion, space constraints, blocking of pathways
    5. Safety Concerns - Hazards, security issues, medical emergencies
    6. Staff Behavior - Rudeness, inefficiency, or other staff-related problems
    7. Content Issues - Speaker/performer problems, scheduling confusions

    ## Severity Levels:
    - Critical: Immediate action required (safety risks, widespread technical failures)
    - High: Urgent attention needed (significant disruptions affecting many attendees)
    - Medium: Should be addressed soon (notable issues affecting event experience)
    - Low: Minor issues that should be logged but aren't urgent

    ## Response Format:
    {
    "classification": "ISSUE" or "NOT_ISSUE",
    "confidence": [number between 0-1],
    "category": [if ISSUE, provide the most relevant category],
    "severity": [if ISSUE, rate as Critical/High/Medium/Low],
    "reasoning": [brief explanation of classification decision],
    "suggested_action": [if ISSUE, brief recommendation]
    }

    ## Message to analyze:\n'''+message




    #   print(prompt)
    groq_response = groq_llm_promt(prompt)
    try:
        groq_response = json.loads(groq_response)
        if(groq_response['severity']=='High'):
            groq_response['post_id']=id
            groq_response['url']=url
            groq_response['source']=source
            groq_response['checked']='False'
            db.alerts.insert_one(groq_response)
        print(groq_response)
    except json.JSONDecodeError:
        print("Error decoding JSON response from Groq")
        groq_response = {
            "sentiment": "unknown",
            "confidence": 0.0
        }


def analysis11111(text):
    prompt='''
        ou are a sentiment analysis expert. Analyze the following text and classify it as exactly one of these categories: "POSITIVE", "NEGATIVE", or "NEUTRAL".

Guidelines:
- LABEL_1: Text expressing approval, happiness, satisfaction, optimism, or praise ( for POSITIVE )
- LABEL_0: Text expressing disapproval, sadness, disappointment, pessimism, anger, or criticism ( for NEGATIVE )
- LABEL_2: Text that is factual, objective, or doesn't express a clear positive or negative sentiment ( for NEUTRAL )

Provide only the category label ("LABEL_1", "LABEL_0", or "LABEL_2") as your response, with no additional explanation or text.\n'''+ text


            



    groq_response = groq_llm_promt(prompt)
    
    return groq_response

def alert1(count):
    data={}
    data['message']='overcrowding'
    data['count']=count
    db.overcrowding.insert_one(data)