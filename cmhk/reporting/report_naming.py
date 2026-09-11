"""Readable report names and coordinated renames of their local assets."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import json
import re
import sqlite3
import uuid


def report_display_name(name: str) -> str:
    """Keep storage identities out of reader-facing titles and downloads."""
    match = re.fullmatch(
        r'(\d+月\d+日(?:运营商|香港竞对)业绩摘要)'
        r'(?:（(?:\d{2}时\d{2}分\d{2}秒|原始稿)(?:-[0-9a-f]{6})?）(?:-[0-9a-f]{6})?| \(\d+\))?'
        r'(（编辑稿(?:\s+\d+)?）)?\.docx', name)
    return f'{match[1]}{match[2] or ""}.docx' if match else name


def performance_output_path(root: Path, now: datetime | None = None) -> Path:
    clock = now or datetime.now(ZoneInfo('Asia/Hong_Kong'))
    if clock.tzinfo:
        clock = clock.astimezone(ZoneInfo('Asia/Hong_Kong'))
    stem = f'{clock.month}月{clock.day}日运营商业绩摘要（{clock:%H时%M分%S秒}）'
    path = root / f'{stem}.docx'
    while path.exists():
        path = root / f'{stem}-{uuid.uuid4().hex[:6]}.docx'
    return path


def audio_rename_pairs(old: Path, new: Path, directory: Path) -> list[tuple[Path, Path]]:
    from tts_service import safe_audio_stem
    pairs = []
    for folder, suffixes in [(directory, ('.mp3', '.wav', '.opus', '.txt', '.timings.json', '.source.json')),
                             (directory / '.pending', ('.mp3', '.json', '.timings.json'))]:
        for suffix in suffixes:
            source = folder / (safe_audio_stem(old) + suffix)
            target = folder / (safe_audio_stem(new) + suffix)
            if source.exists() and source != target:
                pairs.append((source, target))
    return pairs


def rename_report_bundle(root: Path, old: Path, new: Path, *, note: str | None = None,
                         metadata_updates: dict | None = None) -> dict:
    """Move bytes without regenerating media; roll back if a dependent update fails."""
    from data_curation.storage import atomic_write_json
    from cmhk.reporting.pdf_preview import pdf_preview_path
    from tts_service import safe_audio_stem
    root, old, new = root.resolve(), old.resolve(), new.resolve()
    old_rel, new_rel = old.relative_to(root).as_posix(), new.relative_to(root).as_posix()
    if old.parent != new.parent or new.suffix != '.docx' or not old.is_file():
        raise ValueError('文件不存在或重命名路径无效')
    metadata_path = root / 'data/reporting/report_file_metadata.json'
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    audio_dir = root / 'audio'
    audio_dir.mkdir(exist_ok=True)
    with ExitStack() as stack:
        lock = stack.enter_context((metadata_path.parent / '.rename.lock').open('a'))
        fcntl.flock(lock, fcntl.LOCK_EX)
        for stem in sorted({safe_audio_stem(old), safe_audio_stem(new)}):
            lock = stack.enter_context((audio_dir / (stem + '.lock')).open('a'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('该报告正在生成音频，请完成后再改名') from exc
        original_metadata = metadata_path.read_bytes() if metadata_path.exists() else None
        metadata = json.loads(original_metadata) if original_metadata else {}
        pairs = [(old, new)] if old != new else []
        qualities = []
        if old != new:
            for source, target in [(old.with_suffix('.quality.json'), new.with_suffix('.quality.json')),
                                   (Path(str(old) + '.quality.json'), Path(str(new) + '.quality.json'))]:
                if source.exists():
                    qualities.append((target, source.read_bytes()))
                    pairs.append((source, target))
            preview_dir = root / 'web/static/report-previews'
            source, target = pdf_preview_path(old, preview_dir), pdf_preview_path(new, preview_dir)
            if source.exists():
                pairs.append((source, target))
            pairs.extend(audio_rename_pairs(old, new, audio_dir))
        for _, target in pairs:
            if target.exists():
                raise ValueError(f'同名文件或关联附件已存在：{target.name}')
        db_path = root / 'var/subscriptions/subscriptions.sqlite3'
        db = sqlite3.connect(db_path) if db_path.exists() else None
        if db:
            stack.callback(db.close)
            db.execute('BEGIN IMMEDIATE')
        moved = []
        try:
            for source, target in pairs:
                source.rename(target)
                moved.append((source, target))
            for target, content in qualities:
                quality = json.loads(content)
                quality['reportFile'] = new.name
                atomic_write_json(target, quality)
            existing = metadata.pop(old_rel, {})
            existing = existing if isinstance(existing, dict) else {}
            existing.setdefault('reportType', 'carrier-performance' if '业绩摘要' in old.name else 'weekly')
            if note is not None:
                existing['note'] = note
            existing.update(metadata_updates or {})
            if old != new:
                existing['renamedFrom'] = list(dict.fromkeys([*existing.get('renamedFrom', []), old_rel]))
            existing['updatedAt'] = datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(timespec='seconds')
            metadata[new_rel] = existing
            for item in metadata.values():
                if isinstance(item, dict) and item.get('sourcePath') == old_rel:
                    item['sourcePath'] = new_rel
            atomic_write_json(metadata_path, metadata)
            if db and old != new:
                db.execute("UPDATE subscription_admin_preferences SET preference_value=? WHERE preference_key IN ('weekly_report_path','performance_report_path') AND preference_value=?", (new_rel, old_rel))
                db.execute("UPDATE pending_subscription_deliveries SET content_ref=? WHERE service IN ('weekly','performance') AND status='queued' AND content_ref=?", (new_rel, old_rel))
            if db:
                db.commit()
        except Exception:
            if db:
                db.rollback()
            for target, content in qualities:
                if target.exists():
                    target.write_bytes(content)
            for source, target in reversed(moved):
                target.rename(source)
            if original_metadata is None:
                metadata_path.unlink(missing_ok=True)
            else:
                metadata_path.write_bytes(original_metadata)
            raise
    return {'old': old_rel, 'new': new_rel, 'assetsMoved': len(pairs)}
