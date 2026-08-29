from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from data_curation.checkpoint_store import maintain_checkpoint_database


class CheckpointStoreTests(unittest.TestCase):
    def test_maintenance_prunes_old_threads_and_keeps_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "checkpoints.sqlite"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE checkpoints (
                    thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT,
                    type TEXT, checkpoint BLOB, metadata BLOB,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                );
                CREATE TABLE writes (
                    thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    idx INTEGER NOT NULL, channel TEXT NOT NULL, type TEXT, value BLOB,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                );
                """
            )
            for index in range(5):
                thread_id = f"thread-{index}"
                checkpoint_id = f"checkpoint-{index}"
                connection.execute(
                    "INSERT INTO checkpoints VALUES (?, '', ?, NULL, 'json', ?, ?)",
                    (thread_id, checkpoint_id, b"{}", b"{}"),
                )
                connection.execute(
                    "INSERT INTO writes VALUES (?, '', ?, 'task', 0, 'channel', 'json', ?)",
                    (thread_id, checkpoint_id, b"{}"),
                )
            connection.commit()
            connection.close()

            result = maintain_checkpoint_database(
                path,
                current_thread_id="thread-0",
                keep_threads=2,
                force=True,
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["maintained"])
            self.assertEqual(result["integrity_after"], "ok")
            self.assertTrue(Path(result["backup_path"]).exists())
            connection = sqlite3.connect(path)
            retained = {
                row[0]
                for row in connection.execute("SELECT DISTINCT thread_id FROM checkpoints")
            }
            connection.close()
            self.assertIn("thread-0", retained)
            self.assertEqual(len(retained), 3)


if __name__ == "__main__":
    unittest.main()
