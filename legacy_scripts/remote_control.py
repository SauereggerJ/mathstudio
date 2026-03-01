import pexpect
import sys

PASSWORD = "jussupow"
REMOTE_USER = "jure"
REMOTE_HOST = "192.168.178.2"
REMOTE_DIR = "/srv/data/math/New_Research_Library/mathstudio"

def run_remote_command(command):
    ssh_cmd = f"ssh {REMOTE_USER}@{REMOTE_HOST} \"{command}\""
    print(f"Executing: {command}")
    child = pexpect.spawn(ssh_cmd, timeout=600)
    
    try:
        i = child.expect(['password:', pexpect.EOF, pexpect.TIMEOUT])
        if i == 0:
            child.sendline(PASSWORD)
            child.expect(pexpect.EOF)
            return child.before.decode()
        else:
            return "Connection failed or timed out"
    except Exception as e:
        return str(e)

def restart_services():
    # 1. Sync files first (using deploy.sh logic but with pexpect)
    print("--- Syncing Files ---")
    # Sync ONLY mathstudio and _Admin, excluding database and heavy assets
    # We use --include to whitelist, and --exclude '*' to block everything else at root
    rsync_cmd = (
        f"rsync -avz "
        f"--include='/mathstudio/***' "
        f"--include='/_Admin/***' "
        f"--exclude='library.db' "
        f"--exclude='*.db' "
        f"--exclude='__pycache__' "
        f"--exclude='*.pyc' "
        f"--exclude='.git' "
        f"--exclude='.gemini' "
        f"--exclude='venv' "
        f"--exclude='mcp_server' "
        f"--exclude='*' "
        f"../ {REMOTE_USER}@{REMOTE_HOST}:/srv/data/math/New_Research_Library/"
    )
    child = pexpect.spawn(rsync_cmd, timeout=300)
    i = child.expect(['password:', pexpect.EOF, pexpect.TIMEOUT])
    if i == 0:
        child.sendline(PASSWORD)
        child.expect(pexpect.EOF)
        print("Sync done.")
    
    # 2. Restart Container and Background Processes
    print("--- Rebuilding and Restarting Services ---")
    commands = [
        f"cd {REMOTE_DIR}",
        "docker compose down",
        "docker compose up -d --force-recreate --build mathstudio",
        # Wait a bit for container to be ready
        "sleep 10",
        # Run DB Migration (Schema Update)
        "docker compose exec mathstudio python3 -c 'from indexer import setup_database; setup_database()'",
        # Start MathBot
        "docker compose exec -d mathstudio sh -c 'nohup python3 -u process_notes.py > process_notes_v2.log 2>&1 &'",
        # Start Vectorizer (nohup to keep it running)
        # We use --reset to clear old incompatible embeddings
        "docker compose exec -d mathstudio nohup python3 -u vectorize.py --limit 5000 --reset > vectorize.log 2>&1 &"
    ]
    
    result = run_remote_command(" && ".join(commands))
    print(result)

if __name__ == "__main__":
    restart_services()
