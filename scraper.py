"""
scraper.py
----------
Discovers Japanese university professors by directly crawling MEXT university
faculty pages — no external API required.

Each university entry in config.yaml supplies a 'homepage' URL.
The scraper:
  1. Fetches the homepage and auto-discovers the faculty/staff listing page.
  2. Collects individual professor profile URLs from that listing.
     If the listing only shows department sub-lists, it follows one level deeper.
  3. Visits each professor page, extracts name / email / research interests /
     publication links.
  4. Returns a list of professor dicts for scorer.py.
"""

import os
import re
import time
import json
import yaml
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# ── HTTP session ──────────────────────────────────────────────────────────────

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
       'AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/124.0.0.0 Safari/537.36')

_session = requests.Session()
_session.headers.update({
    'User-Agent':      _UA,
    'Accept-Language': 'en-US,en;q=0.9,ja;q=0.8',
    'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
})

_domain_last: dict[str, float] = {}
_DELAY = 1.2   # seconds between requests to the same domain


def _fetch(url: str, timeout: int = 10) -> 'requests.Response | None':
    host = urlparse(url).netloc
    gap  = time.time() - _domain_last.get(host, 0)
    if gap < _DELAY:
        time.sleep(_DELAY - gap)
    _domain_last[host] = time.time()
    try:
        r = _session.get(url, timeout=timeout, allow_redirects=True)
        _domain_last[host] = time.time()
        if r.status_code == 429:
            print(f"  ⏳  Rate-limited — waiting 30 s...")
            time.sleep(30)
            r = _session.get(url, timeout=timeout, allow_redirects=True)
        return r if r.status_code == 200 else None
    except Exception:
        return None


def _abs(href: str, base: str) -> str:
    return urljoin(base, href).split('#')[0].rstrip('?')


def _same_domain(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc


def _base_url(soup: BeautifulSoup, page_url: str) -> str:
    tag = soup.find('base', href=True)
    return urljoin(page_url, tag['href']) if tag else page_url


def _is_valid_email(e: str) -> bool:
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', e))


# ── Faculty listing page discovery ───────────────────────────────────────────
#
# Score every link on the homepage. High-scoring links go to the faculty list.

_FACULTY_TEXT = {
    'faculty', 'faculty members', 'academic staff', 'staff', 'researchers',
    'members', 'professors', 'people', 'our faculty', 'teaching staff',
    'laboratories', 'graduate school/areas', 'areas',
    '教員', '教員一覧', '研究者', 'スタッフ',
}
_FACULTY_PATH = {
    'faculty', 'staff', 'member', 'members', 'people', 'professor',
    'professors', 'researcher', 'researchers', 'laboratory', 'laboratories',
    'teacher', 'teachers', 'academic', 'lab', 'labs',
    '教員', '教授', 'スタッフ', '研究者', '研究室',
}
_FACULTY_EXCL = {
    'news', 'event', 'admission', 'contact', 'access', 'sitemap',
    'privacy', 'login', 'alumni', 'curriculum', 'course', 'download',
    'about', 'overview', 'history', 'gallery', 'media', 'message',
}


def _find_faculty_url(homepage: str) -> str:
    resp = _fetch(homepage, timeout=15)
    if not resp:
        return homepage
    soup  = BeautifulSoup(resp.text, 'html.parser')
    base  = _base_url(soup, resp.url or homepage)
    best_score, best_url = 0, homepage

    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        if not href or href.startswith(('mailto:', 'javascript:', '#')):
            continue
        url  = _abs(href, base)
        if not _same_domain(url, homepage):
            continue
        path  = urlparse(url).path.lower()
        parts = set(re.split(r'[/\-_]', path))
        text  = a.get_text(strip=True).lower()

        score  = len(parts & _FACULTY_PATH) * 2
        score += sum(1 for k in _FACULTY_PATH if k in text)
        score += 5 if text in _FACULTY_TEXT else 0
        score -= len(parts & _FACULTY_EXCL) * 3

        if score > best_score:
            best_score, best_url = score, url

    return best_url


# ── Professor link detection ──────────────────────────────────────────────────

_PROF_PATH_KW = {
    'member', 'faculty', 'staff', 'professor', 'researcher',
    'lab', 'laboratory', 'people', 'teacher',
    '教員', '教授', '研究者', 'スタッフ',
}
_PROF_PATH_EXCL = {
    'news', 'event', 'contact', 'access', 'sitemap', 'search',
    'login', 'privacy', 'download', 'media', 'gallery', 'about',
    'admission', 'curriculum', 'alumni', 'overview', 'history',
}
_NAV_BLOCK = {
    'home', 'news', 'about', 'contact', 'access', 'sitemap', 'japanese',
    'english', 'top', 'back', 'more', 'search', 'login', 'menu', 'privacy',
    'map', 'link', 'links', 'admission', 'event', 'events', 'alumni',
    'course', 'courses', 'curriculum', 'download', '日本語',
    # Kyushu-style nav page titles
    'organization and history', 'features of isee', 'courses and subjects',
    'job opportunities', 'student voices', 'big projects with isee',
    'timetable / syllabus', 'academic calendar', 'student support',
    'information for foreign students', 'nationalities of international students',
    'brochure', 'three policies', 'student life', 'research facilities',
    'dean\'s message', 'international institutions',
}
_DEPT_WORDS = {
    'mathematics', 'science', 'engineering', 'computing', 'informatics',
    'systems', 'information', 'technology', 'department', 'division',
    'physical', 'applied', 'pure', 'bioinformatic', 'multimedia',
    'networking', 'electrical', 'electronic', 'mechanical', 'chemistry',
    'biology', 'physics', 'program', 'major', 'graduate', 'school',
    'institute', 'laboratory', 'laboratories', 'research', 'faculty',
    # Section/page title words (not personal names)
    'students', 'prospective', 'current', 'international', 'industrial',
    'collaborations', 'lectures', 'coursework', 'consultation', 'policy',
    'syllabus', 'curriculum', 'admission', 'admissions', 'overview',
    'opportunities', 'features', 'projects', 'facilities', 'support',
    'careers', 'career', 'alumni', 'alumnae', 'voices', 'brochure',
    'calendar', 'timetable', 'schedule', 'announcement', 'announcements',
    'procedures', 'scholarship', 'scholarships', 'dormitory', 'access',
    'directions', 'contact', 'publications', 'achievements', 'awards',
}
_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]')
_TITLE_PREFIXES = (
    'Professor', 'Associate Professor', 'Assistant Professor',
    'Lecturer', 'Dr.', 'Prof.',
)
_LIST_PAGE_JUNK = {
    'faculty members', 'faculty member', 'staff list', 'researchers',
    'academic staff', 'teaching staff', 'research staff', 'members',
    '教職員', 'スタッフリスト',
}


def _is_prof_link(href: str, text: str, base: str, resolved: str) -> bool:
    if not href or href.startswith(('mailto:', 'javascript:', '#')):
        return False
    parsed = urlparse(resolved)
    if not parsed.scheme or not parsed.netloc:
        return False
    if resolved.rstrip('/') == base.rstrip('/'):
        return False
    if not (_same_domain(resolved, base) or parsed.netloc.endswith('.ac.jp')):
        return False

    path  = parsed.path.lower()
    parts = set(re.split(r'[/\-_.]', path))
    last  = path.rstrip('/').rsplit('/', 1)[-1]

    # Hard exclude navigation and list/index pages
    if parts & _PROF_PATH_EXCL:
        return False
    if re.search(r'\blist\b', last) or last in ('index.php', 'index.html', 'index.htm', 'index'):
        return False

    # Pass 1: path keyword — only accept if link text is NOT a dept/subject/nav phrase
    if parts & _PROF_PATH_KW:
        t_chk = text.strip()
        for pfx in _TITLE_PREFIXES:
            if t_chk.startswith(pfx):
                t_chk = t_chk[len(pfx):].strip()
                break
        if t_chk.lower() in _NAV_BLOCK:
            return False
        words_chk = [w for w in t_chk.split() if w and w[0].isupper() and w.isalpha()]
        dept_ct = sum(1 for w in words_chk if w.lower() in _DEPT_WORDS)
        if not words_chk or dept_ct < len(words_chk) / 2:
            return True

    # Pass 2: strict personal name heuristic (same domain only)
    if not _same_domain(resolved, base):
        return False
    t = text.strip()
    if t.lower() in _NAV_BLOCK:
        return False
    # Strip academic title prefixes
    for pfx in _TITLE_PREFIXES:
        if t.startswith(pfx):
            t = t[len(pfx):].strip()
            break
    # CJK name: 2-4 CJK characters, short total text
    cjk = len(_CJK.findall(t))
    if cjk >= 2 and len(t) <= 20:
        depth = len([p for p in parsed.path.strip('/').split('/') if p])
        if depth >= 1:
            return True
    # Latin name: exactly 2-3 words total, each 2-15 chars, no dept/nav words
    all_words = t.split()
    if 2 <= len(all_words) <= 3:
        cap_words = [w for w in all_words if w and w[0].isupper() and w.isalpha()]
        dept_ct   = sum(1 for w in cap_words if w.lower() in _DEPT_WORDS)
        nav_ct    = sum(1 for w in all_words if w.lower() in _NAV_BLOCK)
        all_short = all(2 <= len(w) <= 15 for w in cap_words)
        if len(cap_words) >= 2 and dept_ct == 0 and nav_ct == 0 and all_short:
            depth = len([p for p in parsed.path.strip('/').split('/') if p])
            if depth >= 1:
                return True

    return False


# ── Collect professor URLs from listing page ──────────────────────────────────

def _collect_prof_urls(listing_url: str, cap: int = 15) -> list[tuple[str, str]]:
    """Return list of (url, link_text) for professor profile pages."""
    resp = _fetch(listing_url, timeout=15)
    if not resp:
        return []

    soup  = BeautifulSoup(resp.text, 'html.parser')
    base  = _base_url(soup, resp.url or listing_url)
    seen: set[str] = set()
    profs: list[tuple[str, str]] = []
    sublists: list[str] = []      # department sub-list pages to follow

    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        text = a.get_text(strip=True)
        if not href or href.startswith(('mailto:', 'javascript:', '#')):
            continue
        url = _abs(href, base)
        if url in seen:
            continue

        if _is_prof_link(href, text, listing_url, url):
            seen.add(url)
            profs.append((url, text))
        elif _same_domain(url, listing_url) or urlparse(url).netloc.endswith('.ac.jp'):
            # Detect department / sub-list pages
            pq   = urlparse(url).path.lower()
            last = pq.rstrip('/').rsplit('/', 1)[-1]
            is_sublist = (
                any(kw in pq for kw in (
                    '/majors/', '/major/', 'list.php', '/department', '/dept',
                    '/group/', '/laboratory/', '/laboratories/', '/lab/',
                    '/member/', '/members/', '/staff/', '/faculty/',
                ))
                or (last == '' and any(kw in pq for kw in
                    ('member', 'staff', 'faculty', 'researcher')))
            )
            if is_sublist and url not in sublists:
                sublists.append(url)

    # Always follow sub-list pages if found — prioritise CS/AI/informatics pages
    if sublists:
        # Sort: prefer CS/AI/informatics/computing pages first, list.php/researcher next
        def _sublist_priority(u: str) -> int:
            p = u.lower()
            if any(k in p for k in ('cs', 'computing', 'computer', 'informatics',
                                     'ai', 'intelligent', 'software', 'system',
                                     'network', 'information')):
                return 0
            if any(k in p for k in ('list.php', 'researcher', 'member', 'staff')):
                return 1
            if any(k in p for k in ('major', 'dept', 'department')):
                return 2
            return 3
        sublists_sorted = sorted(sublists, key=_sublist_priority)
        print(f"     ↘  Following {min(len(sublists_sorted),10)} sub-list page(s)...")
        for sub_url in sublists_sorted[:10]:
            sr = _fetch(sub_url, timeout=10)
            if not sr:
                continue
            ss   = BeautifulSoup(sr.text, 'html.parser')
            sb   = _base_url(ss, sr.url or sub_url)
            for a in ss.find_all('a', href=True):
                href = a.get('href', '').strip()
                text = a.get_text(strip=True)
                if not href or href.startswith(('mailto:', 'javascript:', '#')):
                    continue
                url = _abs(href, sb)
                if url not in seen and _is_prof_link(href, text, sub_url, url):
                    seen.add(url)
                    profs.append((url, text))
            if len(profs) >= cap:
                break
    elif len(profs) < 3:
        sample = [(a.get('href', '')[:50], a.get_text(strip=True)[:30])
                  for a in soup.find_all('a', href=True)[:6]]
        print(f"     ⚠  No professor links found. Page sample: {sample}")

    if len(profs) > cap:
        print(f"     ℹ  {len(profs)} prof links — capping at {cap}.")
    return profs[:cap]


# ── Extract data from a professor profile page ────────────────────────────────

_INTEREST_HEADS = {
    'research', 'interests', 'keywords', 'research interests',
    'research areas', 'research topics', 'research fields', 'research focus',
    'areas', 'focus', 'specialization', 'research keywords', 'research interest',
    '専門', '研究', 'キーワード', '研究分野', '専門分野', '研究テーマ',
}
_H_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'dt', 'th', 'strong', 'b'}

_PUB_DOMAINS = {
    'doi.org', 'arxiv.org', 'ieeexplore.ieee.org', 'dl.acm.org',
    'link.springer.com', 'researchgate.net', 'researchmap.jp',
}


def _extract_email(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a', href=True):
        if a['href'].startswith('mailto:'):
            e = a['href'][7:].split('?')[0].strip()
            if _is_valid_email(e):
                return e
    text = soup.get_text(separator=' ')
    for rep in (('[at]','@'),('(at)','@'),('（at）','@'),('＠','@'),
                ('[dot]','.'),('_at_','@')):
        text = text.replace(*rep)
    text = re.sub(r'\s+@\s+', '@', text)
    text = re.sub(r'(?<=[a-zA-Z0-9])\s+\.\s+(?=[a-zA-Z])', '.', text)
    m = re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
    if m:
        e = m.group(0).strip('.,;')
        if _is_valid_email(e) and not e.lower().endswith(('.png','.jpg','.gif')):
            return e
    return ''


def _extract_interests(soup: BeautifulSoup) -> list[str]:
    for tag in soup.find_all(_H_TAGS):
        head = tag.get_text(strip=True).lower()
        if head in _INTEREST_HEADS or any(h in head for h in _INTEREST_HEADS):
            parts: list[str] = []
            for sib in tag.next_siblings:
                sname = getattr(sib, 'name', None)
                if sname in {'h1','h2','h3','h4','h5','dt','th'}:
                    break
                if sname in {'ul','ol'}:
                    for li in sib.find_all('li'):
                        parts.append(li.get_text(strip=True))
                elif sname:
                    t = sib.get_text(strip=True)
                    if t:
                        parts.append(t)
                else:
                    t = str(sib).strip()
                    if t:
                        parts.append(t)
            result = []
            for p in parts:
                for seg in re.split(r'[,;\n\r]+', p):
                    seg = seg.strip('・•–—·\t ')
                    if len(seg) >= 3:
                        result.append(seg)
            if result:
                return result[:10]
    return []


def _find_pub_links(soup: BeautifulSoup, base: str) -> list[str]:
    found: list[str] = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        url  = _abs(href, base)
        if urlparse(url).netloc in _PUB_DOMAINS or href.lower().endswith('.pdf'):
            if url not in found:
                found.append(url)
        if len(found) >= 3:
            break
    return found[:3]


def _fetch_paper(url: str) -> dict:
    if url.lower().endswith('.pdf'):
        return {'title': url.split('/')[-1], 'abstract': '', 'url': url}
    resp = _fetch(url, timeout=8)
    if not resp:
        return {'title': url, 'abstract': '', 'url': url}
    soup = BeautifulSoup(resp.text, 'html.parser')
    title = ''
    h1 = soup.find('h1')
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        t = soup.find('title')
        if t:
            title = t.get_text(strip=True).split('|')[0].split('—')[0].strip()
    abstract = ''
    for meta in soup.find_all('meta'):
        n = meta.get('name','') or meta.get('property','')
        if n in ('description','og:description'):
            abstract = meta.get('content','')
            break
    if not abstract:
        for el in soup.find_all(['section','div','p']):
            cls = ' '.join(el.get('class',[]) + [el.get('id','')]).lower()
            if 'abstract' in cls:
                abstract = el.get_text(strip=True)
                break
    return {'title': (title or url)[:200], 'abstract': abstract[:400], 'url': url}


def _scrape_professor(url: str, uni_name: str, link_text: str = '') -> 'dict | None':
    """Scrape one professor profile page. Uses link_text as name fallback."""
    resp = _fetch(url, timeout=8)
    # Even if page fails, we can still create a stub from link_text
    soup = BeautifulSoup(resp.text if resp else '', 'html.parser')

    # ── Name ─────────────────────────────────────────────────────────────────
    name = ''
    # 1. h1 / h2
    for tag_name in ('h1', 'h2'):
        t = soup.find(tag_name)
        if t:
            name = t.get_text(strip=True)
            break
    # 2. Common class names
    if not name:
        for cls in ('name','researcher-name','prof-name','faculty-name',
                    'person-name','researcher_name','staff-name'):
            el = soup.find(class_=re.compile(cls, re.I))
            if el:
                c = el.get_text(strip=True)
                if 2 < len(c) < 60:
                    name = c
                    break
    # 3. meta author
    if not name:
        m = soup.find('meta', attrs={'name': 'author'})
        if m:
            name = m.get('content', '').strip()
    # 4. page title (first segment)
    if not name:
        t = soup.find('title')
        if t:
            raw = t.get_text(strip=True)
            for sep in ('|', '—', '-', '–', '·', '/'):
                if sep in raw:
                    raw = raw.split(sep)[0]
            name = raw.strip()

    # Clean: strip rank prefixes, trailing qualifiers, and page suffixes
    for rank in ('Specially-appointed Associate Professor',
                 'Specially-appointed Professor',
                 'Specially-appointed Assistant Professor',
                 'Associate Professor', 'Assistant Professor',
                 'Assoc. Prof.', 'Assist. Prof.', 'Prof.', 'Dr.'):
        if name.startswith(rank):
            name = name[len(rank):].strip()
            break
    name = re.sub(r'\s*\(concurr\w*\)\s*$', '', name, flags=re.I).strip()
    name = re.sub(r'\s+', ' ', name).strip()

    for sfx in (uni_name, 'Laboratory', 'Lab', 'Department', 'Professor',
                'Graduate School', 'Research Group', 'Faculty Members',
                'Faculty Member', 'Staff List', 'Researchers', 'Academic Staff'):
        if name.endswith(sfx):
            name = name[:-len(sfx)].strip('— ,-|')

    # Reject if name looks like a list-page title
    if any(ind in name.lower() for ind in _LIST_PAGE_JUNK):
        name = ''

    # Fallback: use the link text from the listing page
    if not name and link_text:
        c = link_text.strip()
        for pfx in ('Specially-appointed Associate Professor',
                    'Specially-appointed Professor',
                    'Specially-appointed Assistant Professor',
                    'Associate Professor', 'Assistant Professor') + _TITLE_PREFIXES:
            if c.startswith(pfx):
                c = c[len(pfx):].strip()
                break
        c = re.sub(r'\s*\(concurr\w*\)\s*$', '', c, flags=re.I).strip()
        c = re.sub(r'\s+', ' ', c).strip()
        if 2 < len(c) < 60:
            name = c

    if not name or len(name) > 80:
        return None

    # Skip if we have no page content at all AND no link-text-derived name
    if not resp and not link_text:
        return None

    # ── Other fields ──────────────────────────────────────────────────────────
    email     = _extract_email(resp.text) if resp else ''
    interests = _extract_interests(soup)
    pub_links = _find_pub_links(soup, url)
    papers    = [_fetch_paper(p) for p in pub_links]

    department = ''
    for el in soup.find_all(['p','div','span','td','li']):
        t = el.get_text(strip=True)
        if any(k in t for k in ('Laboratory','Lab','Department','Division',
                                '研究室','学部','専攻')) and len(t) < 120:
            department = t
            break

    return {
        'permalink':  f"{uni_name}::{url}",
        'name':       name,
        'university': uni_name,
        'department': department,
        'lab_url':    url,
        'source_url': url,
        'email':      email,
        'interests':  interests,
        'papers':     papers,
    }


# ── University crawler ────────────────────────────────────────────────────────

def crawl_university(entry: dict) -> list[dict]:
    name     = entry['name']
    homepage = entry.get('homepage') or entry.get('faculty_url', '')
    if not homepage:
        print(f"  ⚠  No homepage for {name} — skipping.")
        return []

    print(f"  🔍  {name}")
    listing = _find_faculty_url(homepage)
    if listing == homepage:
        print(f"     ↩  Using homepage directly")
    else:
        print(f"     ✓  Faculty page: {listing}")

    items = _collect_prof_urls(listing, cap=15)
    print(f"     →  {len(items)} professor URLs")
    if not items:
        return []

    profs: list[dict] = []
    for url, link_text in items:
        p = _scrape_professor(url, name, link_text=link_text)
        if p:
            profs.append(p)
            print(f"       + {p['name']}  "
                  f"{'✉ ' + p['email'] if p['email'] else '(no email)'}  "
                  f"interests:{len(p['interests'])}  papers:{len(p['papers'])}")
    return profs


# ── discover_professors (called by discoverer.py) ─────────────────────────────

def discover_professors(
    applicant_profile: dict,
    target_universities_only: bool = True,
    cache_path: str = 'scraper_cache.json',
    keywords: 'list | None' = None,
    max_per_keyword: int = 20,
) -> list[dict]:
    with open('config.yaml', 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    universities = cfg.get('discovery', {}).get('universities', [])
    if not universities:
        print("  ⚠  No universities in config.yaml.")
        return []

    cache: dict = {}
    if os.path.isfile(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            try:
                cache = json.load(f)
            except json.JSONDecodeError:
                cache = {}
        if cache:
            print(f"  📦  Cache loaded ({len(cache)} professors).")

    seen    = set(cache.keys())
    results = list(cache.values())

    for entry in universities:
        print(f"\n  🏫  {entry.get('name','?')}")
        for p in crawl_university(entry):
            pk = p.get('permalink', '')
            if pk and pk not in seen:
                seen.add(pk)
                results.append(p)
                cache[pk] = p
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\n  ✅  Total: {len(results)} professors found.")
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse, sys
    parser = argparse.ArgumentParser(description='Crawl MEXT university faculty pages')
    parser.add_argument('university', nargs='?', help='University name (partial match)')
    parser.add_argument('--all', action='store_true', help='Crawl all universities')
    args = parser.parse_args()

    with open('config.yaml', 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    unis = cfg['discovery']['universities']

    if args.all:
        targets = unis
    elif args.university:
        targets = [u for u in unis if args.university.lower() in u['name'].lower()]
        if not targets:
            print(f"No match for '{args.university}'. Available: {[u['name'] for u in unis]}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(0)

    for entry in targets:
        profs = crawl_university(entry)
        print(f"\n── {entry['name']} ── {len(profs)} professor(s) ──")
        for p in profs:
            print(f"  {p['name']}  |  {p['email'] or 'no email'}  |  {p['interests'][:2]}")
