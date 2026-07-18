# -*- coding: utf-8 -*-
"""
diag_court.py — courtauction 접속 실패 원인 진단
GitHub Actions 러너에서 실행해서, timeout이 '해외 IP 차단' 때문인지
아니면 다른 원인(헤더/세션/사이트다운)인지 가른다.
"""
import sys, socket, time, json
sys.stdout.reconfigure(line_buffering=True)
import requests

def line(t): print("\n" + "="*60 + f"\n{t}\n" + "="*60)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ── TEST 1: 다른 한국 사이트는 되는가? (해외 전체차단 vs courtauction만) ──
line("TEST 1: 다른 한국 사이트 접속 (대조군)")
for name, url in [("네이버", "https://www.naver.com"),
                  ("정부24", "https://www.gov.kr"),
                  ("대법원 메인", "https://www.scourt.go.kr"),
                  ("온비드", "https://www.onbid.co.kr")]:
    try:
        t0 = time.time()
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        print(f"  [OK]   {name:10} {r.status_code}  {time.time()-t0:.1f}s  len={len(r.content)}")
    except Exception as e:
        print(f"  [FAIL] {name:10} {type(e).__name__}: {str(e)[:60]}")

# ── TEST 2: courtauction DNS/TCP/HTTPS 단계별 ──
line("TEST 2: courtauction 단계별 진단")
host = "www.courtauction.go.kr"
try:
    ip = socket.gethostbyname(host)
    print(f"  DNS 해석 OK: {host} → {ip}")
except Exception as e:
    print(f"  DNS 실패: {e}")
    ip = None

if ip:
    for port in (443, 80):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        t0 = time.time()
        try:
            s.connect((ip, port))
            print(f"  TCP {port} 연결 OK  {time.time()-t0:.1f}s")
            s.close()
        except Exception as e:
            print(f"  TCP {port} 실패  {time.time()-t0:.1f}s  {type(e).__name__}: {str(e)[:50]}")

# ── TEST 3: courtauction HTTPS GET (헤더 변형) ──
line("TEST 3: courtauction HTTPS GET — 헤더 변형별")
variants = {
    "헤더없음": {},
    "UA만": {"User-Agent": UA},
    "풀헤더(브라우저모방)": {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
}
for name, h in variants.items():
    try:
        t0 = time.time()
        r = requests.get("https://www.courtauction.go.kr/pgj/index.on",
                         headers=h, timeout=20)
        body = r.text[:120].replace("\n", " ")
        print(f"  [{name}] {r.status_code}  {time.time()-t0:.1f}s  len={len(r.content)}")
        print(f"       서버헤더: {dict(list(r.headers.items())[:4])}")
        print(f"       본문앞: {body}")
    except Exception as e:
        print(f"  [{name}] FAIL  {type(e).__name__}: {str(e)[:70]}")
    time.sleep(1)

# ── TEST 4: 러너의 실제 나가는 IP 확인 ──
line("TEST 4: 이 러너의 공인 IP / 위치")
try:
    r = requests.get("https://ipinfo.io/json", headers={"User-Agent": UA}, timeout=10)
    j = r.json()
    print(f"  IP: {j.get('ip')}  국가: {j.get('country')}  지역: {j.get('region')}  ISP: {j.get('org')}")
except Exception as e:
    print(f"  IP 확인 실패: {e}")

line("진단 끝 — 위 결과를 그대로 캡처해 주세요")
