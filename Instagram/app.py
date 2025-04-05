import os
import requests
import threading
from datetime import datetime
from flask import Flask, jsonify
from flask_socketio import SocketIO
from pymongo import MongoClient
from transformers import pipeline
from dotenv import load_dotenv
import time
from bson.json_util import dumps

import logging
from app2 import *


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
socketio = SocketIO(app,async_mode='threading', cors_allowed_origins="*")

CONFIG = {
    "alert_thresholds": {
        "urgent_keywords": ["crowd", "emergency", "accident"],
    }
}

print("[INFO] Connecting to MongoDB...")
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.event_monitoring
print("[INFO] MongoDB connection established.")

print("[INFO] Loading sentiment and emotion analysis models...")
sentiment_pipeline = pipeline("sentiment-analysis", model="distilbert-base-uncased")
emotion_pipeline = pipeline("text-classification", model="bhadresh-savani/bert-base-uncased-emotion")
print("[INFO] Models loaded successfully.")

last_seen_id = None  # Global tracker


def analyze_tweet(text):
    print(f"[DEBUG] Analyzing tweet: {text}")
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



def store_analysis(post_id, analysis,post):
    print(f"[INFO] Storing analysis for tweet_id: {post_id}")
    if db.feedback_insta.find_one({"post_id": post_id}):
        print("[WARNING] Duplicate tweet found. Skipping insert.")
        return
    analysis["post_id"] = post_id
    #analysis["uri"]=post['uri']
    db.feedback_insta.insert_one(analysis)
    print("[INFO] Tweet analysis stored in feedback collection.")

    db.metrics_insta.update_one(
        {"type": "sentiment"},
        {"$inc": {f"counts.{analysis['sentiment']}": 1}},
        upsert=True
    )
    print("[INFO] Sentiment metrics updated.")


def trigger_alert(analysis):
    print(f"[ALERT] Triggering urgent alert for tweet: {analysis['text']}")
    socketio.emit("alert", {
        "type": "urgent",
        "message": "Immediate attention required!",
        "text": analysis["text"],
        "timestamp": analysis["timestamp"].isoformat()
    })
    print("[ALERT] Alert emitted via SocketIO.")

def fetch_captions_comments():
    posts= fetch_user_posts("virat.kohli")
    for items in posts:
        post_id = items["post_id"]
        #last_seen_id = max(last_seen_id or "0", tweet_id)
        comments=fetch_post_comments(post_id)['comments']
        analysis = analyze_tweet(items["caption"])
        store_analysis(post_id, analysis,items)
        if analysis["urgent"]:
            trigger_alert(analysis)
        for comment in comments:
            analysis1 = analyze_tweet(comment["text"])
            store_analysis_comments(post_id, analysis1)




def store_analysis_comments(tweet_id, analysis):
    print(f"[INFO] Storing analysis for tweet_id: {tweet_id}")
    if db.feedback_comments_insta.find_one({"post_id": tweet_id}):
        print("[WARNING] Duplicate post found. Skipping insert.")
        return
    analysis["post_id"] = tweet_id
    db.feedback_comments_insta.insert_one(analysis)
    print("[INFO] Tweet analysis stored in feedback collection.")

    db.metrics_comments_insta.update_one(
        {"type": "sentiment"},
        {"$inc": {f"counts.{analysis['sentiment']}": 1}},
        upsert=True
    )
    print("[INFO] Sentiment metrics updated.")





# def test():
    
#     m=db.metrics_comments.find()
#     m1=dumps(m)
#     #print(m1)
#     socketio.emit("update",{"t":99})
#     #logger.info(f"[SOCKET] Metrics emitted: {99}")
#     time.sleep(2)
#     threading.Timer(3, test).start()

# def start_loop():
#     socketio.sleep(3)
#     test()

@app.route("/dashboard")
def dashboard():
    print("[INFO] Dashboard API hit.")
    metrics = db.metrics.find_one({"type": "sentiment"}) or {}
    counts = metrics.get("counts", {})
    print(f"[INFO] Current sentiment counts: {counts}")
    return jsonify({
        "positive": counts.get("POSITIVE", 0),
        "negative": counts.get("NEGATIVE", 0),
        "neutral": counts.get("NEUTRAL", 0)
    })


if __name__ == "__main__":
    print("[INFO] Starting tweet fetcher and Flask server...")
    
    #fetch_tweets()
    #test()
    #socketio.start_background_task(start_loop)
    fetch_captions_comments()
    socketio.run(app, port=5000, debug=True)