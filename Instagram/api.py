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

# Instagram API headers
INSTA_HEADERS = {
    "x-rapidapi-host": "instagram230.p.rapidapi.com",
    "x-rapidapi-key": "40aa78f613msh0d3be2aa1ef2521p1a78c7jsne3c3ded97d8a"
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

def store_analysis(post_id, analysis, post):
    print(f"[INFO] Storing analysis for post_id: {post_id}")
    if db.feedback_insta.find_one({"post_id": post_id}):
        print("[WARNING] Duplicate post found. Skipping insert.")
        return
    analysis["post_id"] = post_id
    db.feedback_insta.insert_one(analysis)
    print("[INFO] Post analysis stored in feedback collection.")

    db.metrics_insta.update_one(
        {"type": "sentiment"},
        {"$inc": {f"counts.{analysis['sentiment']}": 1}},
        upsert=True
    )
    print("[INFO] Sentiment metrics updated.")

def trigger_alert(analysis):
    print(f"[ALERT] Triggering urgent alert for content: {analysis['text']}")
    socketio.emit("alert", {
        "type": "urgent",
        "message": "Immediate attention required!",
        "text": analysis["text"],
        "timestamp": analysis["timestamp"].isoformat()
    })
    print("[ALERT] Alert emitted via SocketIO.")

def store_analysis_comments(post_id, analysis):
    print(f"[INFO] Storing analysis for comment on post_id: {post_id}")
    if db.feedback_comments_insta.find_one({"post_id": post_id, "text": analysis["text"]}):
        print("[WARNING] Duplicate comment found. Skipping insert.")
        return
    analysis["post_id"] = post_id
    db.feedback_comments_insta.insert_one(analysis)
    print("[INFO] Comment analysis stored in feedback collection.")

    db.metrics_comments_insta.update_one(
        {"type": "sentiment"},
        {"$inc": {f"counts.{analysis['sentiment']}": 1}},
        upsert=True
    )
    print("[INFO] Comment sentiment metrics updated.")

# Functions from app2.py
def fetch_user_details(username):
    url = f"https://instagram230.p.rapidapi.com/user/details?username={username}"
    response = requests.get(url, headers=INSTA_HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user details: {response.status_code} - {response.text}")

    data = response.json()
    data = data["data"]["user"]

    # Extract the useful parts
    user_data = {
        "username": data.get("username"),
        "full_name": data.get("full_name"),
        "id": data.get("id"),
        "bio": data.get("biography"),
        "followers": data.get("edge_followed_by", {}).get("count"),
        "following": data.get("edge_follow", {}).get("count"),
        "profile_pic_url": data.get("profile_pic_url_hd") or data.get("profile_pic_url"),
        "is_verified": data.get("is_verified"),
        "is_private": data.get("is_private"),
    }

    return user_data

def fetch_user_posts(username):
    url = f"https://instagram230.p.rapidapi.com/user/posts?username={username}"
    response = requests.get(url, headers=INSTA_HEADERS)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch user posts: {response.status_code} - {response.text}")

    data = response.json()
    items = data.get("items")

    posts = []

    for item in items:
        post_id = item.get("pk")

        caption = item.get("caption")
        caption_text = caption.get("text") if caption else ""

        # Tags
        tagged_users = []
        usertags = item.get("usertags", {}).get("in", [])
        for tag in usertags:
            user_info = tag.get("user", {})
            tagged_users.append(user_info.get("username"))

        post_info = {
            "post_id": post_id,
            "caption": caption_text,
            "tagged_users": tagged_users,
            "timestamp": item.get("taken_at")
        }

        posts.append(post_info)

    return posts

def fetch_post_comments(post_pk):
    url = f"https://instagram230.p.rapidapi.com/post/comments?pk={post_pk}"
    try:
        response = requests.get(url, headers=INSTA_HEADERS)
        response.raise_for_status()
        data = response.json()

        # Create a structured result object
        result = {
            "post_id": post_pk,
            "caption": {
                "text": None,
                "username": None,
                "created_at": None
            },
            "comments": []
        }

        # Fill caption data if available
        caption = data.get("caption")
        if caption:
            result["caption"] = {
                "text": caption.get("text"),
                "username": caption.get("user", {}).get("username"),
                "created_at": caption.get("created_at_utc")
            }

        # Fill comments data
        for c in data.get("comments", []):
            result["comments"].append({
                "text": c.get("text"),
                "username": c.get("user", {}).get("username"),
                "likes": c.get("comment_like_count", 0),
                "created_at": c.get("created_at_utc")
            })

        return result

    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {e}")
    except Exception as e:
        raise Exception(f"Error processing comment data: {e}")

def build_user_schema(username):
    user_info = fetch_user_details(username)
    posts = fetch_user_posts(username)
    post_list = []
    for post in posts:
        caption = post.get("caption")
        caption_text = caption.get("text") if isinstance(caption, dict) else caption

        post_data = {
            "post_id": post.get("pk"),
            "caption": caption_text,
            "media_type": post.get("media_type"),
            "taken_at": post.get("taken_at"),
            "like_count": post.get("like_count"),
            "comment_count": post.get("comment_count"),
            "image_versions": post.get("image_versions2", {}).get("candidates") if post.get("image_versions2") else None,
            "video_versions": post.get("video_versions") if post.get("video_versions") else None,
            "comments": post.get("comments", [])
        }
        post_list.append(post_data)

    return {
        "username": username,
        "profile": user_info,
        "posts": post_list
    }

def fetch_captions_comments():
    posts = fetch_user_posts("virat.kohli")
    for items in posts:
        post_id = items["post_id"]
        # Analyze the post caption
        analysis = analyze_tweet(items["caption"])
        store_analysis(post_id, analysis, items)
        if analysis["urgent"]:
            trigger_alert(analysis)
            
        # Get and analyze comments
        try:
            comments_data = fetch_post_comments(post_id)
            comments = comments_data['comments']
            for comment in comments:
                analysis1 = analyze_tweet(comment["text"])
                store_analysis_comments(post_id, analysis1)
        except Exception as e:
            print(f"[ERROR] Failed to process comments for post {post_id}: {e}")
    
    print("[INFO] Instagram data collection complete. Scheduling next run in 5 minutes.")
    threading.Timer(300, fetch_captions_comments).start()

# Routes
@app.route("/dashboard")
def dashboard():
    print("[INFO] Dashboard API hit.")
    metrics = db.metrics_insta.find_one({"type": "sentiment"}) or {}
    counts = metrics.get("counts", {})
    print(f"[INFO] Current sentiment counts: {counts}")
    return jsonify({
        "positive": counts.get("POSITIVE", 0),
        "negative": counts.get("NEGATIVE", 0),
        "neutral": counts.get("NEUTRAL", 0)
    })

@app.route("/insta-analysis")
def insta_analysis():
    print("[INFO] Instagram Analysis API hit.")
    # Get Instagram post metrics
    metrics = db.metrics_insta.find_one({"type": "sentiment"}) or {"counts": {}}
    counts = metrics.get("counts", {})
    
    # Get Instagram comments metrics
    comments_metrics = db.metrics_comments_insta.find_one({"type": "sentiment"}) or {"counts": {}}
    comments_counts = comments_metrics.get("counts", {})
    
    # Calculate totals
    posts_total = sum(counts.values())
    comments_total = sum(comments_counts.values())
    
    # Get recent posts and comments
    recent_posts = list(db.feedback_insta.find({}, {"_id": 0, "text": 1, "sentiment": 1, "timestamp": 1}).sort("timestamp", -1).limit(5))
    recent_comments = list(db.feedback_comments_insta.find({}, {"_id": 0, "text": 1, "sentiment": 1, "timestamp": 1}).sort("timestamp", -1).limit(5))
    
    return jsonify({
        "platform": "Instagram",
        "stats": {
            "posts": {
                "positive": {"count": counts.get("POSITIVE", 0), "percentage": calculate_percentage(counts.get("POSITIVE", 0), posts_total)},
                "negative": {"count": counts.get("NEGATIVE", 0), "percentage": calculate_percentage(counts.get("NEGATIVE", 0), posts_total)},
                "neutral": {"count": counts.get("NEUTRAL", 0), "percentage": calculate_percentage(counts.get("NEUTRAL", 0), posts_total)},
                "total": posts_total
            },
            "comments": {
                "positive": {"count": comments_counts.get("POSITIVE", 0), "percentage": calculate_percentage(comments_counts.get("POSITIVE", 0), comments_total)},
                "negative": {"count": comments_counts.get("NEGATIVE", 0), "percentage": calculate_percentage(comments_counts.get("NEGATIVE", 0), comments_total)},
                "neutral": {"count": comments_counts.get("NEUTRAL", 0), "percentage": calculate_percentage(comments_counts.get("NEUTRAL", 0), comments_total)},
                "total": comments_total
            }
        },
        "recent_posts": recent_posts,
        "recent_comments": recent_comments
    })

if __name__ == "__main__":
    print("[INFO] Starting Instagram sentiment analysis server...")
    
    # Start data collection
    fetch_captions_comments()
    
    # Run the Flask server
    socketio.run(app, port=5001, debug=True)
