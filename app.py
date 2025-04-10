from flask import Flask, jsonify, request
from flask_socketio import SocketIO
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import logging
from flask_cors import CORS
from bson.json_util import dumps
import json
from bson import ObjectId, json_util
from surveillance import start1
import threading
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "sentinel-dashboard-secret")
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")
# Enable CORS for all origins
CORS(app, resources={r"/*": {"origins": "*"}})
# Connect to MongoDB
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.event_monitoring

# Setup message collection from chat.py
messages_collection = db['messages']
# Ensure index for efficient querying
messages_collection.create_index([('thread_id', 1), ('timestamp', 1)])

def calculate_percentage(value, total):
    """Calculate percentage with safety for division by zero"""
    return round((value / total) * 100, 2) if total > 0 else 0

@app.route('/')
def home_dashboard():
    """Aggregate data from all platforms for a unified dashboard"""
    # Get metrics from all platforms
    platforms = {
        "twitter": db.metrics.find_one({"type": "sentiment"}) or {"counts": {}},
        "instagram": db.metrics_insta.find_one({"type": "sentiment"}) or {"counts": {}},
        "youtube": db.metrics_youtube.find_one({"type": "sentiment"}) or {"counts": {}}
    }
    
    # Calculate total counts across platforms
    total_positive = sum(p["counts"].get("LABEL_1", 0) for p in platforms.values())
    total_negative = sum(p["counts"].get("LABEL_0", 0) for p in platforms.values())
    total_neutral = sum(p["counts"].get("LABEL_2", 0) for p in platforms.values())
    total_items = total_positive + total_negative + total_neutral
    
    trend_posts_insta = list(db.feedback_insta.find({}, {"_id": 0, "text": 1, "sentiment": 1, "timestamp": 1}).sort("views", -1).limit(2))
    trend_posts_twitter = list(db.feedback.find({}, {"_id": 0, "text": 1, "sentiment": 1, "timestamp": 1}).sort("trend", -1).limit(2))
    return jsonify({
        "overall": {
            "positive": {
                "count": total_positive,
                "percentage": calculate_percentage(total_positive, total_items)
            },
            "negative": {
                "count": total_negative,
                "percentage": calculate_percentage(total_negative, total_items)
            },
            "neutral": {
                "count": total_neutral,
                "percentage": calculate_percentage(total_neutral, total_items)
            },
            "total": total_items
        },
        "platforms": {
            "twitter": {
                "positive": calculate_percentage(platforms["twitter"]["counts"].get("LABEL_1", 0), sum(platforms["twitter"]["counts"].values())),
                "negative": calculate_percentage(platforms["twitter"]["counts"].get("LABEL_0", 0), sum(platforms["twitter"]["counts"].values())),
                "neutral": calculate_percentage(platforms["twitter"]["counts"].get("LABEL_2", 0), sum(platforms["twitter"]["counts"].values()))
            },
            "instagram": {
                "positive": calculate_percentage(platforms["instagram"]["counts"].get("LABEL_1", 0), sum(platforms["instagram"]["counts"].values())),
                "negative": calculate_percentage(platforms["instagram"]["counts"].get("LABEL_0", 0), sum(platforms["instagram"]["counts"].values())),
                "neutral": calculate_percentage(platforms["instagram"]["counts"].get("LABEL_2", 0), sum(platforms["instagram"]["counts"].values()))
            },
            "youtube": {
                "positive": calculate_percentage(platforms["youtube"]["counts"].get("LABEL_1", 0), sum(platforms["youtube"]["counts"].values())),
                "negative": calculate_percentage(platforms["youtube"]["counts"].get("LABEL_0", 0), sum(platforms["youtube"]["counts"].values())),
                "neutral": calculate_percentage(platforms["youtube"]["counts"].get("LABEL_2", 0), sum(platforms["youtube"]["counts"].values()))
            }
        },
        "trend_insta": trend_posts_insta,
        "trend_twitter": trend_posts_twitter,
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
    
    return jsonify({
        "platform": "Twitter",
        "stats": {
            "tweets": {
                "positive": {"count": counts.get("LABEL_1", 0), "percentage": calculate_percentage(counts.get("LABEL_1", 0), posts_total)},
                "negative": {"count": counts.get("LABEL_0", 0), "percentage": calculate_percentage(counts.get("LABEL_0", 0), posts_total)},
                "neutral": {"count": counts.get("LABEL_2", 0), "percentage": calculate_percentage(counts.get("LABEL_2", 0), posts_total)},
                "total": posts_total
            },
            "comments": {
                "positive": {"count": comments_counts.get("LABEL_1", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_1", 0), comments_total)},
                "negative": {"count": comments_counts.get("LABEL_0", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_0", 0), comments_total)},
                "neutral": {"count": comments_counts.get("LABEL_2", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_2", 0), comments_total)},
                "total": comments_total
            }
        },
        "recent_tweets": recent_tweets,
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
    recent_posts = dumps(db.feedback_insta.find({},{"_id": 0}).sort("timestamp", -1).limit(5))
    recent_posts=json.loads(recent_posts)
    
    return jsonify({
        "platform": "Instagram",
        "stats": {
            "posts": {
                "positive": {"count": counts.get("LABEL_1", 0), "percentage": calculate_percentage(counts.get("LABEL_1", 0), posts_total)},
                "negative": {"count": counts.get("LABEL_0", 0), "percentage": calculate_percentage(counts.get("LABEL_0", 0), posts_total)},
                "neutral": {"count": counts.get("LABEL_2", 0), "percentage": calculate_percentage(counts.get("LABEL_2", 0), posts_total)},
                "total": posts_total
            },
            "comments": {
                "positive": {"count": comments_counts.get("LABEL_1", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_1", 0), comments_total)},
                "negative": {"count": comments_counts.get("LABEL_0", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_0", 0), comments_total)},
                "neutral": {"count": comments_counts.get("LABEL_2", 0), "percentage": calculate_percentage(comments_counts.get("LABEL_2", 0), comments_total)},
                "total": comments_total
            }
        },
        "recent_posts": recent_posts,
    })

@app.route("/forms/getAll")
def get_live_forms():
    # Fetch all forms
    live_forms = list(db.forms.find({}, {"_id": 0}).sort("timestamp", -1))
    
    # Fetch all form responses
    form_responses = list(db.form_responses.find({}, {"_id": 0}))
    
    # Create a dictionary to map formId to responses
    responses_dict = {}
    for response in form_responses:
        form_id = response.get("formId")
        if form_id:
            if form_id not in responses_dict:
                responses_dict[form_id] = []
            responses_dict[form_id].append(response)
    
    # Add responses to the corresponding forms
    for form in live_forms:
        form_id = form.get("formId")
        form["responses"] = responses_dict.get(form_id, [])
        positive, negative, neutral = 0, 0, 0
        last_submitted_time = None

        for response in form["responses"]:
            sentiment = response.get("sentimentAnalysis", {}).get("sentiment", "")
            if sentiment == "positive":
                positive += 1
            elif sentiment == "negative":
                negative += 1
            elif sentiment == "neutral":
                neutral += 1
            
            for key, value in response["answers"].items():
                if 'email' in key.lower() or "gmail" in key.lower():
                    response["email"] = value
                    break
            
            # Track the most recent submission time
            response_time = response.get("lastSubmittedTime")
            if response_time and (last_submitted_time is None or response_time > last_submitted_time):
                last_submitted_time = response_time
        
        # Set the lastUpdated field
        form["lastUpdated"] = last_submitted_time
    
        # Determine overall sentiment
        if positive > negative:
            form["sentiment"] = "Positive"
        elif negative > positive:
            form["sentiment"] = "Negative"
        else:
            form["sentiment"] = "Neutral"
    # Sort forms by lastUpdated in decreasing order (newest first)
    live_forms = sorted(live_forms, key=lambda form: form.get("lastUpdated") or "", reverse=True)
    return jsonify(live_forms)

@app.route("/youtube/videos")
def get_youtube_channel():
    youtube_videos = list(db.youtube_videos.find({}, {"_id": 0}).sort("timestamp", -1))
    # sort youtube_videos acc to   "publishedAt": "2025-04-05T00:34:23Z", in descending order
    youtube_videos.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    return youtube_videos

@app.route('/notifications', methods=['GET'])
def get_notifications():
    notifications = list(db.alerts.find({'checked':'False'}).sort("timestamp", -1).limit(1))  # Latest first
    for n in notifications:
        n['_id'] = str(n['_id'])  # Convert ObjectId to string
        db.alerts.update_one(
            {'_id': ObjectId(n['_id'])},
            {'$set': {'checked': 'True'}}
        )
    
    return jsonify(notifications)

@app.route('/start-surveillance', methods=['GET'])
def func():
    thread = threading.Thread(target=start1)
    thread.start()
    m=db.overcrowding.find({}).limit(5)

    m=json.loads(dumps(m))
    print(m)
    return m

# Chat endpoints from chat.py
@app.route('/api/messages', methods=['GET'])
def get_messages():
    try:
        # Fetch root-level messages
        pipeline = [
            {"$match": {"thread_id": {"$exists": False}}},
            {"$sort": {"timestamp": -1}},
            {"$limit": 50},
            {
                "$lookup": {
                    "from": "messages",
                    "localField": "_id",
                    "foreignField": "thread_id",
                    "as": "replies",
                    "pipeline": [
                        {"$sort": {"timestamp": 1}},
                        {"$limit": 10}
                    ]
                }
            },
            {
                "$addFields": {
                    "reply_count": {"$size": "$replies"}
                }
            }
        ]
        messages = list(messages_collection.aggregate(pipeline))
        return jsonify(json.loads(json_util.dumps(messages)))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/messages', methods=['POST'])
def add_message():
    try:
        data = request.get_json()

        if not data or not data.get('content'):
            return jsonify({'error': 'Missing message content'}), 400

        message = {
            'content': data['content'],
            'author': data.get('author', 'Anonymous'),
            'timestamp': datetime.utcnow()
        }

        # Handle reply if thread_id is provided
        thread_id = data.get('thread_id').get("$oid") if data.get('thread_id') else None
        
        if thread_id:
            try:
                message['thread_id'] = ObjectId(thread_id)
            except Exception:
                return jsonify({'error': 'Invalid thread_id format'}), 400

        result = messages_collection.insert_one(message)
        message['_id'] = str(result.inserted_id)
        message['timestamp'] = message['timestamp'].isoformat() + 'Z'
        message['thread_id'] = str(message.get('thread_id')) if thread_id else None
        return jsonify(message), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("[INFO] Starting server on port 5000...")
    socketio.run(app, port=5000, debug=True)
