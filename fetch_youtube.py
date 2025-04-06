from pymongo import MongoClient
from google.oauth2.credentials import Credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import os
from dotenv import load_dotenv
from  groq_service.groq_promt import groq_llm_promt
import msgpack
import json
import sys
import time
import threading
import datetime

# Load environment variables
load_dotenv()
print(f"[{datetime.datetime.now()}] Starting YouTube data fetch script")

mongo_uri = os.getenv("MONGO_URI")
print(f"[{datetime.datetime.now()}] Connecting to MongoDB")
mongo_client = MongoClient(mongo_uri)
db = mongo_client.event_monitoring
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
video_collection = db.youtube_videos

if not mongo_uri:
    print(f"[{datetime.datetime.now()}] Error: MONGO_URI environment variable not set")
    sys.exit(1)
else:
    print(f"[{datetime.datetime.now()}] Successfully connected to MongoDB")
        
        
def get_videos():
    print(f"[{datetime.datetime.now()}] Starting video fetch process")
    session_collection = db.google_auth_session
    print(f"[{datetime.datetime.now()}] Retrieving latest Google auth session")
    latest_session = session_collection.find_one(
        {"id": {"$regex": "^session:"}},
        sort=[("_id", -1)]
    )
    
    if not latest_session or 'val' not in latest_session:
        print(f"[{datetime.datetime.now()}] Error: No valid session found in MongoDB")
        return None
    
    # Extract credentials from session
    print(f"[{datetime.datetime.now()}] Extracting credentials from session data")
    session_data = latest_session['val']
    deserialized_data = msgpack.unpackb(session_data, raw=False)
    if 'credentials' not in deserialized_data:
        print(f"[{datetime.datetime.now()}] Error: No credentials found in session data")
        return None

    credentials_data = deserialized_data['credentials']
    credentials = Credentials(
        token=credentials_data['token'],
        refresh_token=credentials_data['refresh_token'],
        token_uri=credentials_data['token_uri'],
        client_id=credentials_data['client_id'],
        client_secret=credentials_data['client_secret'],
        scopes=credentials_data['scopes']
    )
    
    # Build the YouTube API client
    print(f"[{datetime.datetime.now()}] Building YouTube API client")
    youtube = googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)
    
    # First, get the uploads playlist ID for the authenticated user
    print(f"[{datetime.datetime.now()}] Fetching user's channel information")
    channels_response = youtube.channels().list(
        part="contentDetails",
        mine=True
    ).execute()
    
    # Get the uploads playlist ID
    uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    print(f"[{datetime.datetime.now()}] Found uploads playlist ID: {uploads_playlist_id}")
    
    # Get videos from the uploads playlist
    print(f"[{datetime.datetime.now()}] Retrieving videos from uploads playlist")
    videos = []
    next_page_token = None
    page_count = 0
    
    while True:
        page_count += 1
        print(f"[{datetime.datetime.now()}] Fetching page {page_count} of videos")
        playlist_items_response = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=next_page_token
        ).execute()
        
        print(f"[{datetime.datetime.now()}] Retrieved {len(playlist_items_response['items'])} videos on page {page_count}")
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
    
    print(f"[{datetime.datetime.now()}] Total videos found: {len(videos)}")
    transformed_videos = []
    for video in videos:
        id = video["id"]
        title = video["title"]
        description= video["description"]
        publishedAt = video["publishedAt"]
        url= f"https://www.youtube.com/watch?v={video['id']}"
        transformed_videos.append({
            "id": id,"title": title,"description": description,"publishedAt": publishedAt, "url":url, "comments": []
        })
        
    try:
        for i, youtube_video in enumerate(transformed_videos):
            video_id = youtube_video["id"]
            print(f"[{datetime.datetime.now()}] Processing video {i+1}/{len(transformed_videos)}: {video_id} - {youtube_video['title']}")
             # Get comments for the specified video
            comments = []
            next_page_token = None
            comment_page = 0
            
            print(f"[{datetime.datetime.now()}] Fetching comments for video: {video_id}")
            while True:
                comment_page += 1
                print(f"[{datetime.datetime.now()}] Fetching page {comment_page} of comments for video {video_id}")
                try:
                    comments_response = youtube.commentThreads().list(
                        part="snippet",
                        videoId=video_id,
                        maxResults=100,
                        pageToken=next_page_token,
                        textFormat="plainText"
                    ).execute()
                    
                    comment_count = len(comments_response.get('items', []))
                    print(f"[{datetime.datetime.now()}] Retrieved {comment_count} comments on page {comment_page}")
                    
                    for item in comments_response.get('items', []):
                        comment = item['snippet']['topLevelComment']['snippet']
                        youtube_video["comments"].append({
                            'id': item['id'],
                            'author': comment['authorDisplayName'],
                            'text': comment['textDisplay'],
                            'likeCount': comment['likeCount'],
                            'publishedAt': comment['publishedAt']
                        })
                    
                    next_page_token = comments_response.get('nextPageToken')
                    if not next_page_token:
                        break
                except Exception as e:
                    print(f"[{datetime.datetime.now()}] Error fetching comments for video {video_id}: {str(e)}")
                    break
            
            print(f"[{datetime.datetime.now()}] Total comments retrieved for video {video_id}: {len(youtube_video['comments'])}")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] Error processing videos: {str(e)}")
        
    if transformed_videos:
        print(f"[{datetime.datetime.now()}] Saving {len(transformed_videos)} videos to MongoDB")
        for i, video in enumerate(transformed_videos):
            print(f"[{datetime.datetime.now()}] Saving video {i+1}/{len(transformed_videos)}: {video['id']}")
            video_collection.update_one(
                {"id": video["id"]},
                {"$set": video}, 
                upsert=True
            )
        print(f"[{datetime.datetime.now()}] Successfully saved {len(transformed_videos)} videos to MongoDB")
    else:
        print(f"[{datetime.datetime.now()}] No videos found to save to MongoDB")
        
    print(f"[{datetime.datetime.now()}] Video fetch process completed")
    return videos

if "__main__" == __name__:
    # Start the process to fetch videos
    print(f"[{datetime.datetime.now()}] Starting initial video fetch")
    get_videos()
    # Schedule the function to run every 10 minutes
    while True:
        print(f"[{datetime.datetime.now()}] Waiting 10 minutes before next fetch...")
        time.sleep(10)  # Sleep for 10 minutes
        print(f"[{datetime.datetime.now()}] Starting scheduled video fetch")
        get_videos()