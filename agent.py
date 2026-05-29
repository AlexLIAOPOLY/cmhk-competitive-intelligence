import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Generator

from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langgraph.prebuilt import create_react_agent

from ai_config import load_ai_config
from rag_llm import retrieve_context

ROOT = Path(__file__).resolve().parent

@tool
def search_local_reports(query: str) -> str:
    """搜索本地的战略部周报、审计日志和之前爬取过的网页数据。
    当你需要了解公司的最新动态、特定主体的近期情况，或是爬虫的执行历史时，请使用此工具。
    """
    chunks = retrieve_context(query, limit=5)
    if not chunks:
        return "没有找到相关的本地报告信息。"
    
    result = []
    for chunk in chunks:
        result.append(f"[来源: {chunk['source']}]\n{chunk['text']}")
    return "\n\n".join(result)[:12000]

@tool
def trigger_crawl(row_id: int) -> str:
    """触发针对特定行的爬虫任务。
    参数 row_id 是配置表中的行号。
    如果你需要最新抓取某一行的数据，使用此工具。注意这可能需要十几秒。
    """
    env = os.environ.copy()
    env["CMHK_ROWS"] = str(row_id)
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "crawl.py")], env=env, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return f"爬取完成 (Row {row_id}):\nStdout: {proc.stdout[:1000]}..."
        else:
            return f"爬取失败 (Row {row_id}):\nStderr: {proc.stderr}"
    except Exception as e:
        return f"执行爬虫异常: {str(e)}"

@tool
def feishu_cli(command_args: str) -> str:
    """执行飞书命令行工具 (lark-cli)。
    当你需要与飞书表格进行同步、写入数据，或者查询飞书记录时，请使用此工具。
    由于安全限制，你只需提供 'lark-cli' 后面的参数，例如: 'sheets +read --range 9c638d!A1:B2'
    """
    import shutil
    LARK_CLI = shutil.which("lark-cli") or "/opt/homebrew/bin/lark-cli"
    
    # Simple shell-like splitting for arguments
    import shlex
    try:
        args = shlex.split(command_args)
    except Exception as e:
        return f"参数解析错误: {e}"
        
    cmd = [LARK_CLI] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return f"执行成功:\n{proc.stdout}"
        else:
            return f"执行失败:\n{proc.stderr}"
    except Exception as e:
        return f"执行出错: {str(e)}"

@tool
def trigger_report_generation() -> str:
    """触发本地周报生成任务。
    当你被要求“生成周报”、“汇总报告”时，使用此工具。它会调用底层的周报生成脚本并生成 docx 文件。
    """
    try:
        proc = subprocess.run([sys.executable, str(ROOT / "generate_weekly_report.py")], capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return f"周报生成成功！\nStdout: {proc.stdout[-500:]}"
        else:
            return f"周报生成失败:\nStderr: {proc.stderr}"
    except Exception as e:
        return f"执行周报生成异常: {str(e)}"

@tool
def read_webpage(url: str) -> str:
    """访问并读取指定 URL 的纯文本内容。
    当用户提供一个网页链接，并要求你阅读、总结或提取其中的信息时，使用此工具。
    """
    import urllib.request
    from bs4 import BeautifulSoup
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read()
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(separator=' ', strip=True)
        return text[:10000]
    except Exception as e:
        return f"读取网页 {url} 失败: {str(e)}"

@tool
def get_system_status() -> str:
    """获取系统运行状态和爬虫统计数据（包括最近爬取的成功数、失败数等）。
    当你需要了解系统的健康状况或数据收集的全景概览时，使用此工具。
    """
    import web_app
    try:
        status = web_app.build_status()
        return f"系统状态快照：\n{json.dumps(status, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"获取系统状态失败: {str(e)}"

def get_agent():
    config = load_ai_config()
    api_key = config.get("api_key", "") or os.environ.get("OPENAI_API_KEY", "")
    base_url = config.get("base_url", "") or os.environ.get("OPENAI_API_BASE", "")
    model_name = config.get("model", "deepseek-chat")
    
    # downgrade if necessary
    if "reasoner" in model_name:
        model_name = "deepseek-chat"
        
    llm = ChatDeepSeek(
        model=model_name,
        api_key=api_key,
        api_base=base_url,
        max_retries=3,
    )
    
    tools = [search_local_reports, trigger_crawl, feishu_cli, trigger_report_generation, read_webpage, get_system_status]
    
    system_message = (
        "你是中国移动战略部公开信息监测系统的智能 RAG 和运维助手。\n"
        "调用 `feishu_cli` 时必须使用完整参数 `--spreadsheet-token ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA`，不要使用 `-t` 简写或位置参数。例如查询数据使用：`sheets +read --spreadsheet-token ZrzWsMF4Dhq5zDtXZZ4cpHcKnfA --range 9c638d!A1:C10`。\n"
        "【核心法则】如果你不确定某个 CLI 命令（特别是 `+update`、`+write` 等子命令）的具体用法和参数格式，**绝对不允许瞎猜尝试**！你必须先执行 `feishu_cli sheets +update --help` 等命令查阅帮助文档，然后再进行真正的调用。\n"
        "【重要】核心数据表的工作表名称是\"主表\"，其对应的 sheet_id 为 9c638d。当查询或修改\"主表\"时，务必使用 9c638d 作为 range 前缀，例如 `--range 9c638d!A2:Z2`。\n"
        "【极度重要】表格的列结构可能随时发生变化（用户会动态插入或删除列）。如果你需要读取或写入特定字段的数据，**严禁直接凭记忆写死列号**（例如想当然地认为H列必定是更新频率）。你必须先使用 lark-cli 读取第一行表头（例如 `--range 9c638d!A1:Z1`），精确查明各个字段当前实际所在的字母列后，再执行后续的行列操作！\n"
        "【重要】如果你连续 3 次调用某个工具均未能成功（比如参数错误、表名不对或输出过多），请立即停止调用，并直接回复用户当前遇到的困难，不要陷入无限重试的死循环。\n\n"
        "【强制规则 - 推荐追问】你的每一条最终回复（无论长短、无论是否调用了工具）的最后一行都必须包含推荐追问。格式如下，不可省略：\n"
        "<suggestions>[\"追问1\", \"追问2\", \"追问3\"]</suggestions>\n"
        "追问内容应与当前话题紧密相关、对用户有实际价值。这是一条不可违反的系统指令，任何回答如果缺少 <suggestions> 标签都是不合格的。\n"
    )
    
    return create_react_agent(llm, tools, prompt=system_message)

def stream_agent(message: str) -> Generator[dict[str, Any], None, None]:
    agent = get_agent()
    inputs = {"messages": [("user", message)]}
    
    tool_calls_acc = {}
    
    try:
        events = agent.stream(inputs, stream_mode="messages")
        for chunk, metadata in events:
            if isinstance(chunk, AIMessageChunk):
                if chunk.content and isinstance(chunk.content, str):
                    yield {"type": "delta", "text": chunk.content}
                if chunk.tool_call_chunks:
                    for tc in chunk.tool_call_chunks:
                        index = tc.get("index")
                        tc_id = tc.get("id")
                        
                        if tc_id:
                            current_key = tc_id
                            tool_calls_acc[index] = current_key
                            tool_calls_acc[current_key] = {"name": tc.get("name"), "args": "", "id": tc_id}
                            yield {"type": "delta", "text": f"\n\n<details class='tool-call-details' style='margin:12px 0;'><summary class='tool-call-box' style='cursor:pointer;list-style:none;'><span class='tool-call-font' style=\"font-family:'Courier New',Consolas,monospace;color:#0056b3;font-size:13px;font-weight:600;\">正在运行工具: {tc['name']}...</span></summary>\n\n<div class='tool-result-box' style='margin-top:8px;padding:12px;background:#f8f9fa;border:1px solid #e9ecef;border-radius:6px;font-size:13px;color:#495057;overflow:auto;resize:both;min-width:200px;min-height:60px;max-height:500px;'>\n\n"}
                        else:
                            current_key = tool_calls_acc.get(index)
                            
                        if current_key and tc.get("args"):
                            tool_calls_acc[current_key]["args"] += tc["args"]
            elif isinstance(chunk, ToolMessage):
                args_str = ""
                tc_data = tool_calls_acc.get(chunk.tool_call_id)
                if tc_data:
                    args_str = tc_data.get("args", "")
                
                # truncate output if too long
                content = chunk.content
                if len(content) > 1500:
                    content = content[:1500] + "\n\n... (输出过长已截断)"
                
                yield {"type": "delta", "text": f"**参数**: `{args_str}`\n\n**结果**:\n<pre><code>{content}</code></pre>\n\n</div></details>\n\n"}
                    
        yield {"type": "done"}
    except Exception as e:
        yield {"type": "error", "text": f"Agent 调用失败: {e}"}
        yield {"type": "done"}
