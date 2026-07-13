#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
공매(온비드) 수집 → data.js + 신규매물 카카오톡 알림
v5: 카카오 키 셀프테스트 / 실패캐시 무시 / 지오코딩 시도내역 로깅
"""
import json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

DATA_KEY      = os.environ.get("DATA_KEY", "").strip()
KAKAO_REST    = os.environ.get("KAKAO_REST_KEY", "").strip()
KAKAO_REFRESH = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()

REGION_SD = os.environ.get("REGION_SD", "서울특별시")
REGION_GU = os.environ.get("REGION_GU", "전체")   # "전체" 또는 "광진구,성동구"

MAX_PAGES, ROWS = 8, 100
REALDEAL_MONTHS = 6
PRPT_DIV        = "0007,0005,0006,0008"
MIN_AREA        = 25.0
VILLA_CAP       = 800_000_000

BASE = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2"
OP   = "getRlstCltrList2"
KAKAO_ADDR = "https://dapi.kakao.com/v2/local/search/address.json?query="
KAKAO_KW   = "https://dapi.kakao.com/v2/local/search/keyword.json?query="
RT = {"apt":"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
      "rh": "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
      "silv":"https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"}
NAVER_TMPL = "https://m.land.naver.com/search/result/{q}"
SEOUL_GU = {"종로구":"11110","중구":"11140","용산구":"11170","성동구":"11200","광진구":"11215",
"동대문구":"11230","중랑구":"11260","성북구":"11290","강북구":"11305","도봉구":"11320",
"노원구":"11350","은평구":"11380","서대문구":"11410","마포구":"11440","양천구":"11470",
"강서구":"11500","구로구":"11530","금천구":"11545","영등포구":"11560","동작구":"11590",
"관악구":"11620","서초구":"11650","강남구":"11680","송파구":"11710","강동구":"11740"}

HERE = os.path.dirname(os.path.abspath(__file__))
def fp(n): return os.path.join(HERE, n)
def num(v):
    try: return int(float(str(v).replace(",", "").strip()))
    except Exception: return 0
def fnum(v):
    try: return float(str(v).replace(",", "").strip())
    except Exception: return None

def http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")

# ── 카카오 셀프테스트 ─────────────────────────────────────────────────────
def kakao_selftest():
    print(f"[키체크] KAKAO_REST_KEY 길이={len(KAKAO_REST)} 앞4={KAKAO_REST[:4]}…")
    probe = "서울특별시 광진구 화양동 530"
    try:
        raw = http_get(KAKAO_ADDR + urllib.parse.quote(probe),
                       headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
        docs = json.loads(raw).get("documents", [])
        print(f"[키체크] '{probe}' → HTTP 200, documents={len(docs)}")
        if docs:
            print(f"[키체크] 좌표 = x={docs[0]['x']} y={docs[0]['y']}  ✅ 키·주소검색 정상")
            return True
        print("[키체크] ⚠ 200인데 결과 0건 — 주소 질의 형식 문제")
        print(f"[키체크] 응답 원문: {raw[:300]}")
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:300]
        print(f"[키체크] ❌ HTTP {e.code} — {body}")
        print("[키체크] → 401이면 REST API 키가 아님(자바스크립트 키 오입력) 또는 키 오타.")
        print("[키체크] → 403이면 카카오 앱의 '허용 IP' 설정 때문입니다. IP 제한을 비우세요.")
        return False
    except Exception as e:
        print(f"[키체크] ❌ 예외: {e}")
        return False

# ── 목록 조회 ─────────────────────────────────────────────────────────────
def onbid_url(page, gu):
    p = {"serviceKey": DATA_KEY, "pageNo": page, "numOfRows": ROWS, "resultType": "json",
         "prptDivCd": PRPT_DIV, "pvctTrgtYn": "N", "lctnSdnm": REGION_SD, "lctnSggnm": gu}
    return f"{BASE}/{OP}?{urllib.parse.urlencode(p, safe='=,')}"

def json_items(raw, label):
    d = json.loads(raw); root = d.get("response", d)
    body, header = root.get("body", {}), root.get("header", {})
    it = body.get("items") or {}
    it = it.get("item", []) if isinstance(it, dict) else it
    if isinstance(it, dict): it = [it]
    if not isinstance(it, list): it = []
    print(f"    [{label}] code={header.get('resultCode')} total={body.get('totalCount','?')} items={len(it)}")
    return it

def fetch_list(gu):
    out = []
    for pg in range(1, MAX_PAGES + 1):
        try:
            its = json_items(http_get(onbid_url(pg, gu)), f"{gu}/p{pg}")
        except Exception as e:
            print(f"  (목록 실패 {gu} p{pg}: {e})"); break
        if not its: break
        out += its
        if len(its) < ROWS: break
        time.sleep(0.2)
    return out

# ── 지오코딩 ─────────────────────────────────────────────────────────────
_glog = {"n": 0}

def clean_addr(full):
    """'서울특별시 광진구 화양동 530 씨즈건대힐스 제2층 제206호' → 질의 후보"""
    s = re.sub(r"\s*외\s*\d+\s*필지", "", full or "").strip()
    m = re.search(r"(\S*[시도]\s+\S+[구군]\s+\S+[동읍면가리]\s*(?:산\s*)?[\d\-]+)", s)
    jibun = m.group(1) if m else ""                 # ① 순수 지번 (카카오 주소검색이 가장 잘 먹음)
    lv1 = re.sub(r"\s*제?\s*[지B]?\d+\s*층.*$", "", s).strip()
    lv1 = re.sub(r"\s*제?\s*[\dA-Za-z\-]+\s*호\s*$", "", lv1).strip()   # ② 층·호 제거(건물명까지)
    return [c for c in (jibun, lv1, s) if c]

def kakao_query(url, q):
    raw = http_get(url + urllib.parse.quote(q), headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
    return json.loads(raw).get("documents", [])

def geocode(cands, cache):
    tried = []
    for addr in cands:
        if not addr: continue
        if cache.get(addr):            # 성공만 캐시 사용 (실패 캐시는 매번 재시도)
            return cache[addr]
        try:
            docs = kakao_query(KAKAO_ADDR, addr)
            tried.append(f"주소'{addr}'→{len(docs)}")
            if not docs:               # 주소검색 실패 시 키워드검색으로 재시도
                docs = kakao_query(KAKAO_KW, addr)
                tried.append(f"키워드'{addr}'→{len(docs)}")
            if docs:
                c = [float(docs[0]["x"]), float(docs[0]["y"])]
                cache[addr] = c
                return c
        except urllib.error.HTTPError as e:
            tried.append(f"'{addr}'→HTTP{e.code}")
        except Exception as e:
            tried.append(f"'{addr}'→ERR {e}")
        time.sleep(0.08)
    if _glog["n"] < 5:
        _glog["n"] += 1
        print("  ★지오코딩 실패: " + " | ".join(tried))
    return None

# ── 실거래 ────────────────────────────────────────────────────────────────
def ym_list(n):
    import datetime as dt
    b = dt.date.today().replace(day=1); out = []
    for i in range(n):
        m, y = b.month - i, b.year
        while m <= 0: m += 12; y -= 1
        out.append(f"{y}{m:02d}")
    return out

def xml_items(raw):
    return [{c.tag: (c.text or "").strip() for c in it} for it in ET.fromstring(raw).findall(".//item")]

_DEAL = {}
def load_deals(lawd):
    if not lawd: return {"apt": [], "rh": [], "silv": []}
    if lawd in _DEAL: return _DEAL[lawd]
    idx = {"apt": [], "rh": [], "silv": []}
    NM = {"apt": ["aptNm", "아파트"], "rh": ["mhouseNm", "연립다세대"], "silv": ["aptNm", "단지", "아파트"]}
    for kind in idx:
        for ym in ym_list(REALDEAL_MONTHS):
            q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "LAWD_CD": lawd, "DEAL_YMD": ym,
                                        "numOfRows": 1000, "pageNo": 1}, safe="=")
            try: its = xml_items(http_get(f"{RT[kind]}?{q}"))
            except Exception: its = []
            for it in its:
                nm = next((it[k] for k in NM[kind] if it.get(k)), "")
                ar = it.get("excluUseAr") or it.get("전용면적") or ""
                am = (it.get("dealAmount") or it.get("거래금액") or "").replace(",", "").strip()
                if nm and am: idx[kind].append({"name": nm, "area": ar, "amount": am, "ym": ym})
            time.sleep(0.08)
    _DEAL[lawd] = idx
    return idx

def match(bldg, area, idx, kind):
    a = fnum(area); tgt = (bldg or "").replace(" ", ""); best = None
    for d in idx.get(kind, []):
        dn = d["name"].replace(" ", "")
        if len(dn) >= 2 and dn in tgt:
            da = fnum(d["area"])
            if a and da and abs(da - a) > 3: continue
            if not best or d["ym"] > best["ym"]: best = d
    return best

# ── 가공 ─────────────────────────────────────────────────────────────────
RESI = ("아파트", "연립", "다세대", "빌라", "단독", "다가구", "도시형생활주택", "주거용")
def build(items, gu):
    gc = json.load(open(fp("geocode_cache.json"), encoding="utf-8")) if os.path.exists(fp("geocode_cache.json")) else {}
    gc = {k: v for k, v in gc.items() if v}          # 실패(null) 캐시 폐기
    stat = {"입력": len(items), "주거용": 0, "면적": 0, "가격": 0, "지오코딩": 0}
    deals = load_deals(SEOUL_GU.get(gu))
    out = []

    for it in items:
        use  = f"{it.get('cltrUsgMclsCtgrNm','')} {it.get('cltrUsgSclsCtgrNm','')}"
        full = (it.get("onbidCltrNm") or "").strip()
        if "오피스텔" in use: continue
        if not any(k in use for k in RESI): continue
        stat["주거용"] += 1

        area = fnum(it.get("bldSqms"))
        if area is not None and area < MIN_AREA: continue
        stat["면적"] += 1

        minp   = num(it.get("lowstBidPrcIndctCont"))
        aprs   = num(it.get("apslEvlAmt"))
        is_apt = "아파트" in use
        if (not is_apt) and minp and minp > VILLA_CAP: continue
        stat["가격"] += 1

        cands = clean_addr(full)
        cands.append(f"{it.get('lctnSdnm','')} {it.get('lctnSggnm','')} {it.get('lctnEmdNm','')}".strip())
        coord = geocode(cands, gc)
        if not coord: continue
        stat["지오코딩"] += 1

        bldg = re.sub(r"^\S*[시도]\s+\S+[구군]\s+\S+[동읍면가리]\s*[\d\-]+\s*", "", cands[1] if len(cands) > 1 else full).strip()
        deal = match(bldg, area, deals, "apt" if is_apt else "rh")
        silv = match(bldg, area, deals, "silv") if is_apt else None
        gap  = (num(deal["amount"]) * 10000 - minp) if (deal and minp) else None

        out.append({
            "name": bldg or full[:30], "addr": full, "gu": gu,
            "use": it.get("cltrUsgSclsCtgrNm", "") or it.get("cltrUsgMclsCtgrNm", ""),
            "isApt": is_apt, "area": area or "", "min": minp, "aprs": aprs,
            "disc": it.get("apslPrcCtrsLowstBidRto", ""), "fail": it.get("usbdNft", ""),
            "status": it.get("pbctStatNm", ""), "id": it.get("cltrMngNo", ""),
            "end": it.get("cltrBidEndDt", ""), "kind": it.get("prptDivNm", ""),
            "thumb": (it.get("thnlImgUrlAdr") or "").replace("&amp;", "&"),
            "deal": num(deal["amount"]) * 10000 if deal else None,
            "silv": num(silv["amount"]) * 10000 if silv else None, "gap": gap,
            "naver": NAVER_TMPL.format(q=urllib.parse.quote(bldg or f"{gu} {it.get('lctnEmdNm','')}")),
            "lng": coord[0], "lat": coord[1]})

    json.dump(gc, open(fp("geocode_cache.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  단계별 잔여: " + " → ".join(f"{k} {v}" for k, v in stat.items()))
    return out

# ── 알림 ─────────────────────────────────────────────────────────────────
def read_prev():
    try:
        s = open(fp("data.js"), encoding="utf-8").read()
        return json.loads(s[s.index("["):s.rindex("]") + 1])
    except Exception: return []

def kakao_token():
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": KAKAO_REST,
                                   "refresh_token": KAKAO_REFRESH}).encode()
    req = urllib.request.Request("https://kauth.kakao.com/oauth/token", data=data)
    return json.loads(urllib.request.urlopen(req, timeout=10).read())["access_token"]

def kakao_send(text, link):
    if not (KAKAO_REFRESH and KAKAO_REST):
        print("  (카카오 리프레시 토큰 없음 → 알림 생략)"); return
    try:
        tok = kakao_token()
        tmpl = json.dumps({"object_type": "text", "text": text[:900],
                           "link": {"web_url": link, "mobile_web_url": link}}, ensure_ascii=False)
        req = urllib.request.Request("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                                     data=urllib.parse.urlencode({"template_object": tmpl}).encode(),
                                     headers={"Authorization": f"Bearer {tok}"})
        urllib.request.urlopen(req, timeout=10)
        print("  카카오톡 알림 전송 완료")
    except Exception as e:
        print(f"  (카카오 알림 실패: {e})")

if __name__ == "__main__":
    if not DATA_KEY:
        print("ERROR: DATA_KEY 없음 (GitHub Secrets 확인)"); sys.exit(1)
    if not KAKAO_REST:
        print("ERROR: KAKAO_REST_KEY 없음 → 지오코딩 전부 실패"); sys.exit(1)
    if not kakao_selftest():
        print("→ 카카오 키 문제 확정. 수집 중단."); sys.exit(1)

    gus = list(SEOUL_GU) if REGION_GU in ("전체", "", "ALL") else [g.strip() for g in REGION_GU.split(",")]
    print(f"수집 시작 — 대상 {len(gus)}개 구")

    prev_ids = {x.get("id") for x in read_prev()}
    cur = []
    for gu in gus:
        items = fetch_list(gu)
        print(f"  · {gu}: 목록 {len(items)}건")
        cur += build(items, gu)

    seen, uniq = set(), []
    for x in cur:
        if x["id"] and x["id"] in seen: continue
        seen.add(x["id"]); uniq.append(x)
    cur = uniq

    open(fp("data.js"), "w", encoding="utf-8").write("window.GONMAE = " + json.dumps(cur, ensure_ascii=False) + ";")
    print(f"완료: {len(cur)}건 → data.js")

    new = [x for x in cur if x.get("id") and x["id"] not in prev_ids]
    if prev_ids and new:
        lines = [f"🏠 신규 공매 {len(new)}건"]
        for x in new[:8]:
            eok = (x["min"] / 1e8) if x["min"] else 0
            lines.append(f"· [{x['gu']}] {x['use']} {x['area']}㎡ / 최저 {eok:.1f}억")
        kakao_send("\n".join(lines), "https://bb7073.github.io/Gonmae/")
    else:
        print(f"  신규 {len(new)}건 (알림조건 미해당)")
