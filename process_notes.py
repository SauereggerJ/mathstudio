import os
import time
import json
import io
import requests
import sqlite3
import numpy as np
import subprocess
import shutil
from pathlib import Path
from PIL import Image

# Google Libraries
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions

# Configuration Utils
from utils import load_api_key

# --- Configuration ---
GEMINI_API_KEY = load_api_key()
CREDENTIALS_FILE = "credentials.json"
DB_FILE = "library.db"
POLL_INTERVAL = 60  # Erhöht auf 60s
LOCAL_OUTPUT_DIR = "notes_output"

# PFAD: Server-Obsidian-Vault
OBSIDIAN_INBOX = "/obsidian/00_Inbox"

# Modelle
GEMINI_MODEL = "gemini-2.0-flash" 
EMBEDDING_MODEL = "models/gemini-embedding-001"

# Client Setup
if not GEMINI_API_KEY:
    print("❌ CRITICAL ERROR: Kein API Key geladen. Prüfe credentials.json!")
    exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# Ensure local output directory exists
if not os.path.exists(LOCAL_OUTPUT_DIR):
    os.makedirs(LOCAL_OUTPUT_DIR)


def optimize_image(image_bytes, max_size=2048):
    """Skaliert das Bild herunter und komprimiert es, um TPM-Limits zu schonen."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # In RGB konvertieren (falls RGBA)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        # Proportionen erhalten und skalieren
        w, h = img.size
        if max(w, h) > max_size:
            if w > h:
                new_w = max_size
                new_h = int(h * (max_size / w))
            else:
                new_h = max_size
                new_w = int(w * (max_size / h))
            
            print(f"  📐 Skaliere Bild von {w}x{h} auf {new_w}x{new_h}...")
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        # Als JPEG komprimieren
        out_io = io.BytesIO()
        img.save(out_io, format="JPEG", quality=85, optimize=True)
        return out_io.getvalue()
    except Exception as e:
        print(f"  ⚠️ Optimierung fehlgeschlagen: {e}. Nutze Original.")
        return image_bytes

def get_drive_service():
    """Authentifiziert sich gegenüber Google Drive."""
    try:
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ Fehler beim Laden der Drive Credentials: {e}")
        return None

def find_or_create_folder(service, name, parent_id=None):
    """Hilfsfunktion für Drive Ordner."""
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    else:
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
        file = service.files().create(body=file_metadata, fields='id').execute()
        return file.get('id')

def get_gemini_content(image_data, mime_type):
    """Sends image to Gemini for LaTeX and Markdown conversion (Infinite Retry Loop)."""
    import base64
    
    # Bild vor dem Senden optimieren
    optimized_data = optimize_image(image_data)
    encoded_image = base64.b64encode(optimized_data).decode('utf-8')
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    prompt = (
        "You are a mathematical transcription expert. Convert this handwritten note into two formats:\n"
        "1. High-quality, clean LaTeX code for PDF generation.\n"
        "2. Obsidian-flavored Markdown for digital notes.\n\n"
        "Requirements:\n"
        "- **LaTeX**: Use standard amsmath environments. Expand abbreviations.\n"
        "- **Markdown**: Use $...$ for inline math and $$...$$ for block math. Include a YAML frontmatter.\n"
        "- **Output**: Return a JSON object with keys: 'latex_source', 'markdown_source', 'title', 'tags'.\n"
        "IMPORTANT: The response must be valid JSON. All backslashes in LaTeX must be properly escaped (e.g., \\\\section instead of \\section)."
    )
    
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": encoded_image}} # Immer JPEG nach Optimierung
            ]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }
    
    retry_count = 0
    backoff = 30 # Start with 30s as lockout can be long
    
    while True: # Infinite robustness
        try:
            response = requests.post(url, json=payload, timeout=60)
            
            if response.status_code == 429:
                sleep_time = min(backoff, 300) # Max 5 mins
                print(f"  ⚠️ Rate Limit (Bild-Analyse). Warte {sleep_time}s (Versuch {retry_count+1})...")
                time.sleep(sleep_time)
                retry_count += 1
                backoff *= 1.5
                continue
            
            if response.status_code != 200:
                print(f"  ❌ API Error {response.status_code}: {response.text}")
                return None

            result = response.json()
            if 'candidates' not in result or not result['candidates']:
                 print(f"  ❌ Keine Kandidaten von Gemini erhalten.")
                 return None
                 
            text = result['candidates'][0]['content']['parts'][0]['text']
            
            try:
                # First attempt: standard JSON
                return json.loads(text)
            except json.JSONDecodeError as jde:
                print(f"  ⚠️ JSON Parse Fehler: {jde}. Versuche Reparatur...")
                # Repariere LaTeX-Backslashes (verdoppeln, wenn sie nicht escaped sind)
                # Vorsicht: sehr simpel, aber oft effektiv für Gemini-Glitches
                import re
                repaired = re.sub(r'(?<!\\)\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', text)
                try:
                    return json.loads(repaired)
                except:
                    print(f"  ❌ JSON Reparatur fehlgeschlagen. Rohdaten: {text[:200]}...")
                    return None
            
        except Exception as e:
            if "429" in str(e):
                sleep_time = min(backoff, 300)
                print(f"  ⚠️ Rate Limit (Ex). Warte {sleep_time}s...")
                time.sleep(sleep_time)
                retry_count += 1
                backoff *= 1.5
                continue
            print(f"  ❌ Verbindungsproblem / Fehler: {e}")
            return None

def get_recommendations(text, limit=3):
    """Findet passende Bücher mit Retry-Logik."""
    if not text: return "", []
    
    retry_count = 0
    backoff = 2
    max_retries = 5
    query_vec = None
    
    while retry_count < max_retries:
        try:
            res = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=[text[:9000]],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=768
                )
            )
            query_vec = np.array(res.embeddings[0].values, dtype=np.float32)
            break
            
        except (google_exceptions.ResourceExhausted, google_exceptions.ServiceUnavailable) as e:
            print(f"  ⚠️ Rate Limit (Embedding). Warte {backoff}s...")
            time.sleep(backoff)
            retry_count += 1
            backoff *= 2
        except Exception as e:
            print(f"  ❌ Embedding Fehler: {e}")
            return "", []

    if query_vec is None:
        print("  ❌ Konnte kein Embedding erstellen.")
        return "", []

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, author, embedding FROM books WHERE embedding IS NOT NULL")
        rows = cursor.fetchall()
        
        if not rows: 
            conn.close()
            return "", []

        ids, titles, authors, vectors = [], [], [], []
        for book_id, t, a, blob in rows:
            if not blob: continue
            
            vec = np.frombuffer(blob, dtype=np.float32)
            if len(vec) != len(query_vec): continue
                
            ids.append(book_id)
            titles.append(t)
            authors.append(a)
            vectors.append(vec)
        
        conn.close()
        
        if not vectors: return "", []
        
        matrix = np.array(vectors)
        q_norm = query_vec / np.linalg.norm(query_vec)
        m_norms = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
        scores = np.dot(m_norms, q_norm)
        
        top_indices = np.argsort(scores)[::-1][:limit]
        
        rec_text = r"\n\section*{Recommended Reading}\n\begin{itemize}\n"
        rec_data = []
        
        for idx in top_indices:
            score = float(scores[idx])
            if score < 0.4: continue # Nur gute Matches (User Wunsch)
            
            rec_text += fr"  \item \textbf{{{titles[idx]}}} by {authors[idx]} (Match: {score:.2f})\n"
            rec_data.append({
                'id': ids[idx],
                'title': titles[idx],
                'author': authors[idx],
                'score': score
            })
            
        rec_text += r"\end{itemize}\n"
        return rec_text, rec_data
        
    except Exception as e:
        print(f"  ❌ DB Fehler: {e}")
        return "", []

def compile_pdf(tex_path):
    """Kompiliert LaTeX zu PDF."""
    work_dir = os.path.dirname(tex_path)
    filename = os.path.basename(tex_path)
    try:
        cmd = ['pdflatex', '-interaction=nonstopmode', filename]
        print(f"  -> Kompiliere PDF für {filename}...")
        subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
        return os.path.exists(tex_path.replace('.tex', '.pdf'))
    except Exception:
        return False

def process_files():
    service = get_drive_service()
    if not service: return
    
    root_id = find_or_create_folder(service, "MathNotes")
    input_id = find_or_create_folder(service, "Input", root_id)
    processed_id = find_or_create_folder(service, "Processed", root_id)
    
    print(f"🚀 MathStudio Monitor gestartet.")
    print(f"📂 Watch Folder: MathNotes/Input (ID: {input_id})")
    print(f"📂 Obsidian Inbox: {OBSIDIAN_INBOX}")
    
    while True:
        try:
            results = service.files().list(
                q=f"'{input_id}' in parents and trashed = false",
                fields="files(id, name, mimeType)"
            ).execute()
            files = results.get('files', [])
            
            for f in files:
                filename = f['name']
                file_id = f['id']
                mime_type = f['mimeType']
                
                if not mime_type.startswith('image/'):
                    continue
                
                print(f"\n🔄 Verarbeite: {filename}...")
                
                # 1. Download
                request = service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                
                image_data = fh.getvalue()
                
                # 2. KI Analyse (Inkl. Skalierung)
                content_data = get_gemini_content(image_data, mime_type)
                
                if content_data:
                    latex_content = content_data.get('latex_source', '')
                    markdown_content = content_data.get('markdown_source', '')
                    title = content_data.get('title', 'Untitled Note')
                    
                    # 3. Empfehlungen
                    print("  🔍 Suche passende Bücher...")
                    recs_latex, recs_data = get_recommendations(latex_content)
                    
                    # Markdown Builder
                    recs_md = "\n## Recommended Reading\n"
                    for item in recs_data:
                         recs_md += f"- **{item['title']}** by {item['author']} (Match: {item['score']:.2f})\n"
                    
                    full_markdown = markdown_content + "\n" + recs_md
                    
                    # LaTeX Builder
                    full_latex = latex_content
                    if r"\documentclass" not in latex_content:
                        full_latex = (
                            r"\documentclass{article}" + "\n"
                            r"\usepackage[utf8]{inputenc}" + "\n"
                            r"\usepackage{amsmath, amssymb, amsfonts}" + "\n"
                            r"\begin{document}" + "\n"
                            f"\\title{{{title}}}\n\\maketitle\n"
                            f"{latex_content}\n"
                            f"{recs_latex}\n"
                            r"\end{document}"
                        )
                    else:
                        if r"\end{document}" in latex_content:
                            full_latex = latex_content.replace(r"\end{document}", f"{recs_latex}\n" + r"\end{document}")
                        else:
                            full_latex = latex_content + "\n" + recs_latex

                    # 4. Generate intelligent filename
                    # Extract title and create meaningful filename
                    title = content_data.get('title', 'Untitled Note')
                    
                    # Create base name from title
                    # Remove common prefixes and clean up
                    title_clean = title.replace('Note:', '').replace('Math Note:', '').strip()
                    
                    # Truncate to first 5 words for reasonable length
                    words = title_clean.split()[:5]
                    title_short = '_'.join(words)
                    
                    # Sanitize for filesystem
                    safe_title = "".join([c for c in title_short if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
                    safe_title = safe_title.replace(' ', '_')
                    
                    # Add timestamp for uniqueness
                    timestamp = time.strftime("%Y-%m-%d_%H%M")
                    
                    # Fallback to original filename if title extraction fails
                    if not safe_title or len(safe_title) < 3:
                        base_name = os.path.splitext(filename)[0]
                        safe_title = "".join([c for c in base_name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
                        if not safe_title:
                            safe_title = "note"
                    
                    safe_name = f"{safe_title}_{timestamp}"

                    local_tex_path = os.path.join(LOCAL_OUTPUT_DIR, safe_name + ".tex")
                    local_md_path = os.path.join(LOCAL_OUTPUT_DIR, safe_name + ".md")
                    local_json_path = os.path.join(LOCAL_OUTPUT_DIR, safe_name + ".json")
                    
                    with open(local_tex_path, "w", encoding="utf-8") as f: f.write(full_latex)
                    with open(local_md_path, "w", encoding="utf-8") as f: f.write(full_markdown)
                    
                    # Save metadata
                    metadata = {
                        'original_filename': filename,
                        'title': title,
                        'created': timestamp,
                        'tags': content_data.get('tags', []),
                        'recommendations': recs_data
                    }
                    with open(local_json_path, "w", encoding="utf-8") as f:
                        json.dump(metadata, f, indent=2)
                    
                    print(f"  ✅ Gespeichert: {safe_name}.md / .tex / .json")

                    # 5. Obsidian Export
                    if os.path.exists(OBSIDIAN_INBOX):
                        try:
                            vault_path = os.path.join(OBSIDIAN_INBOX, safe_name + ".md")
                            shutil.copy2(local_md_path, vault_path)
                            print(f"  ➡️ Exportiert nach Obsidian: {safe_name}.md")
                        except Exception as e:
                            print(f"  ⚠️ Obsidian Copy Fehler: {e}")

                    # 6. PDF & Move
                    compile_pdf(local_tex_path)
                    
                    try:
                        file = service.files().get(fileId=file_id, fields='parents').execute()
                        previous_parents = ",".join(file.get('parents'))
                        service.files().update(
                            fileId=file_id,
                            removeParents=previous_parents,
                            addParents=processed_id,
                            fields='id, parents'
                        ).execute()
                        print(f"  📦 Verschoben nach 'Processed'.")
                    except Exception as e:
                        print(f"  ⚠️ Verschiebe-Fehler: {e}")

                else:
                    print("  ❌ Konnte Inhalt nicht generieren.")

                # Erhöhtes Cool-down (15s statt 5s)
                print("  💤 Cool-down (15s)...")
                time.sleep(15)

        except Exception as e:
            print(f"Loop Fehler: {e}")
            
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    process_files()