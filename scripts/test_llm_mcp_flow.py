#!/usr/bin/env python3
import subprocess
import time
import sys

PROMPT = 'Research "Lebesgue Integration" across multiple books. Find at least 2 different definitions and list some related exercises. Then draft a short summary and publish it.'

def send_prompt(prompt):
    print(f"Sending prompt to tmux: {prompt}")
    # Escape single quotes and send
    escaped_prompt = prompt.replace("'", "'\\''")
    subprocess.run(["tmux", "send-keys", "-t", "gemini-chat", escaped_prompt, "Enter"], check=True)

def monitor_output(duration_sec=180, interval_sec=15):
    print(f"Monitoring for {duration_sec} seconds...")
    start_time = time.time()
    last_content = ""
    
    while time.time() - start_time < duration_sec:
        time.sleep(interval_sec)
        result = subprocess.run(["tmux", "capture-pane", "-t", "gemini-chat", "-p"], capture_output=True, text=True)
        content = result.stdout
        
        # Look for signs of activity
        if "Calling tool" in content or "Result from tool" in content or "Draft" in content:
            print(f"[{int(time.time() - start_time)}s] Activity detected...")
        
        # Check if we returned to prompt
        if ">   Type your message" in content and (time.time() - start_time > 30):
            print("Detected prompt. Gemini might be finished.")
            print("--- FINAL OUTPUT ---")
            print(content[-2000:]) # Last 2000 chars
            return True
            
        if content == last_content:
            print(f"[{int(time.time() - start_time)}s] No change...")
        else:
            print(f"[{int(time.time() - start_time)}s] Content updated.")
            last_content = content
            
    print("Timeout reached.")
    return False

if __name__ == "__main__":
    send_prompt(PROMPT)
    monitor_output()
