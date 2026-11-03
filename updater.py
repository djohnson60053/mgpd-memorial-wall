"""Best-effort ODMP homepage collector. Fails closed; never invents records.

Run only if automated retrieval and image reuse are permitted by ODMP.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = 'https://www.odmp.org/'
OUT = Path('docs')
DATA = OUT / 'memorials.json'
IMAGES = OUT / 'images'
IMAGES.mkdir(parents=True, exist_ok=True)


def text(node):
    return node.get_text(' ', strip=True) if node else ''


def officer_url(href):
    if not href:
        return None
    u = urljoin(BASE, href.split('#')[0])
    p = urlparse(u)
    if p.netloc not in ('www.odmp.org', 'odmp.org'):
        return None
    return u if re.match(r'^/officer/\d+(?:/|$)', p.path) else None


def browse(page, url):
    response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(3500)
    if response and response.status >= 400:
        raise RuntimeError(f'ODMP HTTP {response.status} at {url}')
    return BeautifulSoup(page.content(), 'html.parser')


def homepage_links(soup):
    """Preserve visual DOM order; do not sort by guessed dates."""
    # Restrict to likely homepage recent-memorial sections where possible.
    candidates = []
    for node in soup.select('section, main, div'):
        label = ' '.join([str(node.get('id','')), ' '.join(node.get('class',[])), text(node.find(['h1','h2','h3']))]).lower()
        if any(k in label for k in ('recent', 'latest', 'fallen officers', 'recently fallen')):
            links = [officer_url(a.get('href')) for a in node.select('a[href]')]
            links = list(dict.fromkeys(u for u in links if u))
            if len(links) >= 10:
                candidates.append((len(links), links))
    if candidates:
        return sorted(candidates, key=lambda item:item[0])[0][1][:10]
    # Fallback: homepage officer links, first appearance. Review output before use.
    links = [officer_url(a.get('href')) for a in soup.select('a[href]')]
    return list(dict.fromkeys(u for u in links if u))[:10]


def meta(soup, key, attr='property'):
    tag = soup.find('meta', attrs={attr:key})
    return (tag.get('content') or '').strip() if tag else ''


def extract(page, url):
    soup = browse(page, url)
    h = soup.find('h1')
    title = text(h) or meta(soup, 'og:title')
    title = re.sub(r'\s*[-|]\s*Officer Down Memorial Page.*$', '', title, flags=re.I).strip()
    # These selectors are deliberately flexible; verify real ODMP structure.
    agency = ''
    for el in soup.select('[class*="agency"], [class*="department"], [data-testid*="agency"]'):
        value = text(el)
        if 4 < len(value) < 180:
            agency = value
            break
    full = text(soup)
    eow = ''
    m = re.search(r'(?:End of Watch|EOW)\s*[:\-]?\s*((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*)?(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}', full, re.I)
    if m:
        eow = (m.group(0).split(':',1)[-1] if ':' in m.group(0) else re.sub(r'^(?:End of Watch|EOW)\s*[- ]*', '', m.group(0), flags=re.I)).strip()
    photo = meta(soup,'og:image')
    if not photo:
        img = soup.select_one('main img, article img')
        if img:
            photo = img.get('src') or img.get('data-src') or ''
    photo = urljoin(BASE,photo) if photo else ''
    # Brief attributed excerpt, not a full copyrighted biography.
    story = ''
    for el in soup.select('[class*="bio"], [class*="incident"], [class*="narrative"], article p, main p'):
        s = text(el)
        if len(s) > 90 and not any(x in s.lower() for x in ('cookie policy','privacy policy','sign up')):
            story = s[:520].rsplit(' ',1)[0] + ('…' if len(s)>520 else '')
            break
    if not (title and agency and eow):
        raise ValueError(f'Incomplete officer record {url}: name={bool(title)}, agency={bool(agency)}, eow={bool(eow)}')
    return dict(name=title, agency=agency, eow=eow, story=story or 'Read the full memorial at ODMP.org.', photo=photo, url=url)


def save_image(session, record):
    url = record.get('photo')
    if not url or urlparse(url).netloc not in ('www.odmp.org','odmp.org'):
        return
    try:
        r = session.get(url, timeout=15, headers={'User-Agent':'MGPD memorial display contact site administrator for permissions'})
        r.raise_for_status()
        mime = r.headers.get('content-type','').split(';')[0]
        ext = {'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}.get(mime)
        if not ext or len(r.content)>5_000_000:
            return
        filename = hashlib.sha256(record['url'].encode()).hexdigest()[:18]+ext
        (IMAGES / filename).write_bytes(r.content)
        record['photo'] = 'images/'+filename
    except requests.RequestException as e:
        print('Image unavailable:', e)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36', viewport={'width':1440,'height':900})
        page = context.new_page()
        soup = browse(page, BASE)
        urls = homepage_links(soup)
        if len(urls) != 10:
            raise RuntimeError(f'Found {len(urls)} homepage officer links, expected exactly 10. Existing data preserved.')
        records = [extract(page, url) for url in urls]
        browser.close()
    with requests.Session() as session:
        for record in records:
            save_image(session,record)
    payload = dict(source=BASE, updated_at=datetime.now(timezone.utc).isoformat(), officers=records)
    # Atomic replacement only after all ten records validate.
    temp = DATA.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(DATA)
    print('Updated 10 records:', [r['name'] for r in records])


if __name__ == '__main__':
    main()
