"""Resolve publisher links and cache validated images before the sending clock."""
from __future__ import annotations

import fcntl
import hashlib
import io
import ipaddress
import json
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from PIL import Image


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


def fetch(url: str, *, max_bytes=6_000_000) -> tuple[bytes, str, str]:
    # Validate every redirect before a network request; publisher HTML is untrusted.
    with httpx.Client(timeout=httpx.Timeout(15, connect=8), follow_redirects=False,
                      headers={'User-Agent': 'Mozilla/5.0 CMHK-NewsReader/1.0'}) as client:
        for _ in range(5):
            parsed = urlsplit(article_url(url))
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise ValueError('新闻资源不是公网地址')
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
    page = BeautifulSoup(data, 'html.parser')
    images = []
    for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]'):
        for element in page.select(selector):
            if element.get('content'):
                images.append(urljoin(final_url, element['content']))
    description = page.select_one('meta[property="og:description"], meta[name="description"]')
    # Existing reviewed source excerpts remain the authority. Live page content
    # is not used to silently replace them with navigation, ads or related news.
    return {'news_url': final_url, 'image_urls': list(dict.fromkeys(images)),
            'source_description': description.get('content', '')[:2000] if description else ''}


def upload_image(service, url: str, cache: Path, profile: str) -> str:
    data, _, _ = fetch(url, max_bytes=8_000_000)
    with Image.open(io.BytesIO(data)) as picture:
        if min(picture.size) < 100 or max(picture.size) > 12000:
            raise ValueError('新闻配图尺寸不合适')
        suffix = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'GIF': '.gif'}.get(picture.format)
        picture.verify()
    if not suffix:
        raise ValueError('新闻配图格式不支持')
    digest = hashlib.sha256(data).hexdigest()
    target = cache / 'uploads' / (fingerprint([profile, digest]) + '.json')
    cached = load(target)
    if cached.get('image_key'):
        return cached['image_key']
    path = cache / 'images' / (digest + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    result = service._lark(['lark-cli', 'im', 'images', 'create', '--as', 'bot', '--profile', profile,
                           '--data', json.dumps({'image_type': 'message'}), '--file', str(path)], timeout=60)
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
        key = fingerprint([original, item.get('published_at'), profile])
        with (cache / (key + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            target = cache / (key + '.json')
            asset = load(target)
            if not asset.get('news_url'):
                direct = resolve_source(original, cache)
                try:
                    asset = source_metadata(direct)
                except (httpx.HTTPError, OSError, ValueError):
                    # A publisher may restrict machine downloads while its public
                    # article is readable in the user's browser. Keep its direct URL.
                    asset = {'news_url': direct, 'image_urls': [], 'metadata_unavailable': True}
                save(target, asset)
            article_url(asset['news_url'])
            if not asset.get('image_key'):
                candidates = list(dict.fromkeys([
                    *[str(item.get(field)) for field in ('image_source_url', 'image_url') if item.get(field)],
                    *asset.get('image_urls', []),
                ]))
                for image_url in candidates[:3]:
                    try:
                        asset['image_key'] = upload_image(service, image_url, cache, profile)
                        asset['image_source_url'] = image_url
                        break
                    except (httpx.HTTPError, OSError, ValueError):
                        continue
                # Transport/API upload failures are not swallowed: retry before IM.
                save(target, asset)
            image_key = asset.get('image_key') or fallback_image_key
            if not re.fullmatch(r'img_[A-Za-z0-9_-]+', image_key):
                raise ValueError('缺少可用新闻配图和栏目封面，保留批次重试')
            ready.append({**item, 'news_url': asset['news_url'], 'image_key': image_key,
                          'image_kind': 'source' if asset.get('image_key') else 'section',
                          'image_source_url': asset.get('image_source_url', '')})
    return ready
