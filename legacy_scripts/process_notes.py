#!/usr/bin/env python3
"""
MathStudio Note Processor (Modern Edition)
Monitors Google Drive for handwritten notes and processes them using established services.
"""

import os
import time
import json
import io
import logging
import shutil
from pathlib import Path
from datetime import datetime

# Google Libraries for Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# MathStudio Services & Config
from core.config import (
    PROJECT_ROOT, DB_FILE, NOTES_OUTPUT_DIR, 
    get_api_key, GEMINI_MODEL
)
from core.ai import ai
from services.note import note_service

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "process_notes.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("note-processor")

# --- Configuration ---
POLL_INTERVAL = 60 # Seconds
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"

class DriveMonitor:
    def __init__(self, credentials_path: Path):
        self.service = self._authenticate(credentials_path)
        if not self.service:
            raise RuntimeError("Could not initialize Google Drive service.")
        
        self.root_folder_name = "MathNotes"
        self.input_folder_name = "Input"
        self.processed_folder_name = "Processed"
        
        # Initialize folder IDs
        self.root_id = self._find_or_create_folder(self.root_folder_name)
        self.input_id = self._find_or_create_folder(self.input_folder_name, self.root_id)
        self.processed_id = self._find_or_create_folder(self.processed_folder_name, self.root_id)

    def _authenticate(self, path: Path):
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(path), scopes=['https://www.googleapis.com/auth/drive']
            )
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            logger.error(f"Drive Authentication failed: {e}")
            return None

    def _find_or_create_folder(self, name, parent_id=None):
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if files:
            return files[0]['id']
        else:
            file_metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
            if parent_id:
                file_metadata['parents'] = [parent_id]
            file = self.service.files().create(body=file_metadata, fields='id').execute()
            logger.info(f"Created Drive folder: {name} ({file.get('id')})")
            return file.get('id')

    def list_new_files(self):
        """List files in the input folder."""
        try:
            results = self.service.files().list(
                q=f"'{self.input_id}' in parents and trashed = false",
                fields="files(id, name, mimeType)"
            ).execute()
            return results.get('files', [])
        except Exception as e:
            logger.error(f"Failed to list Drive files: {e}")
            return []

    def download_file(self, file_id):
        """Download file content to memory."""
        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            return fh.getvalue()
        except Exception as e:
            logger.error(f"Failed to download file {file_id}: {e}")
            return None

    def mark_processed(self, file_id):
        """Move file to Processed folder."""
        try:
            file = self.service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            self.service.files().update(
                fileId=file_id,
                removeParents=previous_parents,
                addParents=self.processed_id,
                fields='id, parents'
            ).execute()
            logger.info(f"Moved file {file_id} to Processed folder.")
            return True
        except Exception as e:
            logger.error(f"Failed to move file {file_id}: {e}")
            return False

def run_processor():
    logger.info("Starting MathStudio Note Processor...")
    
    try:
        monitor = DriveMonitor(CREDENTIALS_FILE)
    except Exception as e:
        logger.critical(f"Initialization failed: {e}")
        return

    logger.info(f"Monitoring folder: MathNotes/Input (ID: {monitor.input_id})")

    while True:
        files = monitor.list_new_files()
        
        for f in files:
            filename = f['name']
            file_id = f['id']
            mime_type = f['mimeType']
            
            if not mime_type.startswith('image/'):
                logger.info(f"Skipping non-image file: {filename}")
                continue
            
            logger.info(f"Processing new note: {filename}...")
            
            # 1. Download
            image_data = monitor.download_file(file_id)
            if not image_data:
                continue
            
            # 2. Transcribe via Gemini (using modern AIService)
            # We use the note_service logic for transcription but ensure it uses our AIService
            try:
                # Note: note_service.transcribe_note already uses AIService internally
                transcription = note_service.transcribe_note(image_data)
                
                if transcription:
                    # 3. Process, Save files and DB record
                    # Using the standard pipeline method
                    note_id = note_service.process_uploaded_note(transcription, image_data)
                    logger.info(f"Successfully processed note {note_id}: {transcription.get('title')}")
                    
                    # 4. Cleanup Drive
                    monitor.mark_processed(file_id)
                else:
                    logger.error(f"Transcription failed for {filename}")
                    
            except Exception as e:
                logger.error(f"Error during note processing: {e}", exc_info=True)

        # Cool down
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    try:
        run_processor()
    except KeyboardInterrupt:
        logger.info("Processor stopped by user.")
