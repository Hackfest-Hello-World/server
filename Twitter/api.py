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
import math

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

CONFIG = {
    "alert_thresholds": {
        "urgent_keywords": ["crowd", "emergency", "accident"],
    }
}

# Twitter API headers
TWITTER_HEADERS = {
    "x-rapidapi-host": "twitter241.p.rapidapi.com",
    "x-rapidapi-key": "cc17d03003msh9b10bdb1326faddp109cb2jsnfdab0ff25424"
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

# Helper function for percentage calculation
def calculate_percentage(value, total):
    return round((value / total) * 100, 2) if total > 0 else 0

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

def store_analysis(tweet_id, analysis, tweet):
    print(f"[INFO] Storing analysis for tweet_id: {tweet_id}")
    if db.feedback.find_one({"tweet_id": tweet_id}):
        print("[WARNING] Duplicate tweet found. Skipping insert.")
        return
    analysis["tweet_id"] = tweet_id
    analysis["uri"] = tweet['uri']
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

    try:
        response = requests.get(url, headers=TWITTER_HEADERS, params=querystring)
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
                    userid = user_legacy['screen_name']

                    tweet_id = legacy_tweet.get("id_str")
                    full_text = legacy_tweet.get("full_text")
                    url = 'https://x.com/' + userid + '/status/' + tweet_id

                    username = user_legacy.get("name")
                    screen_name = user_legacy.get("screen_name")

                    tweets.append({"id": tweet_id, "text": full_text, "uri": url})
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
            store_analysis(tweet_id, analysis, tweet)
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

# Functions from app_comments.py
def fetch_user_details(username):
    url = f"https://twitter241.p.rapidapi.com/user?username={username}"
    response = requests.get(url, headers=TWITTER_HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user details: {response.status_code} - {response.text}")

    data = response.json()
    data1 = data['result']["data"]["user"]['result']['rest_id']
    return data1

def fetch_user_posts(username, count=1):
    url = f"https://twitter241.p.rapidapi.com/user-tweets?user={username}&count={count}"
    response = requests.get(url, headers=TWITTER_HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user posts: {response.status_code} - {response.text}")

    data = response.json()
    item1 = data['result']['timeline']['instructions'][1]['entry']['content']['itemContent']['tweet_results']['result']['legacy']['id_str']
    items = data['result']['timeline']['instructions'][2]['entries']

    posts = [item1]

    for item in items:
        try:
            post_id = item['content']['itemContent']['tweet_results']['result']['legacy']['id_str']
            posts.append(post_id)
        except:
            continue

    return posts

def fetch_post_comments(post_pk):
    print(post_pk)
    url = f"https://twitter241.p.rapidapi.com/comments?pid={post_pk}&count=5&rankingMode=Relevance"
    try:
        response = requests.get(url, headers=TWITTER_HEADERS)
        response.raise_for_status()
        data = response.json()
        try:
            items = data['result']['instructions'][0]['entries']
            comments = []
            for x in items:
                try:
                    comment = x['content']['itemContent']['tweet_results']['result']['legacy']['full_text']
                    comments.append(comment)
                except:
                    continue
            return {'id': post_pk, 'comments': comments}
        except:
            return {'id': post_pk, 'comments': []}

    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {e}")
    except Exception as e:
        raise Exception(f"Error processing comment data: {e}")

def fetch_comments(username):
    id = fetch_user_details(username)
    posts = fetch_user_posts(id)
    comments = []
    for post in posts:
        comments.append(fetch_post_comments(post))
        time.sleep(0.5)
    return comments

def comments(username):
    comments = fetch_comments(username)
    for item in comments:
        id = item['id']
        for comment in item['comments']:
            analysis = analyze_tweet(comment)
            store_analysis_comments(id, analysis)

def test():
    m = db.metrics_comments.find()
    m1 = dumps(m)
    socketio.emit("update", {"t": 99})
    time.sleep(2)
    threading.Timer(3, test).start()

def start_loop():
    socketio.sleep(3)
    test()

# Routes
@app.route("/dashboard")
def dashboard():
    print("[INFO] Dashboard API hit.")
    metrics = db.metrics.find_one({"type": "sentiment"}) or {}
    counts = metrics.get("counts", {})
    print(f"[INFO] Current sentiment counts: {counts}")
    # neutral_count = math.ceil(counts.get("LABEL_1", 0)*0.15 + counts.get("LABEL_0", 0)*0.15)
    return jsonify({
        "positive": counts.get("LABEL_1", 0),
        "negative": counts.get("LABEL_0", 0),
        "neutral": counts.get("NEUTRAL", 0),
    })

@app.route("/twitter-analysis")
def twitter_analysis():
    print("[INFO] Twitter Analysis API hit.")
    # Get Twitter post metrics
    metrics = db.metrics.find_one({"type": "sentiment"}) or {"counts": {}}
    counts = metrics.get("counts", {})
    
    # Get Twitter comments metrics
    comments_metrics = db.metrics_comments.find_one({"type": "sentiment"}) or {"counts": {}}
    comments_counts = comments_metrics.get("counts", {})
    
    # Calculate totals
    posts_total = sum(counts.values())
    comments_total = sum(comments_counts.values())
    
    # Get recent tweets and comments
    recent_tweets = list(db.feedback.find({}, {"_id": 0, "text": 1, "sentiment": 1, "timestamp": 1, "uri": 1}).sort("timestamp", -1).limit(5))
    recent_comments = list(db.feedback_comments.find({}, {"_id": 0, "text": 1, "sentiment": 1, "timestamp": 1}).sort("timestamp", -1).limit(5))
    
    return jsonify({
        "platform": "Twitter",
        "stats": {
            "tweets": {
                "positive": {"count": counts.get("LABEL_1", 0), "percentage": calculate_percentage(counts.get("LABEL_1", 0), posts_total)},
                "negative": {"count": counts.get("LABEL_0", 0), "percentage": calculate_percentage(counts.get("LABEL_0", 0), posts_total)},
                "neutral": {"count": counts.get("NEUTRAL", 0), "percentage": calculate_percentage(counts.get("NEUTRAL", 0), posts_total)},
                "total": posts_total
            },
            "comments": {
                "positive": {"count": comments_counts.get("LABEL_1", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_1", 0), comments_total)},
                "negative": {"count": comments_counts.get("LABEL_0", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_0", 0), comments_total)},
                "neutral": {"count": comments_counts.get("NEUTRAL", 0), "percentage": calculate_percentage(comments_counts.get("NEUTRAL", 0), comments_total)},
                "total": comments_total
            }
        },
        "recent_tweets": recent_tweets,
        "recent_comments": recent_comments
    })

if __name__ == "__main__":
    print("[INFO] Starting tweet fetcher and Flask server...")
    
    #fetch_tweets()
    #test()
    #socketio.start_background_task(start_loop)
    socketio.run(app, port=5000, debug=True)