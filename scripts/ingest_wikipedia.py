import sys
import os
import re
import time
import argparse
import requests
import sqlite3
from bs4 import BeautifulSoup
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai import ai
from core.database import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ingest_wiki")

def ingest_glossary(url: str, subject_area: str, msc_code: str = ""):
    logger.info(f"Fetching glossary from {url}")
    
    headers = {
        'User-Agent': 'MathStudio Knowledge Base Ingester Bot (contact: admin@mathstudio.local)'
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to fetch {url}. Status: {response.status_code}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    content_div = soup.find(id='bodyContent')
    
    if not content_div:
        logger.error("Could not find bodyContent div.")
        return
        
    # Remove script, style, and annoying tables/navboxes
    for tag in content_div(['script', 'style', 'table', 'nav']):
        tag.decompose()
        
    raw_text = content_div.get_text(separator='\n\n', strip=True)
    
    # Clean up massive whitespace gaps
    raw_text = re.sub(r'\n{3,}', '\n\n', raw_text)
    
    # We will chunk this up and feed it to the AI to extract structured entities
    # This prevents the AI from hitting output token limits on massive glossaries
    chunk_size = 8000
    chunks = [raw_text[i:i + chunk_size] for i in range(0, len(raw_text), chunk_size)]
    
    logger.info(f"Extracted {len(raw_text)} characters. Split into {len(chunks)} chunks for AI parsing.")
    
    # Force Gemini for this because it has huge context windows and is very fast at text extraction
    ai.routing_policy = "gemini_only"
    
    total_saved = 0
    
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i+1}/{len(chunks)}...")
        
        prompt = (
            f"You are a mathematical knowledge extraction engine.\n"
            f"Extract all mathematical definitions, theorems, and concepts from the following text (which is a raw scrape of a Wikipedia Glossary about {subject_area}).\n"
            "=== RULES ===\n"
            "1. Ignore navigation links, 'See also', Edit buttons, or reference numbers like [1].\n"
            "2. Ensure the summary makes sense out of context.\n"
            "3. Return the result strictly as a list of XML blocks in this EXACT format:\n"
            "<concept>\n"
            "  <name>The Term Here</name>\n"
            "  <summary>A concise 1-2 sentence definition.</summary>\n"
            "</concept>\n\n"
            "=== RAW TEXT CHUNK ===\n"
            f"{chunk}"
        )
        
        try:
            blocks = ai.generate_xml_blocks(prompt, "concept")
            
            if not blocks:
                logger.warning(f"No concepts found in chunk {i+1}.")
                continue
                
            with db.get_connection() as conn:
                cursor = conn.cursor()
                chunk_saved = 0
                for block in blocks:
                    name_match = re.search(r'<name>(.*?)</name>', block, re.DOTALL)
                    summary_match = re.search(r'<summary>(.*?)</summary>', block, re.DOTALL)
                    
                    if name_match and summary_match:
                        name = name_match.group(1).strip()
                        summary = summary_match.group(1).strip()
                        
                        # Remove citation brackets from summary if any leaked through e.g. [1]
                        summary = re.sub(r'\[\d+\]', '', summary)
                        
                        if len(name) > 1 and len(summary) > 5:
                            try:
                                cursor.execute('''
                                    INSERT INTO mathematical_concepts 
                                    (name, subject_area, msc_code, source, source_url, summary)
                                    VALUES (?, ?, ?, 'wikipedia', ?, ?)
                                ''', (name, subject_area, msc_code, url, summary))
                                chunk_saved += 1
                            except sqlite3.IntegrityError:
                                # Duplicate (name, subject) combination
                                pass
                conn.commit()
                total_saved += chunk_saved
                logger.info(f"Saved {chunk_saved} unique concepts from chunk {i+1}.")
                
        except Exception as e:
            logger.error(f"Error processing chunk {i+1}: {e}")
            
        time.sleep(6) # Soft rate limit
        
    logger.info(f"--- Ingestion Complete ---\nSuccessfully added {total_saved} unique concepts for {subject_area} to the base.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Wikipedia Glossaries into the Mathematical Brain")
    parser.add_argument("--url", type=str, required=True, help="URL of the Wikipedia glossary")
    parser.add_argument("--subject", type=str, required=True, help="Subject Area (e.g. Topology, Linear Algebra)")
    parser.add_argument("--msc", type=str, default="", help="Optional 2-digit MSC Code (e.g. 54)")
    
    args = parser.parse_args()
    ingest_glossary(args.url, args.subject, args.msc)
