import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from config import CREDENTIALS_FILE, TOKEN_FILE

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def authorize():
    print("Starting authorization flow...")
    creds = None
    if os.path.exists(TOKEN_FILE):
        print(f"Loading existing credentials from {TOKEN_FILE}")
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired credentials...")
            creds.refresh(Request())
        else:
            print(f"No valid credentials found. Using {CREDENTIALS_FILE}")
            if not os.path.exists(CREDENTIALS_FILE):
                print(f"Error: {CREDENTIALS_FILE} not found!")
                return
            
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            # Use console flow if local server fails or to get the URL
            print("Please follow the instructions to authorize the app.")
            creds = flow.run_local_server(port=0, open_browser=False)
        
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        print(f"Credentials saved to {TOKEN_FILE}")

if __name__ == '__main__':
    authorize()
