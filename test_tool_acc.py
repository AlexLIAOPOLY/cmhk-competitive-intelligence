import asyncio
from agent import get_agent
from langchain_core.messages import AIMessageChunk, ToolMessage

def main():
    agent = get_agent()
    events = agent.stream({"messages": [("user", "帮我用feishu_cli运行 sheets +info")]}, stream_mode="messages")
    
    tool_calls_acc = {}
    
    for chunk, metadata in events:
        if isinstance(chunk, AIMessageChunk):
            if chunk.tool_call_chunks:
                for tc in chunk.tool_call_chunks:
                    index = tc.get("index")
                    if index not in tool_calls_acc:
                        tool_calls_acc[index] = {"name": tc.get("name"), "args": ""}
                    if tc.get("args"):
                        tool_calls_acc[index]["args"] += tc.get("args")
        elif isinstance(chunk, ToolMessage):
            # Let's find the matching tool call by ID or just assume order
            print(f"Tool {chunk.name} finished! Accumulated args: {tool_calls_acc}")

if __name__ == "__main__":
    main()
