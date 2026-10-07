"""
Checks all candidate faculty URLs, prints HTTP status and whether
professor names / profile links are visible in HTML (non-JS-rendered).
"""
import requests
from bs4 import BeautifulSoup

TIMEOUT = 15
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

sess = requests.Session()
sess.headers.update({"User-Agent": UA})

CANDIDATES = {
    "NAIST": [
        "https://is.naist.jp/en/laboratory/",
        "https://is.naist.jp/en/faculty/",
        "https://naist.jp/en/academics/",
    ],
    "JAIST": [
        "https://www.jaist.ac.jp/english/areas/ait/faculty/",
        "https://www.jaist.ac.jp/english/faculty/",
        "https://www.jaist.ac.jp/english/areas/is/faculty/",
        "https://www.jaist.ac.jp/english/areas/",
    ],
    "Tsukuba": [
        "https://www.cs.tsukuba.ac.jp/en/faculty/",
        "https://www.coins.tsukuba.ac.jp/en/faculty/",
        "https://www.cs.tsukuba.ac.jp/en/people/",
        "https://www.cs.tsukuba.ac.jp/en/staff/",
    ],
    "Kyoto IST": [
        "https://www.ist.i.kyoto-u.ac.jp/en/people/",
        "https://www.ist.i.kyoto-u.ac.jp/en/research/",
        "https://www.ist.i.kyoto-u.ac.jp/research/professor.html",
        "https://www.ist.i.kyoto-u.ac.jp/en/laboratory/",
    ],
    "Osaka IST": [
        "https://www.ist.osaka-u.ac.jp/english/faculty/",
        "https://www.ist.osaka-u.ac.jp/english/staff/",
        "https://www.ist.osaka-u.ac.jp/english/research/professor/",
        "https://www.ist.osaka-u.ac.jp/english/",
    ],
    "Tohoku": [
        "https://www.is.tohoku.ac.jp/en/laboratory/",
        "https://www.riec.tohoku.ac.jp/en/introduction/member/",
        "https://www.is.tohoku.ac.jp/en/faculty/",
        "https://www.is.tohoku.ac.jp/en/",
    ],
    "Nagoya": [
        "https://www.i.nagoya-u.ac.jp/en/faculty/",
        "https://www.ttic.nagoya-u.ac.jp/en/members.html",
        "https://www.i.nagoya-u.ac.jp/en/",
    ],
    "Kyushu": [
        "https://www.ait.kyushu-u.ac.jp/en/faculty/",
        "https://www.inf.kyushu-u.ac.jp/en/faculty/",
        "https://www.ait.kyushu-u.ac.jp/en/",
        "https://www.inf.kyushu-u.ac.jp/en/",
    ],
    "UTokyo i-school": [
        "https://www.i.u-tokyo.ac.jp/faculty/",
        "https://www.i.u-tokyo.ac.jp/about/staff.shtml",
        "https://www.i.u-tokyo.ac.jp/people/",
        "https://www.i.u-tokyo.ac.jp/about/",
        "https://www.i.u-tokyo.ac.jp/",
    ],
    "Waseda GIPS": [
        "https://www.waseda.jp/fsci/gips/en/faculty/",
        "https://www.waseda.jp/fsci/gips/en/about/faculty/",
        "https://www.waseda.jp/fsci/gips/en/",
    ],
    "Keio ICS": [
        "https://www.ics.keio.ac.jp/faculty/",
        "https://www.ics.keio.ac.jp/en/faculty/",
        "https://www.ics.keio.ac.jp/",
    ],
    "TiTech": [
        "https://educ.titech.ac.jp/cs/eng/faculty/",
        "https://www.titech.ac.jp/english/research/faculty/",
        "https://www.c.titech.ac.jp/en/member/",
        "https://www.titech.ac.jp/english/",
    ],
}


def score_page(html: str) -> tuple[bool, str]:
    """Return (has_prof_content, reason) by inspecting HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Detect JS-rendered shell (nearly empty body)
    body = soup.body
    if body:
        visible = body.get_text(separator=" ", strip=True)
        if len(visible) < 200:
            # Check for React/Angular/Vue root divs
            ng = soup.find(id="app") or soup.find(id="root") or soup.find(attrs={"ng-app": True})
            if ng:
                return False, "JS-rendered (React/Angular root, empty body)"
            return False, f"Very short body ({len(visible)} chars) — possibly JS-rendered"

    # Count English name-like patterns (First Last)
    import re
    text = soup.get_text(" ", strip=True)
    latin_names = re.findall(r'\b[A-Z][a-z]{1,15}\s+[A-Z][a-z]{1,20}\b', text)
    # Count CJK name-like sequences
    cjk_names = re.findall(r'[\u4e00-\u9fff\u3040-\u30ff]{2,5}', text)

    # Count links that look like profile pages
    prof_keywords = {'member', 'faculty', 'staff', 'professor', 'researcher',
                     'lab', 'people', 'teachers', 'laboratory'}
    prof_links = 0
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(k in href for k in prof_keywords):
            prof_links += 1

    reasons = []
    if len(latin_names) >= 3:
        reasons.append(f"{len(latin_names)} Latin names")
    if len(cjk_names) >= 5:
        reasons.append(f"{len(cjk_names)} CJK name-patterns")
    if prof_links >= 3:
        reasons.append(f"{prof_links} prof-like links")

    if reasons:
        return True, ", ".join(reasons)
    return False, f"no clear prof content (latin_names={len(latin_names)}, cjk={len(cjk_names)}, prof_links={prof_links})"


print("="*70)
print("URL CHECK RESULTS")
print("="*70)

results = {}

for uni, urls in CANDIDATES.items():
    print(f"\n{'─'*60}")
    print(f"  {uni}")
    print(f"{'─'*60}")
    best = None
    for url in urls:
        try:
            r = sess.get(url, timeout=TIMEOUT, allow_redirects=True)
            status = r.status_code
            if status == 200:
                has_content, reason = score_page(r.text)
                flag = "✅" if has_content else "⚠️ "
                print(f"  {flag} [{status}] {url}")
                print(f"       → {reason}")
                if has_content and best is None:
                    best = url
            else:
                print(f"  ❌ [{status}] {url}")
        except Exception as e:
            print(f"  ❌ [ERR] {url} — {e}")
    results[uni] = best

print("\n\n" + "="*70)
print("SUMMARY — Best working URL per university:")
print("="*70)
for uni, url in results.items():
    status = url if url else "— NONE FOUND"
    print(f"  {uni:30s}  {status}")
