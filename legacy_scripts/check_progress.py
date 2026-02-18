import pexpect
import sys
import re

PASSWORD = "jussupow"
REMOTE_USER = "jure"
REMOTE_HOST = "192.168.178.2"

def run_check():
    python_code = "import sqlite3; conn = sqlite3.connect('library.db'); c = conn.cursor(); c.execute('SELECT count(*) FROM books WHERE embedding IS NOT NULL'); print(c.fetchone()[0]); conn.close()"
    
    # Constructing the command carefully
    cmd = 'ssh ' + REMOTE_USER + '@' + REMOTE_HOST + ' "docker exec mathstudio python3 -c \"' + python_code + '\""'
    
    child = pexpect.spawn(cmd, timeout=30)
    try:
        i = child.expect(['password:', pexpect.EOF, pexpect.TIMEOUT])
        if i == 0:
            child.sendline(PASSWORD)
            child.expect(pexpect.EOF)
            output = child.before.decode().strip()
            
            # Find the last line that contains only digits
            lines = output.splitlines()
            result = None
            for line in reversed(lines):
                clean_line = line.strip()
                if clean_line.isdigit():
                    result = clean_line
                    break
            
            if result:
                print(result)
            else:
                print("Output was: " + output)
        else:
            print("Connection failed or timed out")
    except Exception as e:
        print("Error: " + str(e))

if __name__ == "__main__":
    run_check()
