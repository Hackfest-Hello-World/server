import os
import threading
from datetime import datetime
from flask import Flask, jsonify, session, redirect, request
from flask_socketio import SocketIO
from pymongo import MongoClient
from transformers import pipeline
from dotenv import load_dotenv
import google_auth_oauthlib.flow
import googleapiclient.discovery
import google
import time
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "sentinel-dashboard-secret")
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# Configuration
CONFIG = {
    "alert_thresholds": {
        "urgent_keywords": ["crowd", "emergency", "accident"],
    }
}

# YouTube API settings
CLIENT_SECRETS_FILE = "client_secrets.json"
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

# MongoDB setup
print("[INFO] Connecting to MongoDB...")
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.event_monitoring
print("[INFO] MongoDB connection established.")

# AI models setup
print("[INFO] Loading sentiment analysis models...")
sentiment_pipeline = pipeline("sentiment-analysis", model="distilbert-base-uncased")
emotion_pipeline = pipeline("text-classification", model="bhadresh-savani/bert-base-uncased-emotion")
print("[INFO] Models loaded successfully.")

def calculate_percentage(value, total):
    return round((value / total) * 100, 2) if total > 0 else 0

def analyze_text(text):
    sentiment = sentiment_pipeline(text)[0]
    emotions = emotion_pipeline(text)
    urgent = any(kw in text.lower() for kw in CONFIG['alert_thresholds']['urgent_keywords'])
    return {
        "text": text,
        "sentiment": sentiment["label"],
        "confidence": sentiment["score"],
        "emotions": emotions,
        "urgent": urgent,
        "timestamp": datetime.utcnow()
    }

def store_youtube_analysis(comment_id, analysis, video_id=None):
    if db.feedback_youtube.find_one({"comment_id": comment_id}):
        return
    analysis["comment_id"] = comment_id
    if video_id:
        analysis["video_id"] = video_id
    db.feedback_youtube.insert_one(analysis)
    db.metrics_youtube.update_one(
        {"type": "sentiment"},
        {"$inc": {f"counts.{analysis['sentiment']}": 1}},
        upsert=True
    )

def trigger_alert(analysis):
    socketio.emit("alert", {
        "type": "urgent",
        "message": "Immediate attention required!",
        "text": analysis["text"],
        "timestamp": analysis["timestamp"].isoformat()
    })

@app.route('/youtube-analysis')
def youtube_analysis():
    metrics = db.metrics_youtube.find_one({"type": "sentiment"}) or {"counts": {}}
    counts = metrics.get("counts", {})
    total = sum(counts.values())
    
    return jsonify({
        "platform": "YouTube",
        "stats": {
            "positive": calculate_percentage(counts.get("LABEL_1", 0), total),
            "negative": calculate_percentage(counts.get("LABEL_0", 0), total),
            "neutral": calculate_percentage(counts.get("NEUTRAL", 0), total),
            "total": total
        },
        "recent_comments": list(db.feedback_youtube.find({}, {"_id": 0}).sort("timestamp", -1).limit(10))
    })

@app.route('/authorize')
def authorize():
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = request.base_url + '/callback'
    authorization_url, state = flow.authorization_url(access_type='offline')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/authorize/callback')
def oauth2callback():
    state = session['state']
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = request.base_url
    flow.fetch_token(authorization_response=request.url)
    
    credentials = flow.credentials
    session['credentials'] = credentials_to_dict(credentials)
    
    # Start background processing after successful auth
    threading.Thread(target=fetch_and_analyze_youtube_comments).start()
    
    return redirect('/youtube-analysis')

def credentials_to_dict(credentials):
    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

def fetch_and_analyze_youtube_comments():
    with app.app_context():
        if 'credentials' not in session:
            logger.error("No credentials found in session")
            return

        credentials = google.oauth2.credentials.Credentials(**session['credentials'])
        youtube = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

        while True:
            try:
                videos_response = youtube.videos().list(
                    part="snippet",
                    chart="mostPopular",
                    regionCode="IN",
                    maxResults=10
                ).execute()

                for video in videos_response.get("items", []):
                    process_video_comments(youtube, video['id'])
                    
                time.sleep(300)  # 5 minute interval

            except Exception as e:
                logger.error(f"Comment processing failed: {str(e)}")
                time.sleep(60)

def process_video_comments(youtube, video_id):
    try:
        comments_response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            textFormat="plainText"
        ).execute()

        for item in comments_response["items"]:
            comment = item["snippet"]["topLevelComment"]["snippet"]
            analysis = analyze_text(comment["textDisplay"])
            store_youtube_analysis(item["id"], analysis, video_id)
            
            if analysis["urgent"]:
                trigger_alert(analysis)

        logger.info(f"Processed {len(comments_response['items'])} comments for video {video_id}")
        time.sleep(1)  # Respect API rate limits

    except Exception as e:
        logger.error(f"Failed to process comments for video {video_id}: {str(e)}")

if __name__ == "__main__":
    print("[INFO] Starting YouTube sentiment analysis server...")
    socketio.run(app, port=5000, debug=True)
    fetch_and_analyze_youtube_comments()
