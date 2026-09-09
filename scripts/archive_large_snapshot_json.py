#!/usr/bin/env python3
"""Losslessly archive oversized research JSON in an isolated private snapshot."""
import gzip
import hashlib
import json
import shutil
import sys
from pathlib import Path


def archive_large_jsons(root: Path, threshold: int = 95_000_000, part_size: int = 45_000_000) -> list[dict]:
    archived = []
    for source in sorted((root / 'curation_data/research_runs').rglob('*.json')):
        if source.is_symlink() or source.stat().st_size <= threshold:
            continue
        original_size = source.stat().st_size
        original_hash = hashlib.sha256()
        compressed = source.with_name(source.name + '.gz')
        # Write a separate inode: snapshots may hard-link source files.
        if compressed.exists():
            raise FileExistsError(compressed)
        with source.open('rb') as src, gzip.open(compressed, 'wb', compresslevel=6) as dst:
            while block := src.read(1024 * 1024):
                original_hash.update(block)
                dst.write(block)
        verified_hash = hashlib.sha256()
        with gzip.open(compressed, 'rb') as src:
            while block := src.read(1024 * 1024):
                verified_hash.update(block)
        if verified_hash.digest() != original_hash.digest():
            raise ValueError(f'Compressed JSON verification failed: {source.relative_to(root)}')
        files = [compressed.name]
        if compressed.stat().st_size > threshold:
            files = []
            with compressed.open('rb') as src:
                number = 0
                while block := src.read(part_size):
                    part = compressed.with_name(compressed.name + f'.part-{number:03d}')
                    with part.open('xb') as dst:
                        dst.write(block)
                    files.append(part.name)
                    number += 1
            compressed.unlink()
        record = {'original': source.name, 'original_bytes': original_size,
                  'original_sha256': original_hash.hexdigest(), 'gzip_parts_in_order': files}
        manifest = source.with_name(source.name + '.RESTORE.json')
        with manifest.open('x') as dst:
            json.dump(record, dst, ensure_ascii=False, indent=2)
        source.with_name(source.name + '.RESTORE.md').write_text(
            'Restore by concatenating gzip_parts_in_order from the adjacent RESTORE.json, '
            'decompressing the combined gzip stream, and writing original. Verify the '
            'restored byte count and SHA-256 against that manifest.\n')
        source.unlink()  # Only remove the snapshot link, never the workspace original.
        archived.append({'path': str(source.relative_to(root)), **record})
    return archived


def write_manifest(root: Path) -> None:
    target = root / 'SNAPSHOT_FILE_MANIFEST.tsv'
    with target.open('w') as output:
        output.write('path\tbytes\tsha256\n')
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root)
            if '.git' in relative.parts or path == target or not path.is_file():
                continue
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            output.write(f'{relative}\t{path.stat().st_size}\t{digest}\n')


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    for item in archive_large_jsons(root):
        print(f"Archived oversized research JSON: {item['path']} ({item['original_bytes']} bytes)")
    write_manifest(root)
