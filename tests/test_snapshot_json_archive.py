import gzip
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('snapshot_archive',Path(__file__).parents[1]/'scripts/archive_large_snapshot_json.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SnapshotArchiveTests(unittest.TestCase):
    def test_roundtrip_and_hardlinked_original_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=root/'original';data=os.urandom(4000);original.write_bytes(data)
            target=root/'snapshot/curation_data/research_runs/run/final.json';target.parent.mkdir(parents=True);os.link(original,target)
            rows=m.archive_large_jsons(root/'snapshot',threshold=1000,part_size=600)
            self.assertEqual(original.read_bytes(),data)
            self.assertFalse(target.exists())
            manifest=json.loads(target.with_name('final.json.RESTORE.json').read_text())
            zipped=b''.join((target.parent/n).read_bytes() for n in manifest['gzip_parts_in_order'])
            self.assertEqual(gzip.decompress(zipped),data)
            self.assertEqual(hashlib.sha256(data).hexdigest(),manifest['original_sha256'])
            self.assertTrue(all((target.parent/n).stat().st_size<=600 for n in manifest['gzip_parts_in_order']))

    def test_small_json_left_as_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'curation_data/research_runs/run/small.json';p.parent.mkdir(parents=True);p.write_text('{}')
            self.assertEqual(m.archive_large_jsons(root),[])
            self.assertEqual(p.read_text(),'{}')
            m.write_manifest(root)
            self.assertIn(hashlib.sha256(b'{}').hexdigest(),(root/'SNAPSHOT_FILE_MANIFEST.tsv').read_text())
