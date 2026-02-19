import asyncio
import sys
import os
import json

# Ensure we can import mcp
sys.path.append(os.getcwd())

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run():
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("Usage: python client.py <command> [args...]")
        print("Commands:")
        print("  list-tools")
        print("  list-resources")
        print("  read-resource <uri>")
        print("  call-tool <tool_name> <json_args>")
        return

    command = sys.argv[1]

    # details of the server to run
    server_params = StdioServerParameters(
        command="python3", # use the same python as this script
        args=["server.py"],
        env=None
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                if command == "list-tools":
                    print("--- Listing Tools ---")
                    tools = await session.list_tools()
                    for tool in tools.tools:
                        print(f"Tool: {tool.name}")
                        print(f"  Description: {tool.description}")

                elif command == "list-resources":
                    print("\n--- Listing Resources ---")
                    resources = await session.list_resources()
                    for resource in resources.resources:
                        print(f"Resource: {resource.name} ({resource.uri})")

                elif command == "read-resource":
                    if len(sys.argv) < 3:
                        print("Error: Missing URI for read-resource")
                        return
                    uri = sys.argv[2]
                    print(f"\n--- Reading Resource: {uri} ---")
                    content = await session.read_resource(uri)
                    # content is a ReadResourceResult, having a 'contents' list
                    for item in content.contents:
                        print(item.text)

                elif command == "call-tool":
                    if len(sys.argv) < 4:
                        print("Error: Missing tool name or arguments")
                        print("Usage: python client.py call-tool <tool_name> '{\"arg\": \"value\"}'")
                        return
                    
                    tool_name = sys.argv[2]
                    try:
                        tool_args = json.loads(sys.argv[3])
                    except json.JSONDecodeError:
                        print("Error: Arguments must be valid JSON")
                        return
                    
                    print(f"\n--- Calling Tool: {tool_name} ---")
                    result = await session.call_tool(tool_name, tool_args)
                    for content in result.content:
                        if content.type == "text":
                            print(content.text)
                        else:
                            print(f"[{content.type} content]")

                else:
                    print(f"Unknown command: {command}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())

