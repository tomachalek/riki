# Copyright 2026 Tomas Machalek <tomas.machalek@gmail.com>
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Previews of external links (title, description, image, site icon).

Metadata are taken from OpenGraph / Twitter card / standard HTML meta tags
of the target page. Results (including failures) are cached on disk, images
are downloaded, downscaled and served locally, so a preview is fetched from
the outside world only once per TTL.
"""

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import socket
import tempfile
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote_to_bytes, urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import ThreadedResolver
from bs4 import BeautifulSoup
from PIL import Image

logger = logging.getLogger(__name__)

USER_AGENT = 'Mozilla/5.0 (compatible; RikiLinkPreview/1.0)'
MAX_HTML_BYTES = 1 << 20
MAX_IMAGE_BYTES = 8 << 20
MAX_REDIRECTS = 5
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15, sock_connect=5)
TTL_OK = 30 * 24 * 3600
TTL_ERROR = 24 * 3600
THUMB_SIZE = (640, 400)
ICON_SIZE = 64
MAX_TEXT_LEN = 400
MAX_IMAGE_PIXELS = 40_000_000

IMAGE_NAME_RE = re.compile(r'^[0-9a-f]{64}(-icon)?\.(jpg|png)$')


class PreviewError(Exception):
    pass


@dataclass
class LinkPreview:
    url: str
    final_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    site_name: Optional[str] = None
    image: Optional[str] = None  # local file name in the cache dir
    icon: Optional[str] = None  # local file name in the cache dir
    error: Optional[str] = None
    fetched: float = 0


def _url_hash(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def _ip_allowed(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split('%', 1)[0])  # strip IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class _PublicOnlyResolver(AbstractResolver):
    """
    A resolver refusing to connect to loopback/private/link-local/... addresses.
    As it is applied on each connection (incl. redirects), it also covers DNS rebinding.
    """

    def __init__(self):
        self._resolver = ThreadedResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> List[Dict[str, Any]]:
        ans = [r for r in await self._resolver.resolve(host, port, family) if _ip_allowed(r['host'])]
        if not ans:
            raise OSError(f'{host} does not resolve to a public address')
        return ans

    async def close(self) -> None:
        await self._resolver.close()


def _decode_data_url(url: str) -> Optional[bytes]:
    """
    Decodes an inline (data:) image. Returns None for empty/non-image/broken ones
    (e.g. 'data:,' which pages use to suppress the browser's favicon request).
    """
    header, _, payload = url[5:].partition(',')
    params = header.split(';')
    if not payload or not params[0].lower().startswith('image/') or len(payload) > MAX_IMAGE_BYTES * 4 // 3 + 4:
        return None
    try:
        if 'base64' in (p.strip().lower() for p in params[1:]):
            return base64.b64decode(payload, validate=False)
        return unquote_to_bytes(payload)
    except ValueError:
        return None


def _clean_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = ' '.join(s.split())
    if len(s) > MAX_TEXT_LEN:
        s = s[:MAX_TEXT_LEN - 1].rstrip() + '…'
    return s or None


def _icon_size(link) -> int:
    sizes = (link.get('sizes') or '').lower()
    m = re.match(r'(\d+)x\d+', sizes)
    if m:
        return int(m.group(1))
    return 1000 if sizes == 'any' else 16


def parse_html(html: bytes, base_url: str, encoding: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Extracts preview metadata from (a beginning of) an HTML page
    """
    soup = BeautifulSoup(html, 'html.parser', from_encoding=encoding)
    base = soup.find('base', href=True)
    if base:
        base_url = urljoin(base_url, base['href'])

    def meta(*names: str) -> Optional[str]:
        for name in names:
            tag = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
            if tag and tag.get('content', '').strip():
                return tag['content'].strip()
        return None

    title = meta('og:title', 'twitter:title')
    if not title and soup.title and soup.title.string:
        title = soup.title.string
    image = meta('og:image:secure_url', 'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src')

    icons = []
    for link in soup.find_all('link', href=True):
        rel = [r.lower() for r in (link.get('rel') or [])]
        if 'apple-touch-icon' in rel:
            icons.append((180, link['href']))
        elif 'icon' in rel and not (link.get('type') or '').endswith('svg+xml') \
                and not link['href'].lower().endswith('.svg'):
            icons.append((_icon_size(link), link['href']))
    # prefer the smallest icon >= 32px, otherwise the biggest one available
    icons.sort(key=lambda x: (x[0] < 32, x[0] if x[0] >= 32 else -x[0]))
    icon = urljoin(base_url, icons[0][1]) if icons else urljoin(base_url, '/favicon.ico')

    return {
        'title': _clean_text(title),
        'description': _clean_text(meta('og:description', 'twitter:description', 'description')),
        'site_name': _clean_text(meta('og:site_name', 'application-name')),
        'image': urljoin(base_url, image) if image else None,
        'icon': icon,
    }


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel('A'))
        return bg
    return img.convert('RGB')


def _open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    if img.size[0] * img.size[1] > MAX_IMAGE_PIXELS:
        img.close()
        raise PreviewError(f'image too large ({img.size[0]}x{img.size[1]})')
    return img


def make_thumbnail(data: bytes, path: str):
    with _open_image(data) as img:
        img.draft('RGB', THUMB_SIZE)  # fast JPEG downscaling while decoding (no-op for other formats)
        img.thumbnail(THUMB_SIZE)
        _atomic_save(_to_rgb(img), path, 'JPEG', quality=82, optimize=True)


def make_icon(data: bytes, path: str):
    with _open_image(data) as img:
        if getattr(img, 'format', None) == 'ICO':
            # pick the largest image stored in the .ico file
            sizes = sorted(img.info.get('sizes') or [img.size])
            img.size = sizes[-1]
        img = img.convert('RGBA')
        img.thumbnail((ICON_SIZE, ICON_SIZE))
        _atomic_save(img, path, 'PNG')


def _atomic_save(img: Image.Image, path: str, fmt: str, **kwargs):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp-')
    try:
        with os.fdopen(fd, 'wb') as fw:
            img.save(fw, fmt, **kwargs)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class LinkPreviewService:

    def __init__(self, cache_dir: str, allow_private_networks: bool = False, max_concurrent: int = 6):
        self._cache_dir = cache_dir
        self._allow_private = allow_private_networks
        self._session: Optional[aiohttp.ClientSession] = None
        self._inflight: Dict[str, 'asyncio.Future[LinkPreview]'] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        os.makedirs(cache_dir, exist_ok=True)

    async def start(self):
        connector = aiohttp.TCPConnector(
            resolver=None if self._allow_private else _PublicOnlyResolver(), limit=20, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(
            connector=connector, timeout=FETCH_TIMEOUT,
            headers={'User-Agent': USER_AGENT, 'Accept-Language': 'en,*;q=0.5'})

    async def close(self):
        if self._session:
            await self._session.close()

    def image_path(self, name: str) -> Optional[str]:
        if not IMAGE_NAME_RE.match(name):
            return None
        path = os.path.join(self._cache_dir, name)
        return path if os.path.isfile(path) else None

    @staticmethod
    def validate_url(url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise PreviewError('only absolute http(s) URLs are supported')
        return url

    async def get(self, url: str) -> LinkPreview:
        self.validate_url(url)
        key = _url_hash(url)
        cached = await asyncio.get_running_loop().run_in_executor(None, self._load_cached, key)
        if cached:
            return cached
        if key not in self._inflight:
            fut = asyncio.ensure_future(self._fetch_and_store(url, key))
            self._inflight[key] = fut
            fut.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(self._inflight[key])

    def _load_cached(self, key: str) -> Optional[LinkPreview]:
        try:
            with open(os.path.join(self._cache_dir, f'{key}.json'), 'r', encoding='utf-8') as fr:
                data = json.load(fr)
            preview = LinkPreview(**data)
        except (OSError, ValueError, TypeError):
            return None
        ttl = TTL_ERROR if preview.error else TTL_OK
        return preview if time.time() - preview.fetched < ttl else None

    def _store(self, key: str, preview: LinkPreview):
        fd, tmp = tempfile.mkstemp(dir=self._cache_dir, prefix='.tmp-')
        with os.fdopen(fd, 'w', encoding='utf-8') as fw:
            json.dump(asdict(preview), fw, ensure_ascii=False)
        os.replace(tmp, os.path.join(self._cache_dir, f'{key}.json'))

    async def _fetch_and_store(self, url: str, key: str) -> LinkPreview:
        async with self._semaphore:
            try:
                preview = await self._fetch_preview(url, key)
            except (PreviewError, aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as ex:
                logger.info('link preview for %s failed: %s', url, ex)
                preview = LinkPreview(url=url, error=str(ex) or ex.__class__.__name__, fetched=time.time())
        await asyncio.get_running_loop().run_in_executor(None, self._store, key, preview)
        return preview

    async def _fetch(self, url: str, max_bytes: int) -> Tuple[bytes, str, str, Optional[str]]:
        """
        Fetches a URL (following redirects manually so each hop is validated).
        Returns (body, final url, content type, charset)
        """
        for _ in range(MAX_REDIRECTS + 1):
            self.validate_url(url)
            host = urlsplit(url).hostname
            if not self._allow_private:
                try:
                    if not _ip_allowed(host):
                        raise PreviewError('non-public address')
                except ValueError:
                    pass  # not an IP literal - checked by the resolver
            async with self._session.get(url, allow_redirects=False) as resp:
                if resp.status in (301, 302, 303, 307, 308) and 'Location' in resp.headers:
                    url = urljoin(url, resp.headers['Location'])
                    continue
                if resp.status != 200:
                    raise PreviewError(f'HTTP {resp.status}')
                chunks = []
                total = 0
                while total < max_bytes:
                    chunk = await resp.content.read(min(65536, max_bytes - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                return b''.join(chunks), str(resp.url), resp.content_type, resp.charset
        raise PreviewError('too many redirects')

    async def _fetch_preview(self, url: str, key: str) -> LinkPreview:
        body, final_url, ctype, charset = await self._fetch(url, MAX_HTML_BYTES)
        loop = asyncio.get_running_loop()
        preview = LinkPreview(url=url, final_url=final_url, fetched=time.time())
        if ctype.startswith('image/'):
            # a direct link to an image
            preview.image = await self._store_image(body, key, f'{key}.jpg', make_thumbnail)
            return preview
        if 'html' not in ctype:
            preview.title = os.path.basename(urlsplit(final_url).path) or None
            preview.description = ctype
            return preview

        meta = await loop.run_in_executor(None, parse_html, body, final_url, charset)
        preview.title = meta['title']
        preview.description = meta['description']
        preview.site_name = meta['site_name']
        if meta['image']:
            preview.image = await self._download_image(meta['image'], f'{key}.jpg', make_thumbnail)
        if meta['icon']:
            # icons are shared by all the pages of the same site
            icon_key = _url_hash(urlsplit(final_url).netloc)
            preview.icon = await self._download_image(meta['icon'], f'{icon_key}-icon.png', make_icon, TTL_OK)
        return preview

    async def _download_image(self, url: str, name: str, convert, reuse_ttl: Optional[int] = None) -> Optional[str]:
        path = os.path.join(self._cache_dir, name)
        if reuse_ttl and os.path.isfile(path) and time.time() - os.path.getmtime(path) < reuse_ttl:
            return name
        if url.startswith('data:'):
            data = _decode_data_url(url)
            if data is None:
                return None
            return await self._store_image(data, name, name, convert)
        try:
            data, _, ctype, _ = await self._fetch(url, MAX_IMAGE_BYTES)
            if ctype and not ctype.startswith('image/') and ctype != 'application/octet-stream':
                raise PreviewError(f'not an image ({ctype})')
            return await self._store_image(data, name, name, convert)
        except Exception as ex:  # a missing image must not spoil the rest of the preview
            logger.info('failed to fetch preview image %s: %s', url, ex)
            return None

    async def _store_image(self, data: bytes, key: str, name: str, convert) -> Optional[str]:
        path = os.path.join(self._cache_dir, name)
        try:
            await asyncio.get_running_loop().run_in_executor(None, convert, data, path)
            return name
        except Exception as ex:  # Pillow raises a variety of exceptions on broken/unsupported data
            logger.info('failed to process preview image for %s: %s', key, ex)
            return None
