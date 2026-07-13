#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
공매(온비드) 수집 → data.js + 신규매물 카카오톡 알림
v3: 필드명 자동대응 / 서울 전 구 순회 / 단계별 잔여건수 로그
"""
import json, os, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

DATA_KEY      = os.environ.get("DATA_KEY", "")
KAKAO_REST    = os.environ.get("KAKAO_REST_KEY", "")
KAKAO_REFRESH = os.environ.get("KAKAO_REFRESH_TOKEN", "")

# "전체" 또는 "광진구,성동구" 처럼 콤마로 지정. 기본은 서울 전체
REGION_SD = os.environ.get("REGION_SD", "서울특별시")
REGION_GU = os.environ.get("REGION_GU", "전체")
DEBUG     = os.environ.get("DEBUG", "1") == "1"

MAX_PAGES, ROWS  = 8, 100
REALDEAL_MONTHS  = 6
PRPT_DIV         = "0007,0005,0006,0008"
MIN_AREA         = 25.0        # 전용 25㎡ 이상
VILLA_CAP        = 800_000_000 # 빌라 8억 컷 (아파트는 무제한)

BASE = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2"
OP   = "getRlstCltrList2"
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

# ── 핵심: 응답 키 이름이 camelCase든 UPPER_SNAKE든 상관없이 찾아내기 ──────────
def norm(item):
    """{'LCTN_SGGNM': '광진구'} 와 {'lctnSggnm': '광진구'} 를 같은 키로 통일"""
    return {str(k).lower().replace("_", ""): v for k, v in item.items()}

def pick(nd, *cands, default=""):
    for c in cands:
        k = c.lower().replace("_", "")
        v = nd.get(k)
        if v not in (None, "", "null"): return str(v).strip()
    return default

def pick_contains(nd, *keywords):
    """키 이름에 특정 단어가 들어간 필드를 통째로 긁어 이어붙임 (주소/용도 탐색용)"""
    vals = []
    for k, v in nd.items():
        if v in (None, "", "null"): continue
        if any(kw in k for kw in keywords): vals.append(str(v))
    return " ".join(vals)

# ── 목록 조회 ─────────────────────────────────────────────────────────────
def onbid_url(page, gu=None, minimal=False):
    p = {"serviceKey": DATA_KEY, "pageNo": page, "numOfRows": ROWS, "resultType": "json"}
    if not minimal:
        p.update({"prptDivCd": PRPT_DIV, "pvctTrgtYn": "N"})
    p["lctnSdnm"] = REGION_SD
    if gu: p["lctnSggnm"] = gu
    return f"{BASE}/{OP}?{urllib.parse.urlencode(p, safe='=,')}"

def json_items(raw, label=""):
    d = json.loads(raw)
    root = d.get("response", d)
    body, header = root.get("body", {}), root.get("header", {})
    print(f"    [{label}] code={header.get('resultCode')} total={body.get('totalCount','?')}")
    it = body.get("items") or {}
    it = it.get("item", []) if isinstance(it, dict) else it
    if isinstance(it, dict): it = [it]
    return it if isinstance(it, list) else []

def fetch_list(gu=None):
    out = []
    for pg in range(1, MAX_PAGES + 1):
        try:
            its = json_items(http_get(onbid_url(pg, gu)), f"{gu or REGION_SD}/p{pg}")
        except Exception as e:
            print(f"  (목록 실패 p{pg}: {e})"); break
        if not its: break
        out += its
        if len(its) < ROWS: break
        time.sleep(0.2)
    return out

# ── 지오코딩 / 실거래 ─────────────────────────────────────────────────────
def geocode(addr, cache):
    if not addr: return None
    if addr in cache: return cache[addr]
    c = None
    try:
        docs = json.loads(http_get(
            "https://dapi.kakao.com/v2/local/search/address.json?query=" + urllib.parse.quote(addr),
            headers={"Authorization": f"KakaoAK {KAKAO_REST}"}))["documents"]
        if docs: c = [float(docs[0]["x"]), float(docs[0]["y"])]
    except Exception: pass
    cache[addr] = c; time.sleep(0.1); return c

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

_DEAL_CACHE = {}
def load_deals(lawd):
    if not lawd: return {"apt": [], "rh": [], "silv": []}
    if lawd in _DEAL_CACHE: return _DEAL_CACHE[lawd]
    idx = {"apt": [], "rh": [], "silv": []}
    NM = {"apt": ["aptNm", "아파트"], "rh": ["mhouseNm", "연립다세대"], "silv": ["aptNm", "단지", "아파트"]}
    for kind in idx:
        for ym in ym_list(REALDEAL_MONTHS):
            q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "LAWD_CD": lawd,
                                        "DEAL_YMD": ym, "numOfRows": 1000, "pageNo": 1}, safe="=")
            try: its = xml_items(http_get(f"{RT[kind]}?{q}"))
            except Exception: its = []
            for it in its:
                nm = next((it[k] for k in NM[kind] if it.get(k)), "")
                ar = it.get("excluUseAr") or it.get("전용면적") or ""
                am = (it.get("dealAmount") or it.get("거래금액") or "").replace(",", "").strip()
                if nm and am: idx[kind].append({"name": nm, "area": ar, "amount": am, "ym": ym})
            time.sleep(0.1)
    _DEAL_CACHE[lawd] = idx
    return idx

def match(name, area, idx, kind):
    a = fnum(area); tgt = (name or "").replace(" ", ""); best = None
    for d in idx.get(kind, []):
        dn = d["name"].replace(" ", "")
        if len(dn) >= 2 and dn in tgt:
            da = fnum(d["area"])
            if a and da and abs(da - a) > 3: continue
            if not best or d["ym"] > best["ym"]: best = d
    return best

# ── 가공 ─────────────────────────────────────────────────────────────────
RESI = ("아파트", "연립", "다세대", "빌라", "단독", "다가구", "주거용")
def build(items, gu_hint=None):
    gc = json.load(open(fp("geocode_cache.json"), encoding="utf-8")) if os.path.exists(fp("geocode_cache.json")) else {}
    stat = {"입력": len(items), "주거용": 0, "면적": 0, "가격": 0, "지오코딩": 0}
    out = []

    if DEBUG and items:
        print("  [필드덤프] 첫 아이템 키 =", sorted(items[0].keys()))
        print("  [필드덤프] 첫 아이템 =", json.dumps(items[0], ensure_ascii=False)[:700])

    for raw_it in items:
        nd = norm(raw_it)

        # 주소·용도는 키 이름이 뭐든 '주소/용도스러운' 필드를 전부 긁어서 판단
        addr_blob = pick_contains(nd, "adrs", "addr", "lctn", "지번", "주소") or ""
        use_blob  = pick_contains(nd, "ctgr", "usg", "용도", "goods") or ""
        name = pick(nd, "cltrNm", "onbidCltrNm", "goodsNm", "물건명")

        gu = next((g for g in SEOUL_GU if g in addr_blob), None) or gu_hint
        if not gu: continue

        if "오피스텔" in use_blob or "오피스텔" in name: continue
        if not any(k in use_blob for k in RESI): continue
        stat["주거용"] += 1

        area = fnum(pick(nd, "bldSqms", "bldArea", "excluUseAr", "면적"))
        if area is not None and area < MIN_AREA: continue
        stat["면적"] += 1

        minp  = num(pick(nd, "minBidPrc", "lowstBidPrcIndctCont", "최저입찰가"))
        aprs  = num(pick(nd, "apslAsesAvgAmt", "apslEvlAmt", "감정가"))
        is_apt = "아파트" in use_blob or "아파트" in name
        if (not is_apt) and minp and minp > VILLA_CAP: continue
        stat["가격"] += 1

        coord = geocode(addr_blob.split("(")[0][:60], gc) or geocode(f"{REGION_SD} {gu} {name}", gc)
        if not coord: continue
        stat["지오코딩"] += 1

        deals = load_deals(SEOUL_GU.get(gu))
        deal  = match(name, area, deals, "apt" if is_apt else "rh")
        silv  = match(name, area, deals, "silv") if is_apt else None
        gap   = (num(deal["amount"]) * 10000 - minp) if (deal and minp) else None

        out.append({
            "name": name, "addr": addr_blob[:60], "gu": gu,
            "use": use_blob.split("/")[-1].strip()[:20],
            "isApt": is_apt, "area": area or "", "min": minp, "aprs": aprs,
            "disc": pick(nd, "apslPrcCtrsLowstBidRto", "minBidPrcRate"),
            "fail": pick(nd, "usbdNft", "uscbdCnt"),
            "status": pick(nd, "pbctStatNm", "pbctCltrStatNm"),
            "id": pick(nd, "cltrMngNo", "cltrMnmtNo", "cltrNo"),
            "thumb": pick(nd, "thnlImgUrlAdr", "cltrImgFilePath").replace("&amp;", "&"),
            "deal": num(deal["amount"]) * 10000 if deal else None,
            "silv": num(silv["amount"]) * 10000 if silv else None,
            "gap": gap,
            "naver": NAVER_TMPL.format(q=urllib.parse.quote(name or f"{gu}")),
            "lng": coord[0], "lat": coord[1]})

    json.dump(gc, open(fp("geocode_cache.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  단계별 잔여: " + " → ".join(f"{k} {v}" for k, v in stat.items()))
    return out

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
        print("  (카카오 토큰 없음 → 알림 생략)"); return
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
        print("ERROR: DATA_KEY 환경변수 없음 (GitHub Secrets 확인)"); sys.exit(1)

    gus = list(SEOUL_GU) if REGION_GU in ("전체", "", "ALL") else [g.strip() for g in REGION_GU.split(",")]
    print(f"수집 시작 — 대상 {len(gus)}개 구: {', '.join(gus)}")

    prev_ids = {x.get("id") for x in read_prev()}
    cur = []
    for gu in gus:
        items = fetch_list(gu)
        print(f"  · {gu}: 목록 {len(items)}건")
        cur += build(items, gu_hint=gu)

    # id 중복 제거
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
