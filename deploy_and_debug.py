#!/usr/bin/env python3
"""
MathStudio Remote Management Tool
Refactored for better maintainability, logging, and performance.
"""

import os
import sys
import time
import argparse
import subprocess
import pexpect
import shutil
from datetime import datetime
from dataclasses import dataclass

# --- Configuration ---
@dataclass
class Config:
    REMOTE_USER: str = "jure"
    REMOTE_HOST: str = "192.168.178.2"
    REMOTE_BASE_DIR: str = "/srv/data/math/New_Research_Library"
    REMOTE_PROJECT_DIR: str = "/srv/data/math/New_Research_Library/mathstudio"
    PASSWORD: str = "jussupow"
    WEB_PORT: int = 5002
    CONTAINER_NAME: str = "mathstudio"

CONF = Config()

# --- Logging & Coloring ---
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    if level == "INFO":
        print(f"[{timestamp}] {Colors.OKBLUE}ℹ {msg}{Colors.ENDC}")
    elif level == "SUCCESS":
        print(f"[{timestamp}] {Colors.OKGREEN}✔ {msg}{Colors.ENDC}")
    elif level == "WARN":
        print(f"[{timestamp}] {Colors.WARNING}⚠ {msg}{Colors.ENDC}")
    elif level == "ERROR":
        print(f"[{timestamp}] {Colors.FAIL}✖ {msg}{Colors.ENDC}")
    elif level == "HEADER":
        print(f"\n{Colors.HEADER}{Colors.BOLD}=== {msg} ==={Colors.ENDC}")

# --- Remote Manager ---
class RemoteManager:
    def __init__(self, config: Config):
        self.cfg = config

    def _get_ssh_cmd(self, command):
        """Constructs the SSH command list for pexpect."""
        return ['ssh', f"{self.cfg.REMOTE_USER}@{self.cfg.REMOTE_HOST}", command]

    def run_command(self, command, print_output=True, timeout=30, stream=False):
        """Executes a remote command via SSH using pexpect."""
        if print_output and not stream:
            log(f"Executing remote: {command}...", "INFO")

        cmd_list = self._get_ssh_cmd(command)
        
        try:
            # If streaming (like logs), we pipe output directly to stdout
            if stream:
                # For interactive/streaming, we might need a different approach or just pexpect interact
                child = pexpect.spawn(cmd_list[0], cmd_list[1:], timeout=None, encoding='utf-8')
                child.logfile_read = sys.stdout
            else:
                child = pexpect.spawn(cmd_list[0], cmd_list[1:], timeout=timeout, encoding='utf-8')

            i = child.expect(['password:', pexpect.EOF, pexpect.TIMEOUT])
            
            if i == 0:
                child.sendline(self.cfg.PASSWORD)
                if stream:
                    child.interact() # Give control to user/stream
                    return ""
                child.expect(pexpect.EOF)
                output = child.before
            elif i == 1:
                output = child.before
            else:
                log("Timeout connecting to server.", "ERROR")
                return None

            # Clean output (remove password prompt if captured)
            output = output.replace(self.cfg.PASSWORD, "[HIDDEN]") if output else ""
            
            if print_output and not stream:
                print(output.strip())
                
            return output.strip()

        except Exception as e:
            log(f"SSH failed: {e}", "ERROR")
            return None

    def sync_files(self):
        """Rsyncs files to the remote server."""
        log("Syncing files via rsync...", "HEADER")
        exclude_flags = (
            "--exclude 'venv' --exclude '.venv' --exclude '__pycache__' --exclude '.git' "
            "--exclude '.gemini' --exclude 'credentials.json' "
            "--exclude 'library.db' --exclude 'archive' --exclude 'notes_output' "
            "--exclude 'mcp_server/config.json' --exclude 'mcp_config.json'"
        )
        # Assuming we are running from mathstudio/ directory, so ../ is the source
        source = "../" 
        dest = f"{self.cfg.REMOTE_USER}@{self.cfg.REMOTE_HOST}:{self.cfg.REMOTE_BASE_DIR}/"
        
        rsync_cmd = f"rsync -avz {exclude_flags} {source} {dest}"
        
        try:
            child = pexpect.spawn(rsync_cmd, timeout=300, encoding='utf-8')
            i = child.expect(['password:', pexpect.EOF, pexpect.TIMEOUT])
            if i == 0:
                child.sendline(self.cfg.PASSWORD)
                child.expect(pexpect.EOF)
            elif i == 2:
                 log("Rsync timed out.", "ERROR")
                 return False
            
            log("Sync complete.", "SUCCESS")
            return True
        except Exception as e:
            log(f"Rsync failed: {e}", "ERROR")
            return False

    def restart_docker(self):
        """Full Docker restart (build and up)."""
        log("Restarting Docker Container...", "HEADER")
        cmd = (
            f"cd {self.cfg.REMOTE_PROJECT_DIR} && "
            f"docker compose up -d --force-recreate --build {self.cfg.CONTAINER_NAME}"
        )
        self.run_command(cmd, timeout=300)

    def restart_python_process(self):
        """Restarts the background python worker without killing container."""
        log("Restarting background worker...", "INFO")
        # We kill the old process and start new one
        kill_cmd = f"cd {self.cfg.REMOTE_PROJECT_DIR} && docker compose exec {self.cfg.CONTAINER_NAME} pkill -f process_notes.py || true"
        self.run_command(kill_cmd, print_output=False)
        
        start_services_cmd = (
            f"cd {self.cfg.REMOTE_PROJECT_DIR} && "
            f"docker compose exec -d {self.cfg.CONTAINER_NAME} sh -c 'nohup python3 -u process_notes.py > process_notes.log 2>&1 &' && "
            f"docker compose exec -d {self.cfg.CONTAINER_NAME} nohup python3 -u vectorize.py --limit 5000 --reset > vectorize.log 2>&1 &"
        )
        self.run_command(start_services_cmd)
        log("Background worker restarted.", "SUCCESS")

    def full_deploy(self):
        """Full deployment pipeline."""
        if self.sync_files():
            self.restart_docker()
            # Wait a bit for container to stay up
            time.sleep(5) 
            self.restart_python_process() # This actually starts them, restart_docker doesn't auto-start these custom bg tasks usually?
            # Actually original script ran start commands after docker up.
            # Docker compose up starts the container, but process_notes.py is separate? 
            # Original: run_remote_command(" && ".join(start_cmds))
            # My restart_python_process does exactly that.
            self.check_health()

    def quick_deploy(self):
        """Quick deployment (Sync + Process Restart)."""
        if self.sync_files():
             self.restart_python_process()
             log("Quick deploy finished. Container was NOT rebuilt.", "SUCCESS")

    def stream_logs(self):
        """Streams logs like tail -f."""
        log("Streaming process_notes.log (Ctrl+C to stop)...", "HEADER")
        cmd = f"cd {self.cfg.REMOTE_PROJECT_DIR} && docker exec {self.cfg.CONTAINER_NAME} tail -f process_notes.log"
        try:
            self.run_command(cmd, stream=True)
        except KeyboardInterrupt:
            print("\nStopped.")

    def open_shell(self):
        """Opens a remote shell inside the container."""
        log("Opening remote shell...", "HEADER")
        cmd = f"ssh -t {self.cfg.REMOTE_USER}@{self.cfg.REMOTE_HOST} 'cd {self.cfg.REMOTE_PROJECT_DIR} && docker compose exec {self.cfg.CONTAINER_NAME} bash'"
        # We use subprocess for this interactive shell as pexpect is tricky with full TTY
        # But we need password. 
        # Actually, let's try pexpect interact, or warn user they might need key.
        # Original script didn't have this.
        # Let's try standard pexpect interact
        
        ssh_cmd = f"ssh -t {self.cfg.REMOTE_USER}@{self.cfg.REMOTE_HOST} \"cd {self.cfg.REMOTE_PROJECT_DIR} && docker compose exec {self.cfg.CONTAINER_NAME} bash\""
        child = pexpect.spawn(ssh_cmd)
        child.expect(['password:', pexpect.EOF, pexpect.TIMEOUT])
        child.sendline(self.cfg.PASSWORD)
        child.interact()

    def check_health(self):
        """Performs health checks."""
        log("System Health Check", "HEADER")
        
        # 1. Web
        try:
            res = subprocess.run(
                ["curl", "-I", f"http://{self.cfg.REMOTE_HOST}:{self.cfg.WEB_PORT}"], 
                capture_output=True, text=True, timeout=5
            )
            if "200 OK" in res.stdout or "200" in res.stdout:
                log("Web Interface: UP", "SUCCESS")
            else:
                log(f"Web Interface: DOWN (Response: {res.stdout.splitlines()[0] if res.stdout else 'None'})", "ERROR")
        except:
             log("Web Interface: DOWN (Connection Failed)", "ERROR")

        # 2. Process
        ps_cmd = f"docker exec {self.cfg.CONTAINER_NAME} ps aux | grep process_notes.py | grep -v grep"
        out = self.run_command(f"cd {self.cfg.REMOTE_PROJECT_DIR} && {ps_cmd}", print_output=False)
        if out:
            log("Background Worker: RUNNING", "SUCCESS")
        else:
            log("Background Worker: STOPPED", "FAIL")

# --- CLI & Menu ---
def run_menu(manager: RemoteManager):
    actions = {
        '1': ("Deploy & Restart (Full)", manager.full_deploy),
        '2': ("Quick Deploy (Sync + Restart Py)", manager.quick_deploy),
        '3': ("Check Health", manager.check_health),
        '4': ("Stream Logs", manager.stream_logs),
        '5': ("Shell Access", manager.open_shell),
        'q': ("Exit", sys.exit)
    }
    
    while True:
        log("Remote Management Menu", "HEADER")
        for k, v in actions.items():
            print(f" {Colors.BOLD}{k}{Colors.ENDC}. {v[0]}")
        
        choice = input(f"\n{Colors.OKCYAN}Select option: {Colors.ENDC}").strip().lower()
        
        if choice in actions:
            if choice == 'q':
                sys.exit(0)
            actions[choice][1]()
            input(f"\nPress Enter to continue...")
        else:
            log("Invalid option", "WARN")

def main():
    parser = argparse.ArgumentParser(description="MathStudio Remote Manager")
    parser.add_argument('--deploy', action='store_true', help="Run full deployment")
    parser.add_argument('--quick', action='store_true', help="Run quick deployment (no docker build)")
    parser.add_argument('--logs', action='store_true', help="Stream logs")
    parser.add_argument('--health', action='store_true', help="Check system health")
    parser.add_argument('--shell', action='store_true', help="Open remote shell")
    
    # Original args support
    parser.add_argument('--ingest', action='store_true', help="Run ingestion API")
    parser.add_argument('--check-sanity', action='store_true', help="Run sanity check")
    
    args = parser.parse_args()
    manager = RemoteManager(CONF)

    if args.deploy:
        manager.full_deploy()
    elif args.quick:
        manager.quick_deploy()
    elif args.logs:
        manager.stream_logs()
    elif args.health:
        manager.check_health()
    elif args.shell:
        manager.open_shell()
    # Support for legacy args (keeping minimal implementation for now or redirecting to new methods if applicable)
    elif args.check_sanity:
        manager.run_command(f"cd {CONF.REMOTE_PROJECT_DIR} && docker compose exec {CONF.CONTAINER_NAME} python3 db_sanity.py")
    elif args.ingest:
         json_payload = '{"dry_run": false}'
         cmd = f"cd {CONF.REMOTE_PROJECT_DIR} && printf '%s' '{json_payload}' > debug.json && cat debug.json | docker compose exec -T {CONF.CONTAINER_NAME} curl -X POST -H 'Content-Type: application/json' -d @- http://localhost:5002/api/v1/admin/ingest"
         manager.run_command(cmd)
    else:
        run_menu(manager)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
