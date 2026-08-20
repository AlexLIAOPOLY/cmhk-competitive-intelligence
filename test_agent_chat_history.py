import json
import tempfile
import unittest
from pathlib import Path

import agent


class AgentChatHistoryTests(unittest.TestCase):
    def test_skill_routing_skips_history_lookup(self) -> None:
        instruction = agent._skill_routing_instruction(
            "请搜索历史聊天记录：前台发送测试 09 对应的回复是什么？",
            ["quarterly-competitor-metrics", "macro-policy-context"],
            [],
        )

        self.assertIn("不要为了流程感读取 Skill", instruction)
        self.assertNotIn("优先调用 `read_agent_skill`", instruction)

    def test_skill_routing_recommends_relevant_analysis_skills(self) -> None:
        instruction = agent._skill_routing_instruction(
            "分析香港5G监管政策对CMHK未来收入趋势的影响，并给出风险建议。",
            ["macro-policy-context", "trend-forecasting", "executive-briefing"],
            [],
        )

        self.assertIn("优先调用 `read_agent_skill`", instruction)
        self.assertIn("macro-policy-context", instruction)
        self.assertIn("trend-forecasting", instruction)

    def test_chat_history_search_returns_neighboring_context(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            original_path = agent.CHAT_THREADS_PATH
            try:
                path = Path(tempdir) / "threads.json"
                path.write_text(
                    json.dumps(
                        {
                            "threads": [
                                {
                                    "id": "thread-a",
                                    "title": "长期记忆条目统计",
                                    "updatedAt": "2026-06-23T17:20:24",
                                    "messages": [
                                        {"role": "user", "content": "前台发送测试 09：只回复 OK-09，不要调用工具。"},
                                        {"role": "assistant", "content": "OK-09"},
                                    ],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                agent.CHAT_THREADS_PATH = path

                rows = agent._chat_history_rows("前台发送测试 09 对应的回复是什么", limit=1)

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["message_index"], 1)
                context = rows[0]["context_messages"]
                self.assertEqual([item["message_index"] for item in context], [1, 2])
                self.assertEqual(context[1]["role"], "assistant")
                self.assertEqual(context[1]["content"], "OK-09")
            finally:
                agent.CHAT_THREADS_PATH = original_path

    def test_chat_history_tool_renders_context_window(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            original_path = agent.CHAT_THREADS_PATH
            try:
                path = Path(tempdir) / "threads.json"
                path.write_text(
                    json.dumps(
                        [
                            {
                                "id": "thread-b",
                                "title": "历史上下文补充",
                                "updatedAt": "2026-06-23T18:00:00",
                                "messages": [
                                    {"role": "user", "content": "历史口令是 BLUE-731。"},
                                    {"role": "assistant", "content": "收到，历史口令 BLUE-731。"},
                                    {"role": "user", "content": "之后报告默认署名是谁？"},
                                    {"role": "assistant", "content": "默认署名是策略雷达。"},
                                ],
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                agent.CHAT_THREADS_PATH = path

                result = agent.search_chat_history.invoke({"query": "历史口令 BLUE-731", "limit": 1})

                self.assertIn("邻近对话上下文", result)
                self.assertIn("message_index=1; role=用户", result)
                self.assertIn("message_index=2; role=AI", result)
                self.assertIn("收到，历史口令 BLUE-731。", result)
            finally:
                agent.CHAT_THREADS_PATH = original_path


if __name__ == "__main__":
    unittest.main()
