import requests, re, time
from bs4 import BeautifulSoup

h = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# Find Kimura lab page
r = requests.get('https://www.is.tohoku.ac.jp/en/laboratory/', headers=h, timeout=12)
soup = BeautifulSoup(r.text, 'html.parser')

kimura_url = None
for a in soup.find_all('a', href=True):
    text = a.get_text(strip=True)
    href = a.get('href', '')
    if 'kimura' in text.lower() or 'kimura' in href.lower():
        full = href if href.startswith('http') else f"https://www.is.tohoku.ac.jp{href}"
        print(f"Found: [{text}] -> {full}")
        kimura_url = full

if kimura_url:
    time.sleep(1)
    r2 = requests.get(kimura_url, headers=h, timeout=12)
    s2 = BeautifulSoup(r2.text, 'html.parser')
    # Look for email
    for a in s2.find_all('a', href=True):
        if a['href'].startswith('mailto:'):
            print("Email:", a['href'][7:])
    # Also regex scan
    text_content = s2.get_text(separator=' ')
    emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text_content)
    if emails:
        print("Emails found on page:", emails[:5])
