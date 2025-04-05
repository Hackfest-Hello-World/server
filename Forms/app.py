from flask import Flask, redirect, request, url_for, session, render_template, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from flask_session import Session
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import timedelta
load_dotenv()
import os
import json

# Configuration
app = Flask(__name__)
app.secret_key = 'hack_the_fest'  # Change this to a random secret key
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Remove this in production

# Create a MongoDB client
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client.event_monitoring

app.config['SESSION_TYPE'] = 'mongodb'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True 
app.config['SESSION_MONGODB'] = mongo_client
app.config['SESSION_MONGODB_DB'] = 'event_monitoring'
app.config['SESSION_MONGODB_COLLECT'] = 'google_auth_session'
Session(app)

# OAuth configuration
CLIENT_SECRETS_FILE = 'client_secrets.json'  # Download this from Google Cloud Console
SCOPES = [
  'https://www.googleapis.com/auth/drive',
  'https://www.googleapis.com/auth/drive.file',
  'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/forms.body.readonly',
    'https://www.googleapis.com/auth/forms.responses.readonly',
    'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/calendar.events' ,'https://www.googleapis.com/auth/youtube.readonly', 'https://www.googleapis.com/auth/youtube.force-ssl'
]
REDIRECT_URI = 'http://localhost:5000/oauth2callback'

def transform_form_data_for_mongodb(api_response):
    # Extract form data
    form_data = api_response['form']
    
    # Create form document
    form_document = {
        "formId": form_data['formId'],
        "title": form_data['info']['title'],
        "items": []
    }
    
    # Map questionId to item details for easy lookup
    question_map = {}
    for item in form_data['items']:
        if 'questionItem' in item:
            question_id = item['questionItem']['question']['questionId']
            item_type = "file" if 'fileUploadQuestion' in item['questionItem']['question'] else "text"
            
            form_document['items'].append({
                "itemId": item['itemId'],
                "questionId": question_id,
                "title": item['title'],
                "type": item_type
            })
            
            question_map[question_id] = {
                "title": item['title'],
                "type": item_type
            }
    
    # Process responses
    responses = []
    for response in api_response['responses']['responses']:
        response_doc = {
            "formId": form_data['formId'],
            "responseId": response['responseId'],
            "createTime": response['createTime'],
            "lastSubmittedTime": response['lastSubmittedTime'],
            "answers": {},
            "sentimentAnalysis": {}
        }
        
        # Process answers
        for question_id, answer_data in response['answers'].items():
            if question_id in question_map:
                title = question_map[question_id]['title'].lower().replace(' ', '')
                
                if question_map[question_id]['type'] == "text":
                    value = answer_data['textAnswers']['answers'][0]['value']
                    response_doc['answers'][title] = value
                    
                    # Initialize sentiment analysis field for text fields
                    # You can later populate this with actual sentiment analysis results
                    response_doc['sentimentAnalysis'][title] = {
                        "score": 0,
                        "magnitude": 0,
                        "sentiment": "neutral"
                    }
                elif question_map[question_id]['type'] == "file" and 'fileUploadAnswers' in answer_data:
                    file_info = answer_data['fileUploadAnswers']['answers'][0]
                    response_doc['answers'][title] = {
                        "fileId": file_info['fileId'],
                        "fileName": file_info['fileName'],
                        "mimeType": file_info['mimeType']
                    }
        
        responses.append(response_doc)
    
    return {
        "form": form_document,
        "responses": responses
    }


@app.route('/')
def index():
    if 'credentials' not in session:
        return redirect("/login")
    return redirect("/dashboard")

@app.route('/login')
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session.permanent = True
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if 'credentials' not in session:
        return redirect("/login")
    return "Authentication Success!"
  
@app.route('/forms')
def get_forms():
    if 'credentials' not in session:
        return redirect(url_for('login'))
    
    credentials = Credentials(**session['credentials'])
    
    # Use the Drive API to list files of type 'form'
    drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
    results = drive_service.files().list(
        q="mimeType='application/vnd.google-apps.form'",
        fields="files(id, name)"
    ).execute()
    
    forms = results.get('files', [])
    
    # Add URL to each form
    for form in forms:
        form['url'] = f"https://docs.google.com/forms/d/{form['id']}"
    
    return jsonify(forms)

@app.route('/form/<form_id>/responses')
def get_form_responses(form_id):
    if 'credentials' not in session:
        return redirect(url_for('login'))
    
    credentials = Credentials(**session['credentials'])
    
    # Build the Forms API service
    forms_service = build('forms', 'v1', credentials=credentials, 
                          discoveryServiceUrl="https://forms.googleapis.com/$discovery/rest?version=v1",
                          cache_discovery=False)
    
    # Get form details
    form = forms_service.forms().get(formId=form_id).execute()
    
    # Get form responses
    responses = forms_service.forms().responses().list(formId=form_id).execute()
    api_responses = {}
    api_responses["form"] = form
    api_responses["responses"] = responses
    
    api_responses = transform_form_data_for_mongodb(api_responses)
    return jsonify(api_responses)
    
  

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
