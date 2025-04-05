import os
import requests
import threading
from datetime import datetime
from flask import Flask, jsonify
from flask_socketio import SocketIO
from pymongo import MongoClient
from transformers import pipeline
from dotenv import load_dotenv
from app_comments import fetch_comments
import time
from bson.json_util import dumps

import logging


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



def store_analysis(tweet_id, analysis,tweet):
    print(f"[INFO] Storing analysis for tweet_id: {tweet_id}")
    if db.feedback.find_one({"tweet_id": tweet_id}):
        print("[WARNING] Duplicate tweet found. Skipping insert.")
        return
    analysis["tweet_id"] = tweet_id
    analysis["uri"]=tweet['uri']
    db.feedback.insert_one(analysis)
    print("[INFO] Tweet analysis stored in feedback collection.")

    db.metrics.update_one(
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


def fetch_tweets():
    global last_seen_id
    print("[INFO] Fetching tweets from API...")

    url = "https://twitter241.p.rapidapi.com/search-v2"
    querystring = {"type": "Latest", "query": "IPL", "count": "10"}
    headers = {
        "X-RapidAPI-Key": 'cc17d03003msh9b10bdb1326faddp109cb2jsnfdab0ff25424',
        "X-RapidAPI-Host": "twitter241.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=querystring)
        print("[INFO] API call made successfully.")
        data = response.json()

        entries = data.get("result", {}).get("timeline", {}).get("instructions", [])[0].get("entries", [])
        tweets = []

        print(f"[INFO] Total entries fetched: {len(entries)}")
        for entry in entries:
            content = entry.get("content", {})
            if content.get("__typename") == "TimelineTimelineItem":
                try:
                    item_content = content.get("itemContent", {})
                    tweet_result = item_content.get("tweet_results", {}).get("result", {})
                    legacy_tweet = tweet_result.get("legacy", {})
                    user_legacy = tweet_result.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
                    userid=user_legacy['screen_name']
                    

                    tweet_id = legacy_tweet.get("id_str")
                    full_text = legacy_tweet.get("full_text")
                    url='https://x.com/'+userid+'/status/'+tweet_id

                    username = user_legacy.get("name")
                    screen_name = user_legacy.get("screen_name")

                    tweets.append({"id": tweet_id, "text": full_text,"uri":url})
                    print(f"[INFO] Tweet fetched from @{screen_name}: {full_text}")
                except:
                    continue

        print(f"[INFO] Total processed tweets: {len(tweets)}")
        tweets.reverse()
        for tweet in tweets:
            tweet_id = tweet["id"]
            if last_seen_id and tweet_id <= last_seen_id:
                print(f"[DEBUG] Skipping already processed tweet: {tweet_id}")
                continue
            last_seen_id = max(last_seen_id or "0", tweet_id)

            analysis = analyze_tweet(tweet["text"])
            store_analysis(tweet_id, analysis,tweet)
            if analysis["urgent"]:
                trigger_alert(analysis)

    except Exception as e:
        print(f"[ERROR] Tweet fetch or processing failed: {e}")

    print("[INFO] Scheduling next fetch in 30 seconds...\n")
    threading.Timer(30, fetch_tweets).start()


def store_analysis_comments(tweet_id, analysis):
    print(f"[INFO] Storing analysis for tweet_id: {tweet_id}")
    if db.feedback_comments.find_one({"post_id": tweet_id}):
        print("[WARNING] Duplicate post found. Skipping insert.")
        return
    analysis["post_id"] = tweet_id
    db.feedback_comments.insert_one(analysis)
    print("[INFO] Tweet analysis stored in feedback collection.")

    db.metrics_comments.update_one(
        {"type": "sentiment"},
        {"$inc": {f"counts.{analysis['sentiment']}": 1}},
        upsert=True
    )
    print("[INFO] Sentiment metrics updated.")



def comments(username):
    comments=fetch_comments(username)
    for item in comments:
        id=item['id']
        for comment in item['comments']:
            analysis = analyze_tweet(comment)
            store_analysis_comments(id, analysis)

def test():
    
    m=db.metrics_comments.find()
    m1=dumps(m)
    #print(m1)
    socketio.emit("update",{"t":99})
    #logger.info(f"[SOCKET] Metrics emitted: {99}")
    time.sleep(2)
    threading.Timer(3, test).start()

def start_loop():
    socketio.sleep(3)
    test()

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
    socketio.run(app, port=5000, debug=True)