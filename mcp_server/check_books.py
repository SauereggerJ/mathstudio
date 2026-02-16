import asyncio
import sys
import os
import json
import re

# Ensure we can import mcp
sys.path.append(os.getcwd())

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BOOKS_TO_CHECK = [
    {"query": "Topics in Algebra Herstein", "expect_author": "Herstein", "expect_title": "Topics"},
    {"query": "Algebra Michael Artin", "expect_author": "Artin", "expect_title": "Algebra"},
    {"query": "Contemporary Abstract Algebra Gallian", "expect_author": "Gallian", "expect_title": "Contemporary"},
    {"query": "Abstract Algebra Dummit Foote", "expect_author": "Dummit", "expect_title": "Abstract"},
    
    {"query": "New Foundations for Classical Mechanics Hestenes", "expect_author": "Hestenes", "expect_title": "Mechanics"},
    {"query": "Geometric Algebra for Physicists Doran", "expect_author": "Doran", "expect_title": "Physicists"},
    {"query": "Linear and Geometric Algebra McDonald", "expect_author": "McDonald", "expect_title": "Linear"},
    {"query": "Geometric Algebra for Computer Graphics Vince", "expect_author": "Vince", "expect_title": "Graphics"},
    {"query": "Clifford Algebra to Geometric Calculus Hestenes", "expect_author": "Hestenes", "expect_title": "Calculus"},
    
    {"query": "Algebraic Topology Hatcher", "expect_author": "Hatcher", "expect_title": "Topology"},
    {"query": "Basic Topology Armstrong", "expect_author": "Armstrong", "expect_title": "Basic"},
    {"query": "Topology Munkres", "expect_author": "Munkres", "expect_title": "Topology"},
    {"query": "An Introduction to Algebraic Topology Rotman", "expect_author": "Rotman", "expect_title": "Introduction"},
    {"query": "Topology and Geometry Bredon", "expect_author": "Bredon", "expect_title": "Geometry"},
    {"query": "Concise Course in Algebraic Topology May", "expect_author": "May", "expect_title": "Concise"}
]

async def check_books():
    server_params = StdioServerParameters(
        command="python3", 
        args=["server.py"],
        env=None
    )
    
    missing_books = []
    found_books = []

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                print("Checking library for recommendations (Strict Mode)...\n")
                
                for item in BOOKS_TO_CHECK:
                    query = item["query"]
                    expect_author = item["expect_author"].lower()
                    expect_title = item["expect_title"].lower()
                    
                    try:
                        # We use a limit of 1
                        result = await session.call_tool("search_books", {"query": query, "limit": 1})
                        
                        text_content = ""
                        for content in result.content:
                            if content.type == "text":
                                text_content += content.text
                        
                        # Parse result
                        # Format: "1. **Title** by Author"
                        match = re.search(r"1\.\s*\*\*(.*?)\*\*\s*by\s*(.*)", text_content)
                        
                        if match:
                            found_title = match.group(1).lower()
                            found_author = match.group(2).lower()
                            
                            # Check if matches expectations
                            if expect_author in found_author and expect_title in found_title:
                                print(f"[FOUND]   {query}")
                                print(f"          -> {match.group(0)}")
                                found_books.append(query)
                            else:
                                print(f"[MISSING] {query}")
                                print(f"          -> Best match was: {match.group(0)} (Does not match expected)")
                                missing_books.append(query)
                        else:
                            # "No results found" or unexpected format
                            print(f"[MISSING] {query} (No results or parse error)")
                            missing_books.append(query)
                            
                    except Exception as e:
                         print(f"[ERROR]   {query} -> {e}")
                         # Assume missing if error
                         missing_books.append(query)

                    await asyncio.sleep(0.5)

    except Exception as e:
        print(f"Global Error: {e}")
        return

    print("\n" + "="*40)
    print("SUMMARY")
    print("="*40)
    print(f"Total Checked: {len(BOOKS_TO_CHECK)}")
    print(f"Found: {len(found_books)}")
    print(f"Missing: {len(missing_books)}")
    print("\n--- Missing Books List ---")
    for book in missing_books:
        print(f"- {book}")

if __name__ == "__main__":
    asyncio.run(check_books())
