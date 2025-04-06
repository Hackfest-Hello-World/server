from flask import Flask, request, redirect, session, jsonify
import google_auth_oauthlib.flow
import googleapiclient.discovery
import os
import json
import pandas as pd
import google
from flask_cors import CORS
from datetime import datetime, timezone, timedelta

# Disable OAuthlib's HTTPS verification for local development
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

app = Flask(__name__)
app.secret_key = "hack_fest"
CORS(app)
# app.secret_key = 'hack_the_fest'  # Replace with a secure random key

# YouTube API settings
CLIENT_SECRETS_FILE = "client_secrets.json"
SCOPES = [
  'https://www.googleapis.com/auth/drive',
  'https://www.googleapis.com/auth/drive.file',
  'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/forms.body.readonly',
    'https://www.googleapis.com/auth/forms.responses.readonly',
    'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/calendar.events' ,'https://www.googleapis.com/auth/youtube.readonly', 'https://www.googleapis.com/auth/youtube.force-ssl'
]
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'


@app.route('/')
def index():
    return "YouTube API Integration Server"

@app.route('/authorize')
def authorize():
    # Create flow instance to manage the OAuth 2.0 Authorization Grant Flow
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    
    # Set the redirect URI
    flow.redirect_uri = 'http://localhost:5000/oauth2callback'
    
    # Generate URL for request to Google's OAuth 2.0 server
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')
    
    # Store the state in the session for later validation
    session['state'] = state
    
    # Redirect the user to Google's OAuth 2.0 server
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    # Specify the state when creating the flow in the callback
    state = session['state']
    
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = 'http://localhost:5000/oauth2callback'
    
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
    
    return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    if 'credentials' not in session:
        return redirect('/authorize')
    
    return "Authentication successful! You can now use the API endpoints."


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
    
    # Update the session with refreshed credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
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
    
    # Update the session with refreshed credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    return jsonify(comments)

@app.route('/export_comments/<video_id>')
def export_comments(video_id):
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
    
    # Create a DataFrame and export to CSV
    df = pd.DataFrame(comments)
    csv_filename = f"comments_{video_id}.csv"
    df.to_csv(csv_filename, index=False)
    
    return jsonify({"message": f"Exported {len(comments)} comments to {csv_filename}"})

@app.route('/start_live_stream')
def start_live_stream():
  if 'credentials' not in session:
    return jsonify({"error": "Not authenticated"}), 401
  credentials = google.oauth2.credentials.Credentials(**session['credentials'])
  youtube = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
  
  # Create a live broadcast (placeholder values; adjust the scheduledStartTime as needed)
  broadcast_response = youtube.liveBroadcasts().insert(
    part="snippet,status,contentDetails",
    body={
    "snippet": {
      "title": "New Live Stream",
      "scheduledStartTime": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")  # Current time + 1 minute
    },
    "status": {
      "privacyStatus": "public"
    },
    "contentDetails": {
      "enableAutoStart": True,
      "enableAutoStop": True
    }
    }
  ).execute()
  
  # Retrieve liveChatId from the broadcast response if available
  snippet = broadcast_response.get('snippet', "CHAT_NOT_AVAILABLE")
  live_chat_id = snippet.get('liveChatId', "CHAT_NOT_AVAILABLE")
  broadcast_id = broadcast_response.get('id')
  session['live_chat_id'] = live_chat_id
  print(live_chat_id)
  # Redirect to YouTube live stream page
  youtube_url = f"https://www.youtube.com/watch?v={broadcast_id}"
  return redirect(youtube_url)

@app.route('/live_comments')
def live_comments():
    if 'credentials' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    if 'live_chat_id' not in session:
        return jsonify({"error": "Live stream not started"}), 400
    broadcast_id = session['live_chat_id']

    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    youtube = googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
    try:
        live_chat_response = youtube.liveChatMessages().list(
            liveChatId=broadcast_id,
            part="snippet,authorDetails",
            maxResults=200,
            # pageToken="1"
        ).execute()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    comments = []
    for item in live_chat_response.get("items", []):
        comments.append({
            "author": item['authorDetails']['displayName'],
            "message": item['snippet']['displayMessage'],
            "publishedAt": item['snippet']['publishedAt']
        })
    
    return jsonify(comments)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
