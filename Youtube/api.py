import os
import requests
import threading
from datetime import datetime, timezone, timedelta
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

# Disable HTTPS verification for local development
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

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

print("[INFO] Connecting to MongoDB...")
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.event_monitoring
print("[INFO] MongoDB connection established.")

print("[INFO] Loading sentiment and emotion analysis models...")
sentiment_pipeline = pipeline("sentiment-analysis", model="distilbert-base-uncased")
emotion_pipeline = pipeline("text-classification", model="bhadresh-savani/bert-base-uncased-emotion")
print("[INFO] Models loaded successfully.")

def calculate_percentage(value, total):
    return round((value / total) * 100, 2) if total > 0 else 0

def analyze_text(text):
    print(f"[DEBUG] Analyzing text: {text}")
    sentiment = sentiment_pipeline(text)[0]
    emotions = emotion_pipeline(text)
    urgent = any(kw in text.lower() for kw in CONFIG['alert_thresholds']['urgent_keywords'])
    print(f"[DEBUG] Sentiment: {sentiment}, Urgent: {urgent}, Emotions: {emotions}")
    return {
        "text": text,
        "sentiment": sentiment["label"],
        "confidence": sentiment["score"],
        "emotions": emotions,
        "urgent": urgent,
        "timestamp": datetime.utcnow()
    }

def store_youtube_analysis(comment_id, analysis, video_id=None):
    print(f"[INFO] Storing analysis for comment_id: {comment_id}")
    if db.feedback_youtube.find_one({"comment_id": comment_id}):
        print("[WARNING] Duplicate comment found. Skipping insert.")
        return
    
    analysis["comment_id"] = comment_id
    if video_id:
        analysis["video_id"] = video_id
    
    db.feedback_youtube.insert_one(analysis)
    print("[INFO] YouTube comment analysis stored in feedback collection.")

    db.metrics_youtube.update_one(
        {"type": "sentiment"},
        {"$inc": {f"counts.{analysis['sentiment']}": 1}},
        upsert=True
    )
    print("[INFO] Sentiment metrics updated.")

def trigger_alert(analysis):
    print(f"[ALERT] Triggering urgent alert: {analysis['text']}")
    socketio.emit("alert", {
        "type": "urgent",
        "message": "Immediate attention required!",
        "text": analysis["text"],
        "timestamp": analysis["timestamp"].isoformat()
    })
    print("[ALERT] Alert emitted via SocketIO.")

@app.route('/youtube-analysis')
def youtube_analysis():
    print("[INFO] YouTube Analysis API hit.")
    metrics = db.metrics_youtube.find_one({"type": "sentiment"}) or {"counts": {}}
    counts = metrics.get("counts", {})
    total = sum(counts.values())
    
    # Get recent comments
    recent_comments = list(db.feedback_youtube.find({}, {"_id": 0, "text": 1, "sentiment": 1, "timestamp": 1, "video_id": 1}).sort("timestamp", -1).limit(10))
    
    return jsonify({
        "platform": "YouTube",
        "stats": {
            "comments": {
                "positive": {"count": counts.get("POSITIVE", 0), "percentage": calculate_percentage(counts.get("POSITIVE", 0), total)},
                "negative": {"count": counts.get("NEGATIVE", 0), "percentage": calculate_percentage(counts.get("NEGATIVE", 0), total)},
                "neutral": {"count": counts.get("NEUTRAL", 0), "percentage": calculate_percentage(counts.get("NEUTRAL", 0), total)},
                "total": total
            }
        },
        "recent_comments": recent_comments
    })

@app.route('/authorize')
def authorize():
    # Create flow instance to manage the OAuth 2.0 Authorization Grant Flow
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    
    # Set the redirect URI
    flow.redirect_uri = request.base_url + '/callback'
    
    # Generate URL for request to Google's OAuth 2.0 server
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')
    
    # Store the state in the session for later validation
    session['state'] = state
    
    # Redirect the user to Google's OAuth 2.0 server
    return redirect(authorization_url)

@app.route('/authorize/callback')
def oauth2callback():
    # Specify the state when creating the flow in the callback
    state = session['state']
    
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = request.base_url
    
    # Use the authorization server's response to fetch the OAuth 2.0 tokens
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)
    
    # Store credentials in the session
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    # Start processing comments after authorization
    fetch_and_analyze_youtube_comments()
    
    return redirect('/youtube-analysis')

@app.route('/get_videos')
def get_videos():
    if 'credentials' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Load credentials from the session
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    
    # Build the YouTube API client
    youtube = googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)
    
    # First, get the uploads playlist ID for the authenticated user
    channels_response = youtube.channels().list(
        part="contentDetails",
        mine=True
    ).execute()
    
    # Get the uploads playlist ID
    uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    
    # Get videos from the uploads playlist
    videos = []
    next_page_token = None
    
    while True:
        playlist_items_response = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page_token
        ).execute()
        
        for item in playlist_items_response['items']:
            video = {
                'id': item['contentDetails']['videoId'],
                'title': item['snippet']['title'],
                'description': item['snippet']['description'],
                'publishedAt': item['snippet']['publishedAt'],
                'thumbnails': item['snippet']['thumbnails']
            }
            videos.append(video)
        
        next_page_token = playlist_items_response.get('nextPageToken')
        if not next_page_token:
            break
    
    return jsonify(videos)

@app.route('/get_comments/<video_id>')
def get_comments(video_id):
    if 'credentials' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    # Load credentials from the session
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    
    # Build the YouTube API client
    youtube = googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)
    
    # Get comments for the specified video
    comments = []
    next_page_token = None
    
    while True:
        comments_response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            pageToken=next_page_token,
            textFormat="plainText"
        ).execute()
        
        for item in comments_response['items']:
            comment = item['snippet']['topLevelComment']['snippet']
            comments.append({
                'id': item['id'],
                'author': comment['authorDisplayName'],
                'text': comment['textDisplay'],
                'likeCount': comment['likeCount'],
                'publishedAt': comment['publishedAt']
            })
        
        next_page_token = comments_response.get('nextPageToken')
        if not next_page_token:
            break
    
    return jsonify(comments)

def fetch_and_analyze_youtube_comments():
    if 'credentials' not in session:
        print("[WARNING] Not authenticated for YouTube API")
        return
    
    print("[INFO] Fetching YouTube comments for sentiment analysis...")
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    youtube = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
    
    # Get trending videos
    try:
        videos_response = youtube.videos().list(
            part="snippet,contentDetails,statistics",
            chart="mostPopular",
            regionCode="IN",  # India
            maxResults=10
        ).execute()
        
        for video in videos_response.get("items", []):
            video_id = video["id"]
            
            # Get comments for each video
            try:
                comments_response = youtube.commentThreads().list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=50,
                    textFormat="plainText"
                ).execute()
                
                for item in comments_response["items"]:
                    comment = item["snippet"]["topLevelComment"]["snippet"]
                    comment_id = item["id"]
                    text = comment["textDisplay"]
                    
                    # Analyze sentiment
                    analysis = analyze_text(text)
                    store_youtube_analysis(comment_id, analysis, video_id)
                    
                    if analysis.get("urgent", False):
                        trigger_alert(analysis)
                
                print(f"[INFO] Processed comments for video {video_id}")
                
            except Exception as e:
                print(f"[ERROR] Failed to process comments for video {video_id}: {e}")
            
            # Avoid rate limiting
            time.sleep(1)
            
    except Exception as e:
        print(f"[ERROR] YouTube data fetching failed: {e}")
    
    print("[INFO] YouTube data collection complete. Scheduling next run in 5 minutes.")
    threading.Timer(300, fetch_and_analyze_youtube_comments).start()

def start_youtube_listener():
    print("[INFO] Starting YouTube comment analyzer...")
    if 'credentials' in session:
        threading.Timer(5, fetch_and_analyze_youtube_comments).start()

if __name__ == "__main__":
    print("[INFO] Starting YouTube sentiment analysis server...")
    socketio.run(app, port=5002, debug=True)
