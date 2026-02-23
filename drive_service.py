import os
import io
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from config import CREDENTIALS_FILE, TOKEN_FILE

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive.file']

class GoogleAuthError(Exception):
    """Custom exception for Google Drive authentication errors."""
    pass

def get_auth_flow():
    """Creates an InstalledAppFlow instance."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Credentials file '{CREDENTIALS_FILE}' not found. Please download it from Google Cloud Console or set GDRIVE_CREDENTIALS env var.")
    return InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES, redirect_uri='urn:ietf:wg:oauth:2.0:oob')

def get_drive_service():
    """Gets the Google Drive API service."""
    
    # Heroku compatibility: Recreate credentials files from environment variables
    if not os.path.exists(CREDENTIALS_FILE) and "GDRIVE_CREDENTIALS" in os.environ:
        with open(CREDENTIALS_FILE, 'w') as f:
            f.write(os.environ["GDRIVE_CREDENTIALS"])
            
    if not os.path.exists(TOKEN_FILE) and "GDRIVE_TOKEN" in os.environ:
        with open(TOKEN_FILE, 'w') as f:
            f.write(os.environ["GDRIVE_TOKEN"])

    creds = None
    # The file token.json stores the user's access and refresh tokens
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # If there are no (valid) credentials available, try to refresh or raise error
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save the refreshed credentials
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                raise GoogleAuthError(f"Failed to refresh token: {str(e)}")
        else:
            raise GoogleAuthError("No valid credentials found. Please use /reauth to authorize the bot.")

    return build('drive', 'v3', credentials=creds)

def save_token(auth_code):
    """Initializes and saves token from auth code."""
    flow = get_auth_flow()
    flow.fetch_token(code=auth_code)
    creds = flow.credentials
    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
    return True

def upload_file(service, file_name, file_content, folder_id, mime_type='application/octet-stream', progress_callback=None, check_cancelled=None):
    """Uploads a file to Google Drive."""
    file_metadata = {
        'name': file_name,
        'parents': [folder_id] if folder_id else []
    }
    
    media = MediaIoBaseUpload(file_content, mimetype=mime_type, resumable=True)
    request = service.files().create(body=file_metadata, media_body=media, fields='id')
    
    response = None
    while response is None:
        if check_cancelled and check_cancelled():
            raise Exception("Upload cancelled by admin")
            
        try:
            status, response = request.next_chunk()
            if status and progress_callback:
                progress_callback(status.progress())
        except Exception as e:
            # Re-raise or handle specific error if needed
            raise e
            
    return response.get('id')

def list_files_in_folder(service, folder_id):
    """Lists all files in a specific folder (Name based)."""
    files = []
    page_token = None
    while True:
        try:
            response = service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces='drive',
                fields='nextPageToken, files(id, name, createdTime)',
                pageToken=page_token
            ).execute()
            files.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        except Exception as e:
            print(f"Error listing files: {e}")
            break
    return files

def find_duplicates(service, folder_id):
    """Finds duplicate files in a folder based on NORMALIZED name match."""
    files = list_files_in_folder(service, folder_id)
    name_map = {}
    
    for f in files:
        # Normalize: Lowercase and strip whitespace
        # This catches "File.txt " and "file.txt" as duplicates
        norm_name = f['name'].strip().lower()
        
        if norm_name not in name_map:
            name_map[norm_name] = []
        name_map[norm_name].append(f)
    
    # Filter for names with more than one file
    duplicates = {name: items for name, items in name_map.items() if len(items) > 1}
    return duplicates

def delete_file(service, file_id):
    """Deletes a file from Google Drive."""
    try:
        service.files().delete(fileId=file_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting file {file_id}: {e}")
        return False
