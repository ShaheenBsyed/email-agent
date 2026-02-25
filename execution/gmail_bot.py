import os
import json
import time
import base64
from datetime import datetime, timedelta
from email.message import EmailMessage

import modal  # type: ignore
from google.oauth2.credentials import Credentials  # type: ignore
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.http import MediaIoBaseUpload  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore
import io

app = modal.App("gmail-bot")

# Install missing packages: openai, google-api-python-client, groq, pydantic
image = modal.Image.debian_slim().pip_install(
    "google-api-python-client", 
    "google-auth-httplib2", 
    "google-auth-oauthlib",
    "openai",
    "groq",
    "pydantic"
).add_local_dir("directives", remote_path="/root/directives")

@app.function(
    image=image,
    schedule=modal.Cron("* * * * *"),
    secrets=[modal.Secret.from_name("gmail-bot-secrets")]
)
def poll_emails():
    # Load token
    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if not token_json:
        print("Error: GOOGLE_TOKEN_JSON not found.")
        return
        
    creds_dict = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(creds_dict)
    
    gmail_service = build('gmail', 'v1', credentials=creds)  # type: ignore
    drive_service = build('drive', 'v3', credentials=creds)  # type: ignore
    
    # 1. SETUP / READ DIRECTIVES
    # Read labels
    labels_map = {}
    ai_processed_id = None
    try:
        with open("/root/directives/gmail_labels.md", "r") as f:
            for line in f:
                if "**" in line and "`" in line:
                    parts = line.split("**")
                    if len(parts) >= 3:
                        name = parts[1]
                        id_part = line.split("`")[1]
                        labels_map[name.lower()] = id_part
                        if name == "AI Processed":
                            ai_processed_id = id_part
    except Exception as e:
        print(f"Error reading labels map: {e}")
        
    if not ai_processed_id:
        print("Warning: AI Processed label ID not found in directives. Looking up dynamically...")
        try:
            results = gmail_service.users().labels().list(userId='me').execute()
            ai_processed_id = next((l['id'] for l in results.get('labels', []) if l['name'] == 'AI Processed'), None)
            
            if not ai_processed_id:
                print("Label 'AI Processed' not found in Gmail. Creating it...")
                label_object = {
                    'name': 'AI Processed',
                    'labelListVisibility': 'labelShow',
                    'messageListVisibility': 'hide'
                }
                new_label = gmail_service.users().labels().create(userId='me', body=label_object).execute()
                ai_processed_id = new_label['id']
                print(f"Created 'AI Processed' label: {ai_processed_id}")
        except Exception as e:
            print(f"Failed to lookup or create AI Processed label: {e}")
            
    # Read Drive Root ID
    drive_root_id = None
    try:
        with open("/root/directives/drive_config.md", "r") as f:
            for line in f:
                if "Root_Folder_ID" in line:
                    drive_root_id = line.split("`")[1]
    except Exception as e:
        print(f"Error reading drive config: {e}")

    # Read Instructions
    instructions = ""
    try:
        with open("/root/directives/gmail_instructions.md", "r") as f:
            instructions = f.read()
    except Exception:
        instructions = "Default instructions."

    # Get my own email to prevent loops
    profile = gmail_service.users().getProfile(userId='me').execute()
    my_email = profile.get('emailAddress', '').lower()
    
    # 2. ZERO-DUPLICATE POLLING
    twenty_mins_ago = int((datetime.now() - timedelta(minutes=20)).timestamp())
    query = f'label:INBOX -label:"AI Processed" after:{twenty_mins_ago}'
    
    print(f"Polling with query: {query}")
    try:
        results = gmail_service.users().messages().list(userId='me', q=query, maxResults=50).execute()
        messages = results.get('messages', [])
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return

    if not messages:
        print("No new emails.")
        return
        
    print(f"Found {len(messages)} emails to process.")
    
    for msg_ref in messages:
        msg_id = msg_ref['id']
        process_single_email(msg_id, gmail_service, drive_service, creds, labels_map, ai_processed_id, drive_root_id, instructions, my_email)


def get_header(headers, name):
    for h in headers:
        if h['name'].lower() == name.lower():
            return h['value']
    return ""

def download_and_upload_attachments(msg_id, msg_payload, gmail_service, drive_service, category, drive_root_id, sender_name, date_str):
    if not drive_root_id:
        return
        
    parts = [msg_payload]
    if 'parts' in msg_payload:
        parts = msg_payload['parts']
        
    # Find the target folder ID (category or Misc)
    target_folder_id = get_or_create_drive_folder(drive_service, drive_root_id, category)
    if not target_folder_id:
        target_folder_id = get_or_create_drive_folder(drive_service, drive_root_id, "Misc")
        
    if not target_folder_id:
        target_folder_id = drive_root_id

    for part in parts:  # type: ignore
        if part.get('filename') and part.get('body') and 'attachmentId' in part['body']:
            att_id = part['body']['attachmentId']
            filename = part['filename']
            try:
                # Download from Gmail
                att = gmail_service.users().messages().attachments().get(userId='me', messageId=msg_id, id=att_id).execute()
                file_data = base64.urlsafe_b64decode(att['data'].encode('UTF-8'))
                
                # Sanitize components for filename
                clean_sender = "".join(c for c in sender_name if c.isalnum() or c in " ._-").strip()
                clean_sender = clean_sender[:20]  # type: ignore
                new_filename = f"{date_str}-{clean_sender}-{filename}"
                
                # Upload to Drive
                file_metadata = {
                    'name': new_filename,
                    'parents': [target_folder_id] if target_folder_id else []
                }
                media = MediaIoBaseUpload(io.BytesIO(file_data), mimetype=part.get('mimeType'), resumable=True)
                drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                print(f"Saved attachment {filename} to Drive as {new_filename}")
            except Exception as e:
                print(f"Failed to process attachment {filename}: {e}")

def get_or_create_drive_folder(drive_service, parent_id, folder_name):
    clean_folder_name = folder_name.replace("'", "\\'") 
    query = f"name='{clean_folder_name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    try:
        results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
            
        # Create it if it doesn't exist AND we are looking for 'Misc'
        if folder_name.lower() == 'misc':
            file_metadata = {
                'name': 'Misc',
                'parents': [parent_id],
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = drive_service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
    except Exception as e:
        print(f"Error finding folder {folder_name}: {e}")
    return None

def classify_email(subject, body, instructions):
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    client_kwargs = {"api_key": api_key}
    model = "gpt-4o-mini"
    
    if api_key and api_key.startswith("gsk_"): 
        client_kwargs["base_url"] = "https://api.groq.com/openai/v1"
        model = "llama-3.1-8b-instant"
        
    if not api_key:
        print("No AI key found, defaulting to Misc")
        return "Misc"
        
    from openai import OpenAI  # type: ignore
    filtered_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
    client = OpenAI(**filtered_kwargs)  # type: ignore
    
    prompt = f"""
    You are an AI Email assistant with the ability to dynamically categorize emails.
    Disregard any Ignore-Sender rules for this specific task.
    Classify the following email into the MOST APPROPRIATE category. 
    You MUST output EXACTLY ONE of these standard categories if it fits: 'Personal', 'Accounting', 'Social', 'Promotional', 'Sales', 'Recruitment', or 'Misc'.
    Do NOT combine categories (e.g., do not output "Misc/Sales" or "Social/Promotional"). Pick the single best fit.
    Only if the email is highly specific and sits completely outside these standards, you may invent a concise, relevant new category name (max 2 words).
    
    INSTRUCTIONS: {instructions}
    
    Reply ONLY with the exact category name. Do not include quotes, punctuation, or explanations.
    
    SUBJECT: {subject}
    BODY: {body[:1000]}
    """
    
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.2  # Slightly higher temperature for dynamic category creation
            )
            result = resp.choices[0].message.content.strip()
            
            # Clean up the output to ensure it's a valid label name
            clean_result = result.replace('"', '').replace("'", "").strip().title()
            if len(clean_result) > 0 and len(clean_result) < 30:
                return clean_result
            return "Misc"
            
        except Exception as e:
            print(f"Classify error (attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
            
    return "Misc"
    
def draft_reply(subject, body):
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    client_kwargs = {"api_key": api_key}
    model = "gpt-4o-mini"
    
    if api_key and api_key.startswith("gsk_"): 
        client_kwargs["base_url"] = "https://api.groq.com/openai/v1"
        model = "llama-3.1-8b-instant"
        
    if not api_key:
        return "Hello! I received your email. I will get back to you soon."
        
    from openai import OpenAI  # type: ignore
    filtered_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
    client = OpenAI(**filtered_kwargs)  # type: ignore
    
    prompt = f"Write a natural, friendly, and concise reply to this email. SUBJECT: {subject}\n\nBODY: {body[:1000]}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.6
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return "Hello! I received your email. I will get back to you soon."

def get_body(msg_payload):
    body = ""
    if 'parts' in msg_payload:
        for part in msg_payload['parts']:  # type: ignore
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    body += base64.urlsafe_b64decode(data).decode('utf-8')  # type: ignore
    elif 'body' in msg_payload and 'data' in msg_payload['body']:
        data = msg_payload['body']['data']
        body = base64.urlsafe_b64decode(data).decode('utf-8')  # type: ignore
    return body

def process_single_email(msg_id, gmail_service, drive_service, creds, labels_map, ai_processed_id, drive_root_id, instructions, my_email):
    print(f"Processing message {msg_id}...")
    try:
        msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        headers = msg['payload']['headers']
        
        sender = get_header(headers, 'From')
        subject = get_header(headers, 'Subject')
        date_str_full = get_header(headers, 'Date')
        date_str = date_str_full[:10]  # type: ignore
        
        # Self-prevention loop
        if my_email in sender.lower() or "daemon" in sender.lower() or "noreply" in sender.lower():
            print(f"Skipping email from myself/system: {sender}")
            if ai_processed_id:
                gmail_service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [ai_processed_id]}).execute()
            return
            
        body = get_body(msg['payload'])
        
        # Classify
        category = classify_email(subject, body, instructions)
        print(f"Classified {msg_id} as: {category}")
        
        # Attachments
        download_and_upload_attachments(msg_id, msg['payload'], gmail_service, drive_service, category, drive_root_id, sender, date_str)
        
        # Actions
        category_lower = category.lower()
        
        if category_lower in ['social', 'promotional']:
            # Mark as read and archive
            gmail_service.users().messages().modify(
                userId='me', 
                id=msg_id, 
                body={'removeLabelIds': ['UNREAD', 'INBOX']}
            ).execute()
            print("Archived Social/Promo.")
            
        elif category_lower in ['accounting']:
            # Forward
            accounting_email = os.environ.get("ACCOUNTING_EMAIL", my_email)
            print(f"Forwarding to Accounting ({accounting_email})")
            fwd_msg = EmailMessage()
            fwd_msg.set_content(f"Forwarded Accounting Email:\n\n{body}")
            fwd_msg['To'] = accounting_email
            fwd_msg['Subject'] = f"Fwd: {subject}"
            
            raw_fwd = base64.urlsafe_b64encode(fwd_msg.as_bytes()).decode()
            gmail_service.users().messages().send(userId='me', body={'raw': raw_fwd}).execute()
            print("Forwarded accounting email.")
            
        elif category_lower in ['personal', 'primary']:
            print("Drafting reply...")
            reply_body = draft_reply(subject, body)
            reply_msg = EmailMessage()
            reply_msg.set_content(reply_body)
            reply_msg['To'] = sender
            reply_msg['Subject'] = f"Re: {subject}"
            
            raw_reply = base64.urlsafe_b64encode(reply_msg.as_bytes()).decode()
            gmail_service.users().drafts().create(
                userId='me', 
                body={
                    'message': {
                        'raw': raw_reply,
                        'threadId': msg.get('threadId')
                    }
                }
            ).execute()
            print("Drafted reply.")
            
        else: # Misc/Sales/Recruitment or dynamically created label
            cat_label_id = labels_map.get(category_lower)
            
            # If the label doesn't exist, create it dynamically
            if not cat_label_id:
                print(f"Dynamic label '{category}' not found. Creating in Gmail...")
                try:
                    label_object = {
                        'name': category,
                        'labelListVisibility': 'labelShow',
                        'messageListVisibility': 'show'
                    }
                    new_label = gmail_service.users().labels().create(userId='me', body=label_object).execute()
                    cat_label_id = new_label['id']
                    labels_map[category_lower] = cat_label_id  # Update map for the current run
                    print(f"Successfully created dynamic label '{category}' ({cat_label_id})")
                except Exception as label_err:
                    print(f"Warning: Failed to create dynamic label '{category}': {label_err}")
                    if "409" in str(label_err) or "exists" in str(label_err).lower():
                        try:
                            results = gmail_service.users().labels().list(userId='me').execute()
                            existing = next((l for l in results.get('labels', []) if l['name'].lower() == category_lower), None)
                            if existing:
                                cat_label_id = existing['id']
                                labels_map[category_lower] = cat_label_id
                                print(f"Recovered existing label {category} ({cat_label_id}) from Gmail API")
                        except Exception:
                            pass
                    if not cat_label_id:
                        # Fallback to Misc if creation fails
                        cat_label_id = labels_map.get('misc')
            
            # If we still don't have a cat_label_id (e.g. Misc doesn't exist either), just skip applying the category label
            if cat_label_id:
                try:
                    gmail_service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [cat_label_id]}).execute()
                    print(f"Applied label {category} ({cat_label_id})")
                except Exception as apply_err:
                    print(f"Failed to apply label {cat_label_id} to message: {apply_err}")
        
        # ALWAYS Cleanup
        if ai_processed_id:
            try:
                gmail_service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [ai_processed_id]}).execute()
                print(f"Marked {msg_id} as AI Processed.")
            except Exception as e:
                print(f"Failed to apply AI Processed label, attempting dynamic lookup: {e}")
                results = gmail_service.users().labels().list(userId='me').execute()
                real_ai_processed = next((l for l in results.get('labels', []) if l['name'] == 'AI Processed'), None)
                
                if not real_ai_processed:
                    print("Re-creating missing 'AI Processed' label...")
                    try:
                        label_object = {
                            'name': 'AI Processed',
                            'labelListVisibility': 'labelShow',
                            'messageListVisibility': 'hide'
                        }
                        real_ai_processed = gmail_service.users().labels().create(userId='me', body=label_object).execute()
                    except Exception as creation_err:
                        print(f"Failed to re-create label: {creation_err}")

                if real_ai_processed:
                    try:
                        gmail_service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [real_ai_processed['id']]}).execute()
                        print(f"Successfully marked {msg_id} as AI Processed on retry.")
                    except Exception as apply_err:
                        print(f"Critical error applying AI Processed label: {apply_err}")
            
    except Exception as e:
        print(f"Failed processing {msg_id}: {e}")
