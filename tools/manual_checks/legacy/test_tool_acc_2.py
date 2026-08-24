from agent import stream_agent
for event in stream_agent("帮我用feishu_cli运行 sheets +info"):
    if event["type"] == "delta":
        print(event["text"], end="")
