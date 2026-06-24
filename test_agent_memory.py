import tempfile
import unittest
from pathlib import Path

import agent_memory


class AgentMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.original_paths = (
            agent_memory.MEMORY_DIR,
            agent_memory.MEMORY_PATH,
            agent_memory.MANIFEST_PATH,
            agent_memory.README_PATH,
        )
        agent_memory.MEMORY_DIR = root
        agent_memory.MEMORY_PATH = root / "memories.jsonl"
        agent_memory.MANIFEST_PATH = root / "manifest.json"
        agent_memory.README_PATH = root / "README.md"

    def tearDown(self) -> None:
        (
            agent_memory.MEMORY_DIR,
            agent_memory.MEMORY_PATH,
            agent_memory.MANIFEST_PATH,
            agent_memory.README_PATH,
        ) = self.original_paths
        self.tempdir.cleanup()

    def test_add_memory_enriches_metadata_and_deduplicates(self) -> None:
        first = agent_memory.add_memory(
            "以后 CMHK 数据整理必须优先读取 official_value 和审计文件。",
            kind="procedural",
            tags=["CMHK", "audit"],
            importance=0.9,
            confidence=0.95,
        )
        second = agent_memory.add_memory(
            "以后 CMHK 数据整理必须优先读取 official_value 和审计文件。",
            kind="procedural",
            tags=["CMHK", "audit"],
            importance=0.5,
            confidence=0.7,
        )
        rows = agent_memory.load_memories()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["schema_version"], 2)
        self.assertEqual(rows[0]["kind"], "procedural")
        self.assertGreaterEqual(rows[0]["importance"], 0.9)
        self.assertIn("CMHK", rows[0]["entities"])

    def test_search_uses_entities_and_updates_access_stats(self) -> None:
        agent_memory.add_memory(
            "Render 部署失败时先检查 render.yaml、Dockerfile 和 /api/status。",
            kind="episodic",
            tags=["Render", "deployment"],
            importance=0.8,
        )
        agent_memory.add_memory(
            "用户偏好：小 UI 文案修改不用默认截图。",
            kind="semantic",
            tags=["frontend"],
        )
        rows = agent_memory.search_memories("Render 部署怎么排查", limit=1)
        self.assertEqual(len(rows), 1)
        self.assertIn("Render", rows[0]["content"])

        loaded = agent_memory.load_memories()
        render_row = next(item for item in loaded if "Render" in item["content"])
        self.assertEqual(render_row["access_count"], 1)
        self.assertGreater(render_row["last_accessed_at"], 0)

    def test_auto_capture_classifies_procedural_rules(self) -> None:
        item = agent_memory.auto_capture_user_memory("以后每次新增来源都必须先点开验证，不要直接引用搜索摘要。")
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "procedural")
        self.assertIn("user-preference", item["tags"])
        self.assertGreaterEqual(item["importance"], 0.8)

    def test_auto_capture_ignores_memory_read_only_queries(self) -> None:
        item = agent_memory.auto_capture_user_memory(
            "再列出当前长期记忆条目数量，并说明每条的 kind、entities、importance、confidence、access_count；不要展开正文。"
        )
        self.assertIsNone(item)
        self.assertEqual(agent_memory.load_memories(), [])

    def test_auto_capture_ignores_synthetic_frontend_tests(self) -> None:
        item = agent_memory.auto_capture_user_memory("前台发送测试 10：只回复 OK-10，不要调用工具。")
        self.assertIsNone(item)
        self.assertEqual(agent_memory.load_memories(), [])

    def test_auto_capture_ignores_chat_history_lookup_queries(self) -> None:
        item = agent_memory.auto_capture_user_memory(
            "查一下之前聊天里 LIVE-MEM-ETA 的默认报告署名是什么？只回答署名和命中消息序号。"
        )
        self.assertIsNone(item)
        self.assertEqual(agent_memory.load_memories(), [])

    def test_compact_memory_store_merges_legacy_duplicates(self) -> None:
        agent_memory._ensure_store()
        with agent_memory.MEMORY_PATH.open("a", encoding="utf-8") as handle:
            handle.write('{"id":"old_1","kind":"procedural","content":"不要输出过程旁白。","tags":["user-preference"],"source":"user-message","created_at":1000,"created_date":"2026-06-22"}\n')
            handle.write('{"id":"old_2","kind":"procedural","content":"不要输出过程旁白。","tags":["user-preference"],"source":"user-message","created_at":2000,"created_date":"2026-06-22","access_count":2}\n')
        result = agent_memory.compact_memory_store()
        rows = agent_memory.load_memories()
        self.assertEqual(result["before"], 2)
        self.assertEqual(result["after"], 1)
        self.assertEqual(rows[0]["schema_version"], 2)
        self.assertEqual(rows[0]["access_count"], 2)
        self.assertIn("old_1", rows[0].get("merged_memory_ids", []))


if __name__ == "__main__":
    unittest.main()
