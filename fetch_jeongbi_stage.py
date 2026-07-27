#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, os, re, sys, time, urllib.parse, urllib.request

BASE = "https://cleanup.seoul.go.kr/cleanup/bsnssttus/lscrMainIndx.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

GU = {
    "11110": "종로구", "11140": "중구",   "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}

STAGES = [
    "정비계획 수립", "정비계획수립", "재정비촉진지구수립", "재정비촉진지구 수립",
    "안전진단", "정비구역지정", "정비구역 지정", "추진위원회승인", "추진위원회 승인",
    "조합설립인가", "주민대표회의구성통지", "주민대표회의 구성통지",
    "사업시행인가", "관리처분인가", "철거", "착공", "분양",
    "준공인가", "이전고시", "조합해산", "조합청산", "일시중단",
]
DONE = {"준공인가", "이전고시", "조합해산", "조합청산"}

TAG = re.compile(r"<[^>]+>")
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
MAPID = re.compile(r"mapOpenPopup\(\s*['\"]([^'\"]+)['\"]")
JIBUN = re.compile(r"[가-힣]{2,}(?:동|가|로)\s*\d+(?:-\d+)?")

def text(s):
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = TAG.sub("", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()

def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            for enc in ("utf-8", "cp949"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "replace")
        except Exception as e:
            if i == tries - 1:
                print("  [실패] %s (%s)" % (url[:80], e))
                return ""
            time.sleep(2 * (i + 1))
    return ""

def parse_rows(html):
    out = []
    for rowhtml in ROW.findall(html):
        cells = [text(c) for c in CELL.findall(rowhtml)]
        if len(cells) < 4:
            continue
        stage = next((c for c in cells if c in STAGES), "")
        if not stage:
            continue
        gu = next((c for c in cells if c.endswith("구") and len(c) <= 5), "")
        jib = next((c for c in cells if JIBUN.search(c) and len(c) <= 40), "")
        cand = [c for c in cells if c not in (stage, gu, jib) and len(c) >= 4
                and not c.isdigit()]
        name = max(cand, key=len) if cand else ""
        m = MAPID.search(rowhtml)
        out.append({"gu": gu, "nm": name, "jibun": jib, "stage": stage,
                    "wt": m.group(1) if m else ""})
    return out

def crawl():
    recs, blank = [], []
    for code, gu in GU.items():
        got = 0
        for page in range(1, 8):
            q = urllib.parse.urlencode({"scupBsnsSttus.signguCode": code,
                                        "cpage": page, "pageSize": 100})
            html = get(BASE + "?" + q)
            if not html:
                break
            rows = parse_rows(html)
            if page == 1 and not rows:
                blank.append((gu, html)); break
            if not rows:
                break
            recs += rows; got += len(rows)
            if len(rows) < 100:
                break
            time.sleep(0.4)
        print("  %-6s %3d건" % (gu, got))
        time.sleep(0.4)
    return recs, blank

def diagnose(html):
    print("\n=== 파서 진단 (이 부분을 그대로 복사해 주세요) ===")
    print("HTML 길이:", len(html))
    rows = ROW.findall(html)
    print("<tr> 개수:", len(rows))
    for i, r in enumerate(rows[:6]):
        cells = [text(c) for c in CELL.findall(r)]
        print(" row%d (%d칸): %s" % (i, len(cells), " | ".join(cells)[:200]))
    print("mapOpenPopup 발견:", len(MAPID.findall(html)))
    for kw in ("로그인", "자바스크립트", "오류", "점검"):
        if kw in html:
            print("  ! 페이지에 '%s' 문구 있음" % kw)
    print("=== 진단 끝 ===\n")

def kakao_key():
    k = os.environ.get("KAKAO_KEY") or os.environ.get("KAKAO_REST_KEY")
    if k:
        return k.strip()
    for f in ("fetch_gonmae.py", "fetch_gyeongmae.py"):
        try:
            src = open(f, encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"KakaoAK\s+([0-9a-f]{32})", src) or \
            re.search(r"['\"]([0-9a-f]{32})['\"]", src)
        if m:
            return m.group(1)
    return ""

def geocode_all(recs, key):
    cache_path = "geocode_cache_jb.json"
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        cache = {}
    n_new = 0
    for r in recs:
        if not r["jibun"]:
            continue
        addr = ("서울 %s %s" % (r["gu"], r["jibun"])).strip()
        if addr in cache:
            r["ll"] = cache[addr]; continue
        url = "https://dapi.kakao.com/v2/local/search/address.json?query=" + \
              urllib.parse.quote(addr)
        try:
            req = urllib.request.Request(url, headers={"Authorization": "KakaoAK " + key})
            with urllib.request.urlopen(req, timeout=15) as resp:
                d = json.load(resp)
            docs = d.get("documents") or []
            cache[addr] = [float(docs[0]["y"]), float(docs[0]["x"])] if docs else None
        except Exception:
            cache[addr] = None
        r["ll"] = cache[addr]; n_new += 1
        if n_new % 25 == 0:
            json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        time.sleep(0.12)
    json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    print("  지오코딩 신규 %d건 (캐시 %d건)" % (n_new, len(cache)))

NOISE = ["주택정비형", "도시정비형", "주거환경개선사업", "주택재개발정비사업",
         "주택재개발사업", "주택재건축정비사업", "주택재건축사업", "재개발사업",
         "재건축사업", "정비사업", "재정비촉진구역", "정비구역", "사업", "구역"]

def norm(s):
    s = re.sub(r"[\s()\[\]（）]", "", s or "")
    s = s.replace("제정비촉진", "재정비촉진")
    for w in NOISE:
        s = s.replace(w, "")
    return s

def main():
    if not os.path.exists("jeongbi.geojson"):
        print("jeongbi.geojson 이 없습니다. ~/Gonmae 에서 실행하세요."); sys.exit(1)
    print("[1/4] 정보몽땅 크롤링")
    recs, blank = crawl()
    print("  총 %d건" % len(recs))
    if len(recs) < 100:
        print("\n!! 수집량이 비정상입니다. 아무 파일도 덮어쓰지 않고 중단합니다.")
        if blank:
            gu, html = blank[0]
            open("debug_cleanup.html", "w", encoding="utf-8").write(html)
            print("   원본을 debug_cleanup.html 로 저장 (%s)" % gu)
            diagnose(html)
        sys.exit(1)
    json.dump(recs, open("stages_raw.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[2/4] 지오코딩")
    key = kakao_key()
    if key:
        geocode_all(recs, key)
    else:
        print("  카카오 키를 못 찾음 -> 이름 매칭만 사용")
    print("[3/4] 폴리곤 연결")
    gj = json.load(open("jeongbi.geojson", encoding="utf-8"))
    feats = gj["features"]
    zi = None
    try:
        from zone_tag import ZoneIndex
        zi = ZoneIndex()
    except Exception as e:
        print("  zone_tag 로드 실패(%s) -> 이름 매칭만" % e)
    byname = {}
    for f in feats:
        byname.setdefault(norm(f["properties"]["nm"]), f["properties"]["nm"])
    stage_of, hit_geo, hit_name = {}, 0, 0
    rank = {s: i for i, s in enumerate(STAGES)}
    def put(nm, st):
        if nm not in stage_of or rank.get(st, 0) > rank.get(stage_of[nm], 0):
            stage_of[nm] = st
    for r in recs:
        nm = None; ll = r.get("ll")
        if zi and ll:
            z = zi.find(ll[0], ll[1])
            if z:
                nm = z.get("nm"); hit_geo += 1
        if not nm:
            nm = byname.get(norm(r["nm"]))
            if nm:
                hit_name += 1
        if nm:
            put(nm, r["stage"])
    print("  좌표매칭 %d / 이름매칭 %d / 미연결 %d"
          % (hit_geo, hit_name, len(recs) - hit_geo - hit_name))
    covered = sum(1 for f in feats if f["properties"]["nm"] in stage_of)
    print("  폴리곤 %d개 중 %d개(%.1f%%)에 단계 부여"
          % (len(feats), covered, 100.0 * covered / len(feats)))
    print("[4/4] stages.js 생성")
    payload = {"gen": time.strftime("%Y-%m-%d"), "done": sorted(DONE), "st": stage_of}
    with open("stages.js", "w", encoding="utf-8") as f:
        f.write("window.ZSTAGE=")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print("  stages.js %.0fKB, 구역 %d개, 완료 %d개"
          % (os.path.getsize("stages.js") / 1024, len(stage_of),
             sum(1 for v in stage_of.values() if v in DONE)))
    print("\n완료. 큰 파일은 건드리지 않았습니다.")

if __name__ == "__main__":
    main()
