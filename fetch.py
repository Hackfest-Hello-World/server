from pymongo import MongoClient
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
from dotenv import load_dotenv
from  groq_service.groq_promt import groq_llm_promt
import msgpack
import json
import sys
   # Load environment variables
load_dotenv()
mongo_uri = os.getenv("MONGO_URI")
mongo_client = MongoClient(mongo_uri)
db = mongo_client.event_monitoring

if not mongo_uri:
    print("Error: MONGO_URI environment variable not set")
    sys.exit(1)
        
def get_form_responses_by_form_id(form_id):
      
    try:
        
        # Get the form details first to verify it exists
        forms_collection = db.forms
        form = forms_collection.find_one({"formId": form_id})
        
        if not form:
            print(f"Error: No form found with ID {form_id}")
            return []
            
        # Get all responses for this form
        responses_collection = db.form_responses
        
        # Query responses that match this form ID
        # Since the form ID isn't directly stored in responses, we need to join the data
        # We can use the form's question IDs to match responses
        form_responses = list(responses_collection.find(
            {"formId": form_id}
        ))
        
        if not form_responses:
            print(f"No responses found for form ID {form_id}")
            return []
            
        print(f"Found {len(form_responses)} responses for form: {form['title']}")
        return form_responses
        
    except Exception as e:
        print(f"Error retrieving form responses: {str(e)}")
        return []
    
def fetch_all_forms_data():
    """
    Standalone script to fetch all Google Forms and their responses using stored session data.
    This script uses the MongoDB session storage from the Flask app to authenticate with Google APIs.
    
    Returns:
        dict: A dictionary containing all forms and their responses
    """
 
    
    # MongoDB connection
   
    
    try:
        # Connect to MongoDB
      
        
        # Get the latest session from MongoDB
        session_collection = db.google_auth_session
        latest_session = session_collection.find_one(
            {"id": {"$regex": "^session:"}},
            sort=[("_id", -1)]
        )
        
        if not latest_session or 'val' not in latest_session:
            print("Error: No valid session found in MongoDB")
            return None
        
        # Extract credentials from session
        session_data = latest_session['val']
        deserialized_data = msgpack.unpackb(session_data, raw=False)
        if 'credentials' not in deserialized_data:
          print("Error: No credentials found in session data")
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
        
        # Get list of forms using Drive API
        drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        forms_results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.form'",
            fields="files(id, name)"
        ).execute()
        
        forms_list = forms_results.get('files', [])
        
        # Build the Forms API service
        forms_service = build('forms', 'v1', credentials=credentials, 
                              discoveryServiceUrl="https://forms.googleapis.com/$discovery/rest?version=v1",
                              cache_discovery=False)
        
        # Fetch each form and its responses
        all_forms_data = []
        for form in forms_list:
            form_id = form['id']
            #get all form_responses for the formId form_id from mongodb 
            
            try:
                # Get form details
                form_details = forms_service.forms().get(formId=form_id).execute()
                
                # Get form responses
                form_responses = forms_service.forms().responses().list(formId=form_id).execute()
                
                # Combine data
                form_data = {
                    "form": form_details,
                    "responses": form_responses
                }
                
                stored_responses = get_form_responses_by_form_id(form_id)
                
                # Transform data for MongoDB storage
                transformed_data = transform_form_data_for_mongodb(form_data, stored_responses)
                all_forms_data.append(transformed_data)
                
                print(f"Successfully fetched data for form: {form['name']}")
                
                # Optionally store in MongoDB
                store_form_data_in_mongodb(transformed_data, db)
                
            except Exception as e:
                print(e)
                print(f"Error fetching data for form {form['name']} (ID: {form_id}): {str(e)}")
        
        return all_forms_data
        
    except Exception as e:
        #clear the sessions from mongodb
        session_collection.delete_many({"id": {"$regex": "^session:"}})
        print(f"Error: {str(e)}")
        return None

def transform_form_data_for_mongodb(api_response, stored_responses):
    """
    Transform the Google Forms API response into a MongoDB-friendly format.
    This is the same function from your Flask application.
    """
    # Extract form data
    form_data = api_response['form']
    stored_responses_ids = [response["responseId"] for response in stored_responses]
    # Create form document
    form_document = {
        "formId": form_data['formId'],
        "title": form_data['info']['title'],
        "items": [],
        "link": f"https://docs.google.com/forms/d/{form_data['formId']}",
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
    for response in api_response['responses'].get('responses', []):
        
        # ALready the response is processed
        if response["responseId"]  in stored_responses_ids:
            print("response already processed")
            continue
        
        response_doc = {
            "formId": form_document['formId'],
            "responseId": response['responseId'],
            "createTime": response['createTime'],
            "lastSubmittedTime": response['lastSubmittedTime'],
            "answers": {},
            "sentimentAnalysis": response.get("sentimentAnalysis", None)
        }
        
        # Process answers
        if 'answers' in response:
            for question_id, answer_data in response['answers'].items():
                if question_id in question_map:
                    title = question_map[question_id]['title'].lower()
                    
                    if question_map[question_id]['type'] == "text":
                        value = answer_data['textAnswers']['answers'][0]['value']
                        response_doc['answers'][title] = value
                        
                        # Initialize sentiment analysis field for text fields
                    elif question_map[question_id]['type'] == "file" and 'fileUploadAnswers' in answer_data:
                        file_info = answer_data['fileUploadAnswers']['answers'][0]
                        response_doc['answers'][title] = {
                            "fileId": file_info['fileId'],
                            "fileName": file_info['fileName'],
                            "mimeType": file_info['mimeType']
                        }
        if response_doc["sentimentAnalysis"] is None:
            print("sentiment analysis not found in response")
            prompt = f'''You have to act as an expert in providing overall sentiment analysis for the following google form response submitted by a user. The response object provided below contains the answers object which contains key as the google form fields and value as the users answer based on it you have to do the overall sentiment analysis \n 
            Response given by the user is:
            {response_doc}
            
            You have to give the response output as a json format (Strictly stick to the output format as a json), dont include anything else, just give the output format in json as i will parse the response directly using json.loads(your_response) \n
            {{
            "sentiment": "positive/negative/neutral",
            "confidence" : 
            }}
            '''
        #   print(prompt)
            groq_response = groq_llm_promt(prompt)
            try:
                groq_response = json.loads(groq_response)
            except json.JSONDecodeError:
                print("Error decoding JSON response from Groq")
                groq_response = {
                    "sentiment": "unknown",
                    "confidence": 0.0
                }
            response_doc["sentimentAnalysis"] = groq_response
        #   break
        # break
        responses.append(response_doc)
    
    return {
        "form": form_document,
        "responses": responses
    }

def store_form_data_in_mongodb(form_data, db):
    """
    Store the form data in MongoDB collections
    
    Args:
        form_data (dict): Transformed form data
        db: MongoDB database connection
    """
    # Store form document
    forms_collection = db.forms
    forms_collection.update_one(
        {"formId": form_data["form"]["formId"]},
        {"$set": form_data["form"]},
        upsert=True
    )
    
    # Store responses
    responses_collection = db.form_responses
    for response in form_data["responses"]:
        responses_collection.update_one(
            {"responseId": response["responseId"]},
            {"$set": response},
            upsert=True
        )

if __name__ == "__main__":
    print("Starting Google Forms data fetcher...")
    forms_data = fetch_all_forms_data()
    
    if forms_data:
        print(f"Successfully fetched data for {len(forms_data)} forms")
        
        # Optionally save to a JSON file
        with open('forms_data.json', 'w') as f:
            json.dump(forms_data, f, indent=2)
        print("Data saved to forms_data.json")
    else:
        print("Failed to fetch forms data")