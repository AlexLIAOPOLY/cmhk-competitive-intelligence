#!/usr/bin/env python3
"""Plan or apply timestamp names using report audits and matching archive bytes."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cmhk.reporting.report_naming import rename_report_bundle


def plan_renames(root: Path) -> list[dict]:
    archives = {}
    for path in (root / 'archives').glob('*/*.docx'):
        archives.setdefault(path.name, []).append(path)
    plan = []
    for path in sorted(root.glob('*业绩摘要*.docx')):
        match = re.fullmatch(r'(\d+月\d+日.*业绩摘要)(?: \(\d+\))?\.docx', path.name)
        if not match:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        clock, evidence = None, ''
        for quality in [path.with_suffix('.quality.json'), Path(str(path) + '.quality.json')]:
            if quality.exists():
                data = json.loads(quality.read_text())
                value = data.get('generatedAt')
                if value and data.get('reportFile') == path.name:
                    clock, evidence = datetime.fromisoformat(value), quality.name
                    break
        if clock is None:
            for archive in sorted(archives.get(path.name, [])):
                if (re.fullmatch(r'\d{8}_\d{6}', archive.parent.name)
                        and hashlib.sha256(archive.read_bytes()).hexdigest() == digest):
                    clock = datetime.strptime(archive.parent.name, '%Y%m%d_%H%M%S').replace(tzinfo=ZoneInfo('Asia/Hong_Kong'))
                    evidence = archive.relative_to(root).as_posix()
                    break
        # Never infer a historical creation time from a later edited/copied mtime.
        label = clock.strftime('%H时%M分%S秒') if clock else '原始稿'
        new_name = f'{match.group(1)}（{label}）.docx'
        if clock and not path.name.startswith(f'{clock.month}月{clock.day}日'):
            raise ValueError(f'报告日期与生成审计不一致：{path.name}')
        plan.append({'old': path.name, 'new': new_name, 'sha256': digest,
                     'mtime_ns': path.stat().st_mtime_ns,
                     'generatedAt': clock.isoformat() if clock else '', 'timeEvidence': evidence})
    names = [item['new'] for item in plan]
    if len(names) != len(set(names)) or any((root / name).exists() for name in names):
        raise ValueError('新名称冲突，请先核查报告记录')
    return plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    plan = plan_renames(root)
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    folder = root / 'var/report_renames' / datetime.now().strftime('%Y%m%d_%H%M%S')
    folder.mkdir(parents=True)
    (folder / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    results = []
    for item in plan:
        old, new = root / item['old'], root / item['new']
        if hashlib.sha256(old.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'报告在核验后发生变化：{old.name}')
        result = rename_report_bundle(root, old, new, metadata_updates={
            'generatedAt': item['generatedAt'], 'namingTimeEvidence': item['timeEvidence']})
        assert hashlib.sha256(new.read_bytes()).hexdigest() == item['sha256']
        assert new.stat().st_mtime_ns == item['mtime_ns']
        results.append(result)
        (folder / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({'renamed': len(results), 'journal': str(folder),
                      'verifiedTimes': sum(bool(x['generatedAt']) for x in plan),
                      'contentAndModificationTimesPreserved': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
