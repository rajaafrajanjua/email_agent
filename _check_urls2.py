"""
Phase 2 URL checks — navigate from homepages to find faculty listing pages.
"""
import requests
from bs4 import BeautifulSoup
import re

TIMEOUT = 15
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

sess = requests.Session()
sess.headers.update({"User-Agent": UA})


def get(url):
    try:
        r = sess.get(url, timeout=TIMEOUT, allow_redirects=True)
        return r
    except Exception as e:
        return None


def score(html):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    if body:
        visible = body.get_text(separator=" ", strip=True)
        if len(visible) < 200:
            return False, "possibly JS-rendered"
    text = soup.get_text(" ", strip=True)
    latin_names = re.findall(r'\b[A-Z][a-z]{1,15}\s+[A-Z][a-z]{1,20}\b', text)
    cjk_names = re.findall(r'[\u4e00-\u9fff\u3040-\u30ff]{2,5}', text)
    prof_keywords = {'member', 'faculty', 'staff', 'professor', 'researcher', 'lab', 'people', 'teachers', 'laboratory'}
    prof_links = sum(1 for a in soup.find_all("a", href=True) if any(k in a["href"].lower() for k in prof_keywords))
    reasons = []
    if len(latin_names) >= 3:
        reasons.append(f"{len(latin_names)} Latin names")
    if len(cjk_names) >= 5:
        reasons.append(f"{len(cjk_names)} CJK names")
    if prof_links >= 3:
        reasons.append(f"{prof_links} prof-links")
    ok = bool(reasons)
    return ok, (", ".join(reasons) if reasons else f"latin={len(latin_names)},cjk={len(cjk_names)},prof_links={prof_links}")


def explore_homepage_links(homepage_url, label):
    """Find internal links from homepage that likely lead to faculty listings."""
    r = get(homepage_url)
    if not r or r.status_code != 200:
        print(f"  ❌ Homepage unreachable: {homepage_url}")
        return
    soup = BeautifulSoup(r.text, "html.parser")
    # Collect ALL links
    from urllib.parse import urljoin, urlparse
    base = urlparse(homepage_url)
    FACULTY_KEYWORDS = {'faculty', 'staff', 'member', 'people', 'professor',
                        'researcher', 'laboratory', 'research', 'academic',
                        'department', 'division', 'school', 'graduate'}
    print(f"\n  Links on {label} ({homepage_url}):")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        abs_href = urljoin(homepage_url, href)
        p = urlparse(abs_href)
        if p.netloc != base.netloc:
            continue
        path_lower = p.path.lower()
        if any(k in path_lower or k in text for k in FACULTY_KEYWORDS):
            print(f"    → [{text[:50]}] {abs_href}")


# ──────────────────────────────────────────────────────────────
# NAIST — DNS failed on is.naist.jp; try alternate domains
print("="*60)
print("NAIST")
for url in [
    "https://www.naist.jp/en/academics/",
    "https://www.naist.jp/en/faculty/",
    "https://www.naist.jp/en/research/",
    "https://ds.naist.jp/en/faculty/",
    "https://bs.naist.jp/en/faculty/",
]:
    r = get(url)
    if r:
        ok, reason = score(r.text) if r.status_code == 200 else (False, "non-200")
        flag = "✅" if ok else "⚠️ "
        print(f"  {flag} [{r.status_code}] {url} → {reason}")
    else:
        print(f"  ❌ [ERR] {url}")

explore_homepage_links("https://www.naist.jp/en/", "NAIST")

# ──────────────────────────────────────────────────────────────
# Tsukuba — all /faculty/ paths 404'd
print("\n" + "="*60)
print("Tsukuba")
for url in [
    "https://www.cs.tsukuba.ac.jp/en/",
    "https://www.cs.tsukuba.ac.jp/en/people/",
    "https://www.coins.tsukuba.ac.jp/en/",
    "https://www.coins.tsukuba.ac.jp/en/people/",
    "https://www.tsukuba.ac.jp/en/academics/",
    "https://www.sie.tsukuba.ac.jp/eng/members/",
    "https://www.cs.tsukuba.ac.jp/en/academic-staff/",
    "https://www.coins.tsukuba.ac.jp/en/academic-staff/",
    "https://www.cs.tsukuba.ac.jp/en/about/faculty.html",
]:
    r = get(url)
    if r:
        ok, reason = score(r.text) if r.status_code == 200 else (False, "non-200")
        flag = "✅" if ok else "⚠️ "
        print(f"  {flag} [{r.status_code}] {url} → {reason}")
    else:
        print(f"  ❌ [ERR] {url}")

explore_homepage_links("https://www.cs.tsukuba.ac.jp/en/", "Tsukuba CS")
explore_homepage_links("https://www.coins.tsukuba.ac.jp/en/", "Tsukuba COINS")

# ──────────────────────────────────────────────────────────────
# Kyoto IST — all 404'd
print("\n" + "="*60)
print("Kyoto IST")
for url in [
    "https://www.ist.i.kyoto-u.ac.jp/en/",
    "https://www.ist.i.kyoto-u.ac.jp/en/members/",
    "https://www.ist.i.kyoto-u.ac.jp/en/faculty/",
    "https://www.i.kyoto-u.ac.jp/en/",
    "https://www.i.kyoto-u.ac.jp/en/research/",
    "https://www.i.kyoto-u.ac.jp/en/people/",
    "https://www.ist.i.kyoto-u.ac.jp/",
]:
    r = get(url)
    if r:
        ok, reason = score(r.text) if r.status_code == 200 else (False, "non-200")
        flag = "✅" if ok else "⚠️ "
        print(f"  {flag} [{r.status_code}] {url} → {reason}")
    else:
        print(f"  ❌ [ERR] {url}")

explore_homepage_links("https://www.ist.i.kyoto-u.ac.jp/en/", "Kyoto IST")

# ──────────────────────────────────────────────────────────────
# Kyushu — ait.kyushu-u.ac.jp DNS failed; inf.kyushu-u.ac.jp 404'd
print("\n" + "="*60)
print("Kyushu")
for url in [
    "https://www.kyushu-u.ac.jp/en/faculties/",
    "https://www.i.kyushu-u.ac.jp/en/",
    "https://www.i.kyushu-u.ac.jp/en/faculty/",
    "https://www.i.kyushu-u.ac.jp/en/members/",
    "https://www.inf.kyushu-u.ac.jp/",
    "https://www.inf.kyushu-u.ac.jp/en/people/",
    "https://www.inf.kyushu-u.ac.jp/en/laboratory/",
    "https://www.kyushu-u.ac.jp/en/education/graduate/",
]:
    r = get(url)
    if r:
        ok, reason = score(r.text) if r.status_code == 200 else (False, "non-200")
        flag = "✅" if ok else "⚠️ "
        print(f"  {flag} [{r.status_code}] {url} → {reason}")
    else:
        print(f"  ❌ [ERR] {url}")

# ──────────────────────────────────────────────────────────────
# UTokyo i-school — homepage only had 9 names; look for better page
print("\n" + "="*60)
print("UTokyo i-school")
explore_homepage_links("https://www.i.u-tokyo.ac.jp/", "UTokyo i-school")
for url in [
    "https://www.i.u-tokyo.ac.jp/en/",
    "https://www.i.u-tokyo.ac.jp/en/faculty/",
    "https://www.i.u-tokyo.ac.jp/en/staff/",
    "https://www.i.u-tokyo.ac.jp/research/lab/",
]:
    r = get(url)
    if r:
        ok, reason = score(r.text) if r.status_code == 200 else (False, "non-200")
        flag = "✅" if ok else "⚠️ "
        print(f"  {flag} [{r.status_code}] {url} → {reason}")
    else:
        print(f"  ❌ [ERR] {url}")

# ──────────────────────────────────────────────────────────────
# Osaka IST homepage — see what faculty/member links exist
print("\n" + "="*60)
print("Osaka IST — explore homepage links")
explore_homepage_links("https://www.ist.osaka-u.ac.jp/english/", "Osaka IST")

# ──────────────────────────────────────────────────────────────
# Nagoya — homepage found; look for more specific faculty page
print("\n" + "="*60)
print("Nagoya — explore homepage links")
explore_homepage_links("https://www.i.nagoya-u.ac.jp/en/", "Nagoya GSI")
for url in [
    "https://www.i.nagoya-u.ac.jp/en/staff/",
    "https://www.i.nagoya-u.ac.jp/en/people/",
    "https://www.i.nagoya-u.ac.jp/en/member/",
    "https://www.i.nagoya-u.ac.jp/en/research/",
    "https://www.i.nagoya-u.ac.jp/en/laboratory/",
]:
    r = get(url)
    if r:
        ok, reason = score(r.text) if r.status_code == 200 else (False, "non-200")
        flag = "✅" if ok else "⚠️ "
        print(f"  {flag} [{r.status_code}] {url} → {reason}")
    else:
        print(f"  ❌ [ERR] {url}")
