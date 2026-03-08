#!/usr/bin/env python3
import json
import subprocess
import time
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
MCP_SERVER_PY = PROJECT_ROOT / "mcp_server" / "server.py"
VENV_PYTHON = PROJECT_ROOT / "mcp_server" / "venv" / "bin" / "python3"

class MCPClient:
    def __init__(self):
        self.proc = subprocess.Popen(
            [str(VENV_PYTHON), str(MCP_SERVER_PY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.msg_id = 1
        self._handshake()

    def _handshake(self):
        # 1. Initialize
        resp = self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        })
        # 2. Initialized notification
        self.send_notification("notifications/initialized")

    def send_request(self, method, params=None):
        req = {
            "jsonrpc": "2.0",
            "id": self.msg_id,
            "method": method,
            "params": params or {}
        }
        self.msg_id += 1
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        
        while True:
            line = self.proc.stdout.readline()
            if not line:
                break
            try:
                resp = json.loads(line)
                # Ignore notifications in this simple client
                if "id" in resp:
                    return resp
            except json.JSONDecodeError:
                continue
        return None

    def send_notification(self, method, params=None):
        req = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()

    def call_tool(self, name, args):
        return self.send_request("tools/call", {"name": name, "arguments": args})

    def close(self):
        self.proc.terminate()

def run_tests():
    client = MCPClient()
    print("--- Starting MCP Tool Validation ---")
    
    test_cases = [
        ("search_books", {"query": "Stein Shakarchi"}),
        ("search_kb", {"query": "Mean Value Theorem", "kind": "theorem"}),
        ("search_concepts", {"query": "Integration"}),
        ("get_book_details", {"book_id": 353}),
        ("search_notes", {"query": "test"}),
    ]

    for tool, args in test_cases:
        print(f"\n[Test] {tool}({args})")
        resp = client.call_tool(tool, args)
        if resp and "result" in resp:
            print("✓ Success")
            # print(json.dumps(resp["result"], indent=2))
        else:
            print(f"✗ Failed: {resp.get('error') if resp else 'No response'}")

    print("\n--- Verifying Drafting Workflow ---")
    client.call_tool("start_research_draft", {"title": "Test Suite Report"})
    client.call_tool("append_to_draft", {"content": "This is a test section."})
    resp = client.call_tool("publish_research_report", {})
    if resp and "result" in resp:
        print("✓ Draft Cycle Successful")
    else:
        print("✗ Draft Cycle Failed")

    client.close()

if __name__ == "__main__":
    run_tests()
