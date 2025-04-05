from flask import Flask, jsonify
from flask_socketio import SocketIO
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import logging

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

# Connect to MongoDB
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.event_monitoring

def calculate_percentage(value, total):
    """Calculate percentage with safety for division by zero"""
    return round((value / total) * 100, 2) if total > 0 else 0

@app.route('/home')
def home_dashboard():
    """Aggregate data from all platforms for a unified dashboard"""
    # Get metrics from all platforms
    platforms = {
        "twitter": db.metrics.find_one({"type": "sentiment"}) or {"counts": {}},
        "instagram": db.metrics_insta.find_one({"type": "sentiment"}) or {"counts": {}},
        "youtube": db.metrics_youtube.find_one({"type": "sentiment"}) or {"counts": {}}
    }
    
    # Calculate total counts across platforms
    total_positive = sum(p["counts"].get("POSITIVE", 0) for p in platforms.values())
    total_negative = sum(p["counts"].get("NEGATIVE", 0) for p in platforms.values())
    total_neutral = sum(p["counts"].get("NEUTRAL", 0) for p in platforms.values())
    total_items = total_positive + total_negative + total_neutral
    
    # Get recent urgent items
    urgent_items = list(db.feedback.find({"urgent": True}, {"_id": 0}).sort("timestamp", -1).limit(3))
    urgent_items.extend(list(db.feedback_insta.find({"urgent": True}, {"_id": 0}).sort("timestamp", -1).limit(3)))
    urgent_items.extend(list(db.feedback_youtube.find({"urgent": True}, {"_id": 0}).sort("timestamp", -1).limit(3)))
    
    # Sort by timestamp
    urgent_items.sort(key=lambda x: x["timestamp"], reverse=True)
    
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
                "positive": calculate_percentage(platforms["twitter"]["counts"].get("POSITIVE", 0), sum(platforms["twitter"]["counts"].values())),
                "negative": calculate_percentage(platforms["twitter"]["counts"].get("NEGATIVE", 0), sum(platforms["twitter"]["counts"].values())),
                "neutral": calculate_percentage(platforms["twitter"]["counts"].get("NEUTRAL", 0), sum(platforms["twitter"]["counts"].values()))
            },
            "instagram": {
                "positive": calculate_percentage(platforms["instagram"]["counts"].get("POSITIVE", 0), sum(platforms["instagram"]["counts"].values())),
                "negative": calculate_percentage(platforms["instagram"]["counts"].get("NEGATIVE", 0), sum(platforms["instagram"]["counts"].values())),
                "neutral": calculate_percentage(platforms["instagram"]["counts"].get("NEUTRAL", 0), sum(platforms["instagram"]["counts"].values()))
            },
            "youtube": {
                "positive": calculate_percentage(platforms["youtube"]["counts"].get("POSITIVE", 0), sum(platforms["youtube"]["counts"].values())),
                "negative": calculate_percentage(platforms["youtube"]["counts"].get("NEGATIVE", 0), sum(platforms["youtube"]["counts"].values())),
                "neutral": calculate_percentage(platforms["youtube"]["counts"].get("NEUTRAL", 0), sum(platforms["youtube"]["counts"].values()))
            }
        },
        "urgent_items": urgent_items[:5]  # Most recent 5 urgent items
    })

@app.route('/')
def index():
    return "Sentiment Analysis Dashboard API - Access /home for aggregated data"

# Note: We're using different servers for each platform
# This main app only provides the aggregated view

if __name__ == '__main__':
    print("[INFO] Starting main dashboard server...")
    socketio.run(app, port=5003, debug=True)
