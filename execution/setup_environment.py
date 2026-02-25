import os
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    'https://mail.google.com/',
    'https://www.googleapis.com/auth/drive'
]

def authenticate():
    if os.path.exists('token.json'):
        return Credentials.from_authorized_user_file('token.json', SCOPES)
    raise FileNotFoundError("token.json not found. Run authenticate_google.py first.")

def setup_gmail_labels(creds):
    print("Setting up Gmail labels...")
    try:
        service = build('gmail', 'v1', credentials=creds)
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        
        # Check if AI Processed label exists
        ai_processed_label = next((label for label in labels if label['name'] == 'AI Processed'), None)
        
        if not ai_processed_label:
            print("Creating 'AI Processed' label...")
            label_object = {
                'name': 'AI Processed',
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            ai_processed_label = service.users().labels().create(userId='me', body=label_object).execute()
        
        # Write to directives
        labels_md_path = os.path.join('directives', 'gmail_labels.md')
        
        # We also re-fetch the list just to ensure freshness
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        
        with open(labels_md_path, 'w') as f:
            f.write("# Gmail Label Map\n\n")
            f.write("This file maps label names to their internal Gmail IDs. It is dynamically generated.\n\n")
            for label in labels:
                f.write(f"- **{label['name']}**: `{label['id']}`\n")
                
        print(f"✅ Successfully wrote {len(labels)} labels to {labels_md_path}")
        return labels

    except HttpError as error:
        print(f"An error occurred: {error}")
        return None

def setup_google_drive(creds):
    print("Setting up Google Drive folders...")
    try:
        service = build('drive', 'v3', credentials=creds)
        
        # Check if root "Gmail Attachments" exists
        query = "name='Gmail Attachments' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, spaces='drive', fields='nextPageToken, files(id, name)').execute()
        items = results.get('files', [])
        
        if not items:
            print("Creating 'Gmail Attachments' folder...")
            file_metadata = {
                'name': 'Gmail Attachments',
                'mimeType': 'application/vnd.google-apps.folder'
            }
            root_folder = service.files().create(body=file_metadata, fields='id').execute()
            root_id = root_folder.get('id')
        else:
            root_id = items[0].get('id')
            
        print(f"✅ Google Drive root folder ID: {root_id}")
        
        # We don't pre-create all subfolders, we'll create them dynamically on demand
        # But we do need to store the root_id somewhere for the script to use.
        # We will write it to a directive file or the .env file.
        # Let's write it to a markdown config file that the agent reads.
        
        config_path = os.path.join('directives', 'drive_config.md')
        with open(config_path, 'w') as f:
            f.write("# Google Drive Configuration\n\n")
            f.write(f"**Root_Folder_ID**: `{root_id}`\n")
            
        print(f"✅ Wrote drive config to {config_path}")
        return root_id
        
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


def setup_instructions():
    path = os.path.join('directives', 'gmail_instructions.md')
    if not os.path.exists(path):
        with open(path, 'w') as f:
            f.write("# Operational Rules\n\n")
            f.write("These rules govern how emails are processed.\n\n")
            f.write("1. **Social/Promotional**: Mark as read and archive immediately.\n")
            f.write("2. **Accounting**: Forward the email and attachments to [ACCOUNTING_EMAIL].\n")
            f.write("3. **Personal/Primary**: Draft a natural, friendly reply and attach it as a draft to the thread.\n")
            f.write("4. **Misc/Sales/Recruitment**: Apply the label and leave in the inbox.\n")
        print(f"✅ Created default instructions at {path}")

def main():
    creds = authenticate()
    setup_gmail_labels(creds)
    setup_google_drive(creds)
    setup_instructions()
    print("\n🎉 Setup Complete!")

if __name__ == '__main__':
    main()
