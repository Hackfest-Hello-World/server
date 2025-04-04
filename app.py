# app.py - Main backend application file

import os
import re
import json
import time
from datetime import datetime
from collections import defaultdict, Counter
import threading

# Flask for web API
from flask import Flask, request, jsonify
from flask_socketio import SocketIO

# NLP libraries for sentiment analysis
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from textblob import TextBlob

# Initialize Flask app
app = Flask(__name__)
socketio = SocketIO(app)

# Download NLTK resources if not already downloaded
try:
    nltk.data.find('vader_lexicon')
except LookupError:
    nltk.download('vader_lexicon')

# Initialize sentiment analyzer
sentiment_analyzer = SentimentIntensityAnalyzer()

# In-memory storage for the POC
feedback_data = []
alerts = []
event_config = {
    "name": "My Event",
    "hashtags": ["myevent2025", "techconference"],
    "keywords": ["conference", "tech event", "speakers"]
}

# Source data collectors (mock implementations for POC)
class DataCollector:
    @staticmethod
    def clean_text(text):
        """Clean text by removing URLs, special chars, etc."""
        text = re.sub(r'http\S+|www\S+|https\S+', '', text, flags=re.MULTILINE)
        text = re.sub(r'@\w+', '', text)
        text = re.sub(r'#\w+', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    @staticmethod
    def analyze_sentiment(text):
        """Analyze sentiment using VADER"""
        clean_text = DataCollector.clean_text(text)
        if not clean_text:
            return {"compound": 0, "pos": 0, "neu": 1, "neg": 0, "sentiment": "neutral"}
        
        scores = sentiment_analyzer.polarity_scores(clean_text)
        
        # Determine sentiment label
        if scores['compound'] >= 0.15:
            sentiment = "positive"
        elif scores['compound'] <= -0.15:
            sentiment = "negative"
        else:
            sentiment = "neutral"
            
        scores["sentiment"] = sentiment
        return scores

# Social media collector (mock implementation)
def collect_social_media(hashtag, platform="twitter", count=10):
    """Mock function to collect social media data based on hashtags"""
    # For POC, generate mock data
    mock_data = []
    
    # Common issues during events
    issues = [
        "Can't hear the speaker in the back of the room",
        "The registration line is way too long. Been waiting for 30 mins",
        "WiFi is not working in the conference hall",
        "Food at the event is disappointing",
        "Room temperature is too cold",
        "The app keeps crashing when I try to view the schedule"
    ]
    
    # Positive comments
    positive = [
        f"Loving this {platform} event! Great speakers #{hashtag}",
        f"Amazing insights from the keynote speaker #{hashtag}",
        f"The venue looks amazing #{hashtag}",
        f"Excellent keynote address! Very inspiring. #{hashtag}",
        f"Networking opportunities are fantastic at #{hashtag}"
    ]
    
    # Combine positive and negative for realistic distribution
    all_comments = issues + positive
    
    # Generate mock social media posts
    for i in range(count):
        timestamp = datetime.now().isoformat()
        message = all_comments[i % len(all_comments)]
        
        sentiment = DataCollector.analyze_sentiment(message)
        
        mock_data.append({
            "platform": platform,
            "message": message,
            "user": f"user{i+1}",
            "timestamp": timestamp,
            "sentiment": sentiment
        })
        
        # Add to global feedback data
        feedback_data.append({
            "source": platform,
            "content": message,
            "user": f"user{i+1}",
            "timestamp": timestamp,
            "sentiment": sentiment
        })
        
        # Create alert for negative sentiment
        if sentiment["sentiment"] == "negative" and sentiment["compound"] < -0.25:
            alert = {
                "level": "warning",
                "message": f"Negative {platform} feedback detected",
                "content": message,
                "sentiment_score": sentiment["compound"],
                "timestamp": datetime.now().isoformat()
            }
            alerts.append(alert)
            socketio.emit('new_alert', alert)
    
    # Emit data update event
    socketio.emit('new_data', {"count": len(mock_data)})
    
    return mock_data

# Process text file uploads (for chat logs, etc.)
def process_file_upload(file_path):
    """Process an uploaded text file (chat logs, feedback, etc.)"""
    data = []
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Try to parse format like "Username: Message"
                parts = line.split(':', 1)
                if len(parts) == 2:
                    user = parts[0].strip()
                    message = parts[1].strip()
                else:
                    # Just treat whole line as message
                    user = "Anonymous"
                    message = line
                
                sentiment = DataCollector.analyze_sentiment(message)
                timestamp = datetime.now().isoformat()
                
                data.append({
                    "source": "chat_log",
                    "content": message,
                    "user": user,
                    "timestamp": timestamp,
                    "sentiment": sentiment
                })
                
                # Add to global feedback data
                feedback_data.append({
                    "source": "chat_log",
                    "content": message,
                    "user": user,
                    "timestamp": timestamp,
                    "sentiment": sentiment
                })
                
                # Create alert for negative sentiment
                if sentiment["sentiment"] == "negative" and sentiment["compound"] < -0.25:
                    alert = {
                        "level": "warning",
                        "message": f"Negative feedback detected in chat log",
                        "content": message,
                        "sentiment_score": sentiment["compound"],
                        "timestamp": datetime.now().isoformat()
                    }
                    alerts.append(alert)
                    socketio.emit('new_alert', alert)
        
        # Emit data update event
        socketio.emit('new_data', {"count": len(data)})
        
        return data
    except Exception as e:
        print(f"Error processing file: {e}")
        return []

# API endpoints
@app.route('/api/collect/social', methods=['POST'])
def api_collect_social():
    """API endpoint to collect social media data"""
    platform = request.form.get('platform', 'twitter')
    hashtag = request.form.get('hashtag', event_config['hashtags'][0])
    count = int(request.form.get('count', 10))
    
    data = collect_social_media(hashtag, platform, count)
    
    return jsonify({
        "status": "success",
        "count": len(data),
        "data": data
    })

@app.route('/api/upload/chat', methods=['POST'])
def api_upload_chat():
    """API endpoint to upload and process a chat log"""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"})
    
    # Save file temporarily
    file_path = os.path.join('/tmp', file.filename)
    file.save(file_path)
    
    # Process file
    data = process_file_upload(file_path)
    
    # Clean up
    os.remove(file_path)
    
    return jsonify({
        "status": "success",
        "count": len(data),
        "data": data
    })

@app.route('/api/feedback')
def api_feedback():
    """API endpoint to get feedback data"""
    source = request.args.get('source')
    sentiment = request.args.get('sentiment')
    limit = int(request.args.get('limit', 100))
    
    filtered_data = feedback_data
    
    if source:
        filtered_data = [item for item in filtered_data if item['source'] == source]
    
    if sentiment:
        filtered_data = [item for item in filtered_data if item['sentiment']['sentiment'] == sentiment]
    
    # Sort by timestamp (newest first)
    sorted_data = sorted(filtered_data, key=lambda x: x['timestamp'], reverse=True)
    
    return jsonify({
        "status": "success",
        "count": len(sorted_data),
        "data": sorted_data[:limit]
    })

@app.route('/api/alerts')
def api_alerts():
    """API endpoint to get alerts"""
    return jsonify({
        "status": "success",
        "count": len(alerts),
        "data": alerts
    })

@app.route('/api/stats')
def api_stats():
    """API endpoint to get sentiment statistics"""
    if not feedback_data:
        return jsonify({
            "status": "success",
            "data": {
                "total": 0,
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "positive_percent": 0,
                "neutral_percent": 0,
                "negative_percent": 0
            }
        })
    
    total = len(feedback_data)
    positive = sum(1 for item in feedback_data if item['sentiment']['sentiment'] == 'positive')
    neutral = sum(1 for item in feedback_data if item['sentiment']['sentiment'] == 'neutral')
    negative = sum(1 for item in feedback_data if item['sentiment']['sentiment'] == 'negative')
    
    return jsonify({
        "status": "success",
        "data": {
            "total": total,
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "positive_percent": round(positive / total * 100, 2),
            "neutral_percent": round(neutral / total * 100, 2),
            "negative_percent": round(negative / total * 100, 2)
        }
    })

@app.route('/api/simulate', methods=['POST'])
def api_simulate():
    """API endpoint to simulate incoming data for testing"""
    count = int(request.form.get('count', 5))
    platform = request.form.get('platform', 'simulation')
    
    data = collect_social_media(event_config['hashtags'][0], platform, count)
    
    return jsonify({
        "status": "success",
        "count": len(data),
        "data": data
    })

@app.route('/')
def index():
    return jsonify({
        "status": "success",
        "message": "Event Sentiment Analysis API is running",
        "endpoints": {
            "feedback": "/api/feedback",
            "stats": "/api/stats",
            "simulate": "/api/simulate (POST)",
            "collect_social": "/api/collect/social (POST)",
            "upload_chat": "/api/upload/chat (POST)"
        }
    })

if __name__ == '__main__':
    socketio.run(app, debug=True)
