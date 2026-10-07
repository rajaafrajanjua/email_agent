"""Phase 4 — Final targeted URL checks."""
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
    prof_keywords = {'member','faculty','staff','professor','researcher','lab','people','teachers','laboratory'}
    prof_links = sum(1 for a in soup.find_all("a", href=True) if any(k in a["href"].lower() for k in prof_keywords))
    profile_links = [a["href"] for a in soup.find_all("a", href=True)
                     if any(k in a["href"].lower() for k in prof_keywords)]
    reasons = []
    if len(latin_names) >= 3:
        reasons.append(f"{len(latin_names)} Latin names")
    if len(cjk_names) >= 5:
        reasons.append(f"{len(cjk_names)} CJK names")
    if prof_links >= 2:
        reasons.append(f"{prof_links} prof-links")
    ok = bool(reasons)
    return ok, (", ".join(reasons) if reasons else f"insufficient"), profile_links[:5]


def check(url):
    r = get(url)
    if not r:
        return
    if r.status_code != 200:
        print(f"  ❌ [{r.status_code}] {url}")
        return
    ok, reason, samples = score(r.text)
    flag = "✅" if ok else "⚠️ "
    print(f"  {flag} [{r.status_code}] {url}")
    print(f"       → {reason}")
    if samples:
        print(f"       sample links: {samples[:3]}")


# Kyoto — /en/faculty/ was referenced in links on /en/research/
print("Kyoto — faculty page")
check("https://www.i.kyoto-u.ac.jp/en/faculty/")
check("https://www.i.kyoto-u.ac.jp/en/faculty/organization/")
check("https://www.i.kyoto-u.ac.jp/en/research/laboratory/")

# Kyushu — www.kyushu-u.ac.jp main site works; find faculty
print("\nKyushu — navigate from homepage")
r = get("https://www.kyushu-u.ac.jp/en/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    from urllib.parse import urljoin, urlparse
    keywords = {'faculty','staff','member','people','professor','researcher','lab','academic','graduate','school'}
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        abs_href = urljoin("https://www.kyushu-u.ac.jp/en/", href)
        p = urlparse(abs_href)
        if p.netloc and 'kyushu-u.ac.jp' in p.netloc:
            if any(k in p.path.lower() or k in text for k in keywords):
                if abs_href not in seen:
                    seen.add(abs_href)
                    print(f"    [{text[:50]}] {abs_href}")

# Check specific Kyushu faculty pages
print("\nKyushu — specific URLs")
for url in [
    "https://www.kyushu-u.ac.jp/en/faculties/graduate-school-of-information-science-and-electrical-engineering/",
    "https://www.kyushu-u.ac.jp/en/faculties/graduate/",
    "https://www.kyushu-u.ac.jp/en/research/faculty/",
    "https://www.kyushu-u.ac.jp/en/education/graduate/isee/",
]:
    check(url)

# Tsukuba — coins.tsukuba.ac.jp has 32 Latin names, look for faculty links
print("\nTsukuba — COINS faculty links")
r = get("https://www.coins.tsukuba.ac.jp/en/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    from urllib.parse import urljoin, urlparse
    keywords = {'faculty','staff','member','people','professor','researcher','lab','academic'}
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        abs_href = urljoin("https://www.coins.tsukuba.ac.jp/en/", href)
        p = urlparse(abs_href)
        if any(k in p.path.lower() or k in text for k in keywords):
            if abs_href not in seen:
                seen.add(abs_href)
                print(f"    [{text[:50]}] {abs_href}")

for url in [
    "https://www.coins.tsukuba.ac.jp/en/staff/",
    "https://www.coins.tsukuba.ac.jp/en/member/",
    "https://www.coins.tsukuba.ac.jp/en/professor/",
    "https://www.coins.tsukuba.ac.jp/en/faculty-members/",
    "https://www.coins.tsukuba.ac.jp/en/about/",
    "https://www.coins.tsukuba.ac.jp/en/organization/",
]:
    check(url)

# NAIST — /en/academics/ had 103 Latin names but no clear faculty links
# Check the NAIST division pages directly
print("\nNAIST — division pages")
for url in [
    "https://www.naist.jp/en/academics/#educational-programs",
    "https://is.naist.jp/en/",          # was DNS error before, retry
    "https://naist.jp/en/",             # was DNS error before, retry
]:
    check(url)

# UTokyo — check /edu/ sub pages via the link found
print("\nUTokyo i-school — shtml pages")
for url in [
    "https://www.i.u-tokyo.ac.jp/edu/entra/research_students_e.shtml",
    "https://www.i.u-tokyo.ac.jp/edu/staff_e.shtml",
    "https://www.i.u-tokyo.ac.jp/edu/faculty_e.shtml",
    "https://www.i.u-tokyo.ac.jp/research/lab/index.shtml",
    "https://www.i.u-tokyo.ac.jp/research/lab/",
]:
    check(url)

# JAIST — try to get a professor listing from /english/areas/
print("\nJAIST — testing sub-area faculty pages")
for url in [
    "https://www.jaist.ac.jp/english/areas/is/",
    "https://www.jaist.ac.jp/english/areas/ait/",
    "https://www.jaist.ac.jp/english/areas/jais/",
    "https://www.jaist.ac.jp/is/labs/",
    "https://www.jaist.ac.jp/is/labs/index-e.html",
    "https://www.jaist.ac.jp/is/staff/",
    "https://www.jaist.ac.jp/is/staff/index-e.html",
]:
    check(url)

# TiTech — educ.titech.ac.jp/cs/eng/faculty/ was best, verify links
print("\nTiTech — verify faculty page")
check("https://educ.titech.ac.jp/cs/eng/faculty/")
r = get("https://educ.titech.ac.jp/cs/eng/faculty/")
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    from urllib.parse import urljoin
    print("  Sample profile links:")
    count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        abs_href = urljoin("https://educ.titech.ac.jp/cs/eng/faculty/", href)
        if 'staff' in href.lower() or 'faculty' in href.lower() or 'member' in href.lower():
            print(f"    [{text[:50]}] {abs_href}")
            count += 1
            if count >= 8:
                break
