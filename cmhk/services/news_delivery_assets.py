"""Resolve publisher links and cache validated images before the sending clock."""
from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from cmhk.services.news_image_quality import (
    NewsImageUnavailable, extract_candidates, policy_key, rank_candidates,
    require_reviewed_images, review_image, search_image_candidates, validate_image,
)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def load(path: Path) -> dict:
    try:
        result = json.loads(path.read_text())
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def article_url(value: str) -> str:
    value = str(value or '').strip()
    parsed = urlsplit(value)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username
            or parsed.password or re.search(r'[\s<>\x00-\x1f]', value)
            or parsed.hostname.lower() in ('localhost', 'news.google.com')
            or parsed.hostname.lower().endswith(('.local', '.localhost'))
            or (parsed.hostname.lower().endswith(('.feishu.cn', '.larksuite.com'))
                and parsed.path.startswith(('/docx/', '/wiki/')))):
        raise ValueError('新闻原文地址无效或仍为聚合页')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('新闻地址不是公网地址')
    return value


def verify_public_host(host: str, port: int, client) -> None:
    addresses = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, port)]
    if addresses and all(address.is_global for address in addresses):
        return
    # Local proxy DNS uses this reserved benchmark range as virtual routing IPs.
    # Check real A and AAAA records via HTTPS before allowing the public request.
    virtual = ipaddress.ip_network('198.18.0.0/15')
    if not addresses or any(not address.is_global and address not in virtual for address in addresses):
        raise ValueError('新闻资源不是公网地址')
    public = []
    for record_type in ('A', 'AAAA'):
        response = client.get('https://dns.google/resolve', params={'name': host, 'type': record_type})
        response.raise_for_status()
        result = response.json()
        if result.get('Status') != 0:
            raise ValueError('新闻资源公网解析失败')
        public.extend(ipaddress.ip_address(row['data']) for row in result.get('Answer', [])
                      if row.get('type') in (1, 28))
    if not public or any(not address.is_global for address in public):
        raise ValueError('新闻资源不是公网地址')


def fetch(url: str, *, max_bytes=6_000_000) -> tuple[bytes, str, str]:
    # Validate every redirect before a network request; publisher HTML is untrusted.
    with httpx.Client(timeout=httpx.Timeout(15, connect=8), follow_redirects=False,
                      headers={'User-Agent': 'Mozilla/5.0 CMHK-NewsReader/1.0'}) as client:
        for _ in range(5):
            parsed = urlsplit(article_url(url))
            verify_public_host(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), client)
            with client.stream('GET', url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['location'])
                    continue
                response.raise_for_status()
                parts, total = [], 0
                for part in response.iter_bytes():
                    total += len(part)
                    if total > max_bytes:
                        raise ValueError('新闻资源超过大小上限')
                    parts.append(part)
                return b''.join(parts), url, response.headers.get('content-type', '')
    raise ValueError('新闻资源重定向过多')


def resolve_source(url: str, cache: Path) -> str:
    if urlsplit(url).hostname != 'news.google.com':
        return article_url(url)
    target = cache / 'links' / (fingerprint(url) + '.json')
    cached = load(target).get('url')
    if cached:
        return article_url(cached)
    # The third-party decoder lacks request deadlines. Isolate it in a bounded
    # child process so a stalled Google endpoint cannot occupy a worker forever.
    result = subprocess.run([sys.executable, '-c',
        'import json,sys; from googlenewsdecoder import gnewsdecoder; '
        'print(json.dumps(gnewsdecoder(sys.argv[1])))', url],
        capture_output=True, text=True, timeout=45, check=True)
    decoded = json.loads(result.stdout)
    if not decoded.get('status'):
        raise ValueError('新闻聚合地址解析失败，保留批次重试')
    direct = article_url(decoded.get('decoded_url'))
    save(target, {'url': direct})
    return direct


def source_metadata(url: str) -> dict:
    data, final_url, content_type = fetch(url)
    if 'html' not in content_type:
        return {'news_url': final_url, 'image_urls': []}
    return extract_candidates(data, final_url)


def upload_image(service, url: str, cache: Path, profile: str, *, data: bytes | None = None) -> str:
    # Upload the exact bytes that passed visual review, never a fresh remote copy.
    if data is None:
        data, _, _ = fetch(url, max_bytes=8_000_000)
    suffix = validate_image(data)
    digest = hashlib.sha256(data).hexdigest()
    target = cache / 'uploads' / (fingerprint([profile, digest]) + '.json')
    cached = load(target)
    if cached.get('image_key'):
        return cached['image_key']
    path = cache / 'images' / (digest + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    result = service._lark(['lark-cli', 'im', 'images', 'create', '--as', 'bot', '--profile', profile,
                           '--data', json.dumps({'image_type': 'message'}), '--file',
                           str(path.relative_to(service.runtime_root))], timeout=60)
    key = result.get('data', {}).get('image_key', '')
    if not re.fullmatch(r'img_[A-Za-z0-9_-]+', key):
        raise ValueError('新闻配图上传未返回有效 image_key')
    save(target, {'image_key': key, 'sha256': digest, 'source_url': url, 'profile': profile})
    return key


def prepare_news_assets(items: list[dict], service, *, profile: str, fallback_image_key: str) -> list[dict]:
    cache = service.runtime_root / 'var/subscriptions/news-assets'
    cache.mkdir(parents=True, exist_ok=True)
    ready = []
    for item in items:
        original = str(item.get('source_url') or item.get('url') or '')
        key = fingerprint([policy_key(), original, item.get('published_at'), profile,
                           item.get('title'), item.get('summary'), item.get('source_summary')])
        with (cache / (key + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            target = cache / (key + '.json')
            asset = load(target)
            if not asset.get('news_url') or (not asset.get('image_key') and
                    time.time() - asset.get('fetched_at', 0) > 600):
                direct = resolve_source(original, cache)
                try:
                    asset = source_metadata(direct)
                except (httpx.HTTPError, OSError, ValueError):
                    # A publisher may restrict machine downloads while its public
                    # article is readable in the user's browser. Keep its direct URL.
                    asset = {'news_url': direct, 'image_urls': [], 'metadata_unavailable': True}
                asset['fetched_at'] = time.time()
                save(target, asset)
            article_url(asset['news_url'])
            if not asset.get('image_key'):
                deadline = time.monotonic() + 360
                attempts = []
                seen = set()
                def candidates():
                    yield from rank_candidates(asset.get('image_candidates', []), item)[:6]
                    # No acceptable article image: the agent searches event and subject keywords.
                    yield from search_image_candidates({**item, 'news_url': asset['news_url']}, cache, deadline=deadline)
                for candidate in candidates():
                    if time.monotonic() >= deadline:
                        raise NewsImageUnavailable('新闻配图本轮时间已用完，已保存进度等待继续')
                    image_url = candidate['url']
                    if image_url in seen:
                        continue
                    seen.add(image_url)
                    try:
                        data, _, _ = fetch(image_url, max_bytes=8_000_000)
                        validate_image(data)
                    except (httpx.HTTPError, OSError, ValueError):
                        attempts.append({'image_url': image_url, 'status': 'download_or_format_failed'})
                        asset['image_attempts'] = attempts
                        save(target, asset)
                        continue
                    # A model outage is not evidence against this picture. Stop
                    # this attempt and recover later instead of hammering every candidate.
                    review = review_image(item, candidate, data, cache, deadline=deadline)
                    attempts.append({'image_url': image_url, 'review': review})
                    asset['image_attempts'] = attempts
                    save(target, asset)
                    if not review['accepted']:
                        continue
                    image_key = upload_image(service, image_url, cache, profile, data=data)
                    if image_key == fallback_image_key:
                        continue
                    asset.update({'image_key': image_key, 'image_source_url': image_url,
                                  'image_page_url': candidate['page_url'], 'image_sha256': review['sha256'],
                                  'image_kind': 'source' if review['relation'] == 'event' else 'related',
                                  'image_review_status': 'accepted', 'image_policy_key': policy_key(),
                                  'image_review': review})
                    break
                # Transport/API upload failures are not swallowed: retry before IM.
                save(target, asset)
            result = {**item, 'news_url': asset['news_url'], **{field: asset.get(field, '') for field in (
                'image_key', 'image_source_url', 'image_page_url', 'image_sha256', 'image_kind',
                'image_review_status', 'image_policy_key', 'image_review')}}
            require_reviewed_images([result], fallback_image_key)
            ready.append(result)
    return ready
