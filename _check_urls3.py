"""
Phase 3 — Verify specific discovered URLs and check Kyushu alternatives.
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
        print(f"  ❌ ERR {url}: {e}")
        return None


def score(html, label=""):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    if body:
        visible = body.get_text(separator=" ", strip=True)
        if len(visible) < 200:
            return False, "possibly JS-rendered (short body)"
    text = soup.get_text(" ", strip=True)
    latin_names = re.findall(r'\b[A-Z][a-z]{1,15}\s+[A-Z][a-z]{1,20}\b', text)
    cjk_names = re.findall(r'[\u4e00-\u9fff\u3040-\u30ff]{2,5}', text)
    prof_keywords = {'member', 'faculty', 'staff', 'professor', 'researcher', 'lab', 'people', 'teachers', 'laboratory'}
    prof_links = 0
    profile_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(k in href for k in prof_keywords):
            prof_links += 1
            profile_links.append(a["href"])
    reasons = []
    if len(latin_names) >= 3:
        reasons.append(f"{len(latin_names)} Latin names")
    if len(cjk_names) >= 5:
        reasons.append(f"{len(cjk_names)} CJK names")
    if prof_links >= 2:
        reasons.append(f"{prof_links} prof-links")
    ok = bool(reasons)
    sample_links = profile_links[:5] if profile_links else []
    return ok, (", ".join(reasons) if reasons else f"insufficient (ln={len(latin_names)},cjk={len(cjk_names)},pl={prof_links})"), sample_links


def check(url, label=""):
    r = get(url)
    if not r:
        return
    if r.status_code != 200:
        print(f"  ❌ [{r.status_code}] {url}")
        return
    ok, reason, sample = score(r.text)
    flag = "✅" if ok else "⚠️ "
    print(f"  {flag} [{r.status_code}] {url}")
    print(f"       {reason}")
    if sample:
        print(f"       sample prof links: {sample[:3]}")


print("="*65)
print("Osaka IST — researcher page")
check("https://www.ist.osaka-u.ac.jp/english/researcher/")
check("https://www.ist.osaka-u.ac.jp/english/researcher/list.php?id=3")  # CS dept

print("\n" + "="*65)
print("Nagoya — department faculty pages")
for url in [
    "https://www.i.nagoya-u.ac.jp/en/prof/mathematical/",
    "https://www.i.nagoya-u.ac.jp/en/prof/study_a06/",   # Computing & SW
    "https://www.i.nagoya-u.ac.jp/en/prof/study_a07/",   # Intelligent Systems
    "https://www.i.nagoya-u.ac.jp/en/prof/study_a03/",   # Complex Systems
]:
    check(url)

print("\n" + "="*65)
print("Kyoto — i.kyoto-u.ac.jp research page")
check("https://www.i.kyoto-u.ac.jp/en/research/")

print("\n" + "="*65)
print("Kyoto IST — ist.i.kyoto-u.ac.jp main page (has CJK)")
r = get("https://www.ist.i.kyoto-u.ac.jp/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    from urllib.parse import urljoin, urlparse
    base = urlparse("https://www.ist.i.kyoto-u.ac.jp/")
    print("  Links on ist.i.kyoto-u.ac.jp:")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        abs_href = urljoin("https://www.ist.i.kyoto-u.ac.jp/", href)
        p = urlparse(abs_href)
        keywords = {'faculty', 'staff', 'member', 'people', 'professor', 'researcher', 'lab', 'academic'}
        if any(k in p.path.lower() or k in text for k in keywords):
            print(f"    [{text[:50]}] {abs_href}")

print("\n" + "="*65)
print("Kyushu — checking alternative domains")
for url in [
    "https://kyushu-u.ac.jp/en/",
    "https://www.kyushu-u.ac.jp/en/",
    "https://www.kyushu-u.ac.jp/en/faculties/f_is.html",
    "https://www.kyushu-u.ac.jp/en/faculties/",
    "https://www.cis.kyushu-u.ac.jp/",
    "https://www.cis.kyushu-u.ac.jp/en/",
    "https://www.cis.kyushu-u.ac.jp/en/faculty.html",
    "https://www.cis.kyushu-u.ac.jp/en/staff/",
    "https://ait.kyushu-u.ac.jp/en/",
    "https://inf.kyushu-u.ac.jp/en/",
]:
    r = get(url)
    if not r:
        continue
    ok, reason, sample = score(r.text) if r.status_code == 200 else (False, "non-200", [])
    flag = "✅" if ok else "⚠️ "
    print(f"  {flag} [{r.status_code}] {url} → {reason}")

print("\n" + "="*65)
print("NAIST — checking /en/academics/ sub-links for faculty")
r = get("https://www.naist.jp/en/academics/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    from urllib.parse import urljoin, urlparse
    print("  All links on /en/academics/:")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        abs_href = urljoin("https://www.naist.jp/en/academics/", href)
        p = urlparse(abs_href)
        keywords = {'faculty', 'staff', 'member', 'people', 'professor', 'researcher', 'lab', 'academic', 'program'}
        if any(k in p.path.lower() for k in keywords):
            print(f"    [{text[:50]}] {abs_href}")

print("\n" + "="*65)
print("UTokyo i-school — check shtml pages")
for url in [
    "https://www.i.u-tokyo.ac.jp/edu/member.shtml",
    "https://www.i.u-tokyo.ac.jp/about/members.shtml",
    "https://www.i.u-tokyo.ac.jp/about/staff/index.shtml",
    "https://www.i.u-tokyo.ac.jp/research/lab/index.shtml",
    "https://www.i.u-tokyo.ac.jp/edu/faculty.shtml",
]:
    r = get(url)
    if not r:
        continue
    ok, reason, sample = score(r.text) if r.status_code == 200 else (False, "non-200", [])
    flag = "✅" if ok else "⚠️ "
    print(f"  {flag} [{r.status_code}] {url} → {reason}")
    if sample:
        print(f"       sample: {sample[:2]}")

print("\n" + "="*65)
print("JAIST — /english/areas/ page content + sub-links")
r = get("https://www.jaist.ac.jp/english/areas/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    from urllib.parse import urljoin, urlparse
    print("  Faculty / staff links on /english/areas/:")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        abs_href = urljoin("https://www.jaist.ac.jp/english/areas/", href)
        p = urlparse(abs_href)
        if any(k in p.path.lower() or k in text for k in ('faculty','staff','member','people','professor','researcher','lab')):
            print(f"    [{text[:50]}] {abs_href}")
