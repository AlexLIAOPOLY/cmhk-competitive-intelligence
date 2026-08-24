import asyncio
from agent import get_agent

def main():
    agent = get_agent()
    events = agent.stream({"messages": [("user", "帮我用飞书CLI查询一下默认表格的数据")]}, stream_mode="messages")
    for chunk, metadata in events:
        if hasattr(chunk, 'tool_call_chunks') and chunk.tool_call_chunks:
            for tc in chunk.tool_call_chunks:
                if tc.get("name"):
                    print("Tool call name found:", tc["name"])
        elif hasattr(chunk, 'name') and chunk.name:
            print("Tool finished:", chunk.name)

if __name__ == "__main__":
    main()
