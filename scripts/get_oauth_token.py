import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# Scopes required for full drive access
SCOPES = ['https://www.googleapis.com/auth/drive']
CLIENT_SECRET_FILE = 'client_secret_933194804549-mjefvrc6cqf6pev4d47uc9skotna31a2.apps.googleusercontent.com.json'
TOKEN_FILE = 'token.json'

def get_token():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    
    # Use console-based flow since there is no local browser
    # This will output a URL and wait for the code
    creds = flow.run_local_server(
        port=0, 
        success_message='Authorization successful! You can close this tab.',
        open_browser=False
    )
    
    # Save the credentials for the next run
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
    
    print(f"\nSuccessfully saved new token to {TOKEN_FILE}")
    print(f"New Scopes: {creds.scopes}")

if __name__ == '__main__':
    get_token()
