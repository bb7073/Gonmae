#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
공매(온비드) 수집 → data.js + 신규매물 카카오톡 알림
v7: 서울 25개 구 / 회차 중복정리 / 법정동·지번 실거래 24개월 / 아파트 단지정보(세대수 등)
"""
import json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

DATA_KEY      = os.environ.get("DATA_KEY", "").strip()
KAKAO_REST    = os.environ.get("KAKAO_REST_KEY", "").strip()
KAKAO_REFRESH = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
ONLY_GU       = os.environ.get("ONLY_GU", "").strip()
FORCE_NOTIFY  = os.environ.get("FORCE_NOTIFY", "") == "1"

REGION_SD       = "서울특별시"
MAX_PAGES, ROWS = 10, 100
REALDEAL_MONTHS = 24
PRPT_DIV        = "0007,0005,0006,0008"
MIN_AREA        = 25.0
VILLA_CAP       = 800_000_000
PAGE_URL        = "https://bb7073.github.io/Gonmae/"

BASE = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2"
OP   = "getRlstCltrList2"
KAKAO_ADDR = "https://dapi.kakao.com/v2/local/search/address.json?query="
KAKAO_KW   = "https://dapi.kakao.com/v2/local/search/keyword.json?query="
RT = {"apt":"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
      "rh": "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
      "silv":"https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"}
# 공동주택 단지목록 / 기본정보 (오퍼레이션명은 후보를 순차 시도해 자동 확정)
APT_LIST_BASE  = "https://apis.data.go.kr/1613000/AptListService3"
APT_LIST_OPS   = ["getLegaldongAptList3", "getLegaldongAptList"]
APT_BASIS_BASE = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4"
APT_BASIS_OPS  = ["getAphusBassInfoV4", "getAphusBassInfoV3", "getAphusBassInfo"]

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
def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
def xml_items(raw):
    return [{c.tag: (c.text or "").strip() for c in it} for it in ET.fromstring(raw).findall(".//item")]
def g(d, *keys):
    for k in keys:
        if d.get(k): return d[k]
    return ""
def nrm(s): return re.sub(r"[\s\(\)0-9\-]|아파트|주상복합", "", s or "")

# ── 카카오 셀프테스트 ─────────────────────────────────────────────────────
def kakao_selftest():
    try:
        raw = http_get(KAKAO_ADDR + urllib.parse.quote("서울특별시 광진구 화양동 530"),
                       headers={"Authorization": f"KakaoAK {KAKAO_REST}"})
        print(f"[키체크] 카카오 OK (documents={len(json.loads(raw).get('documents', []))})")
        return True
    except urllib.error.HTTPError as e:
        print(f"[키체크] ❌ HTTP {e.code} — {e.read().decode('utf-8','ignore')[:200]}"); return False
    except Exception as e:
        print(f"[키체크] ❌ {e}"); return False

# ── 온비드 목록 ───────────────────────────────────────────────────────────
def fetch_list(gu):
    out = []
    for pg in range(1, MAX_PAGES + 1):
        p = {"serviceKey": DATA_KEY, "pageNo": pg, "numOfRows": ROWS, "resultType": "json",
             "prptDivCd": PRPT_DIV, "pvctTrgtYn": "N", "lctnSdnm": REGION_SD, "lctnSggnm": gu}
        try:
            d = json.loads(http_get(f"{BASE}/{OP}?{urllib.parse.urlencode(p, safe='=,')}"))
        except Exception as e:
            print(f"    (목록 실패 {gu} p{pg}: {e})"); break
        body = d.get("response", d).get("body", {})
        it = body.get("items") or {}
        it = it.get("item", []) if isinstance(it, dict) else it
        if isinstance(it, dict): it = [it]
        if not it: break
        out += it
        if len(it) < ROWS: break
        time.sleep(0.15)
    return out

# ── 지오코딩 ─────────────────────────────────────────────────────────────
def parse_addr(full):
    s = re.sub(r"\s*외\s*\d+\s*필지", "", full or "").strip()
    m = re.search(r"(\S*[시도])\s+(\S+[구군])\s+(\S+[동읍면가리])\s+(?:산\s*)?(\d+(?:-\d+)?)", s)
    if not m: return ("", "", "", "")
    rest = s[m.end():].strip()
    bldg = re.sub(r"\s*제?\s*[지B]?\d+\s*층.*$", "", rest).strip()
    bldg = re.sub(r"\s*제?\s*[\dA-Za-z\-]+\s*호\s*$", "", bldg).strip()
    return (f"{m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)}", bldg, m.group(3), m.group(4))

def geocode(jibun_addr, bldg, cache):
    for q in [jibun_addr, f"{jibun_addr} {bldg}".strip()]:
        if not q: continue
        if cache.get(q): return cache[q]
        for url in (KAKAO_ADDR, KAKAO_KW):
            try:
                docs = json.loads(http_get(url + urllib.parse.quote(q),
                       headers={"Authorization": f"KakaoAK {KAKAO_REST}"})).get("documents", [])
                if docs:
                    c = [float(docs[0]["x"]), float(docs[0]["y"])]
                    cache[q] = c; return c
            except Exception: pass
            time.sleep(0.05)
    return None

# ── 아파트 단지정보 (세대수 등) ───────────────────────────────────────────
_APT_LIST_OP  = {"op": None}
_APT_BASIS_OP = {"op": None}
_BJD_CACHE = {}     # bjdCode → [(kaptCode, kaptName)]
_KAPT_CACHE = {}    # kaptCode → dict

def apt_list_by_bjd(bjd):
    """법정동코드 → 그 동의 공동주택 단지 목록"""
    if bjd in _BJD_CACHE: return _BJD_CACHE[bjd]
    ops = [_APT_LIST_OP["op"]] if _APT_LIST_OP["op"] else APT_LIST_OPS
    res = []
    for op in ops:
        q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "bjdCode": bjd,
                                    "numOfRows": 200, "pageNo": 1}, safe="=")
        try:
            its = xml_items(http_get(f"{APT_LIST_BASE}/{op}?{q}"))
        except Exception:
            continue
        if its or _APT_LIST_OP["op"]:
            if not _APT_LIST_OP["op"]:
                _APT_LIST_OP["op"] = op
                print(f"  [단지목록] 오퍼레이션 '{op}' 사용")
            res = [(g(it, "kaptCode", "kaptcode"), g(it, "kaptName", "kaptname")) for it in its]
            break
    _BJD_CACHE[bjd] = res
    time.sleep(0.05)
    return res

def apt_basis(kapt):
    if kapt in _KAPT_CACHE: return _KAPT_CACHE[kapt]
    ops = [_APT_BASIS_OP["op"]] if _APT_BASIS_OP["op"] else APT_BASIS_OPS
    info = {}
    for op in ops:
        q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "kaptCode": kapt}, safe="=")
        try:
            its = xml_items(http_get(f"{APT_BASIS_BASE}/{op}?{q}"))
        except Exception:
            continue
        if its:
            if not _APT_BASIS_OP["op"]:
                _APT_BASIS_OP["op"] = op
                print(f"  [단지정보] 오퍼레이션 '{op}' 사용")
            it = its[0]
            info = {"hh": num(g(it, "kaptdaCnt")), "dong": num(g(it, "kaptDongCnt")),
                    "used": g(it, "kaptUsedate"), "heat": g(it, "codeHeatNm"),
                    "hall": g(it, "codeHallNm"), "kaptName": g(it, "kaptName")}
            break
    _KAPT_CACHE[kapt] = info
    time.sleep(0.05)
    return info

def apt_info(pnu, bldg):
    """PNU(19자리) 앞 10자리 = 법정동코드 → 단지 매칭 → 세대수 등"""
    if not pnu or len(pnu) < 10 or not bldg: return {}
    cands = apt_list_by_bjd(pnu[:10])
    key = nrm(bldg)
    if not key: return {}
    for code, name in cands:
        n = nrm(name)
        if n and (n in key or key in n):
            return apt_basis(code)
    return {}

# ── 실거래 ────────────────────────────────────────────────────────────────
def ym_list(n):
    import datetime as dt
    b = dt.date.today().replace(day=1); out = []
    for i in range(n):
        m, y = b.month - i, b.year
        while m <= 0: m += 12; y -= 1
        out.append(f"{y}{m:02d}")
    return out

_DEAL = {}
def load_deals(lawd):
    if lawd in _DEAL: return _DEAL[lawd]
    by_jb, by_nm = {}, {}
    for kind in ("apt", "rh", "silv"):
        for ym in ym_list(REALDEAL_MONTHS):
            q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "LAWD_CD": lawd, "DEAL_YMD": ym,
                                        "numOfRows": 1000, "pageNo": 1}, safe="=")
            try: its = xml_items(http_get(f"{RT[kind]}?{q}"))
            except Exception: its = []
            for it in its:
                amt = num(g(it, "dealAmount", "거래금액"))
                if not amt: continue
                nm  = g(it, "aptNm", "mhouseNm", "아파트", "연립다세대")
                umd, jb = g(it, "umdNm", "법정동"), g(it, "jibun", "지번")
                rec = {"ym": ym, "amt": amt, "area": fnum(g(it, "excluUseAr", "전용면적")) or "",
                       "floor": g(it, "floor", "층"), "name": nm}
                if umd and jb: by_jb.setdefault((umd.strip(), jb.strip()), []).append(rec)
                if nm: by_nm.setdefault(nm.replace(" ", ""), []).append(rec)
            time.sleep(0.05)
    _DEAL[lawd] = (by_jb, by_nm)
    return _DEAL[lawd]

def deal_history(lawd, umd, jibun, bldg, area):
    by_jb, by_nm = load_deals(lawd)
    recs = list(by_jb.get((umd, jibun), []))
    if not recs and bldg:
        key = bldg.replace(" ", "")
        for nm, rs in by_nm.items():
            if len(nm) >= 2 and (nm in key or key in nm): recs += rs
    same = [r for r in recs if not (area and r["area"]) or abs(r["area"] - area) <= 3]
    return sorted(same or recs, key=lambda r: r["ym"], reverse=True)[:24]

# ── 가공 ─────────────────────────────────────────────────────────────────
RESI = ("아파트", "연립", "다세대", "빌라", "단독", "다가구", "도시형생활주택", "주거용")
def build(items, gu, gc):
    lawd = SEOUL_GU[gu]
    stat = {"입력": len(items), "주거용": 0, "면적": 0, "가격": 0, "지오코딩": 0}
    rows = []
    for it in items:
        use  = f"{it.get('cltrUsgMclsCtgrNm','')} {it.get('cltrUsgSclsCtgrNm','')}"
        full = (it.get("onbidCltrNm") or "").strip()
        if "오피스텔" in use: continue
        if not any(k in use for k in RESI): continue
        stat["주거용"] += 1
        area = fnum(it.get("bldSqms"))
        if area is not None and area < MIN_AREA: continue
        stat["면적"] += 1
        minp, aprs = num(it.get("lowstBidPrcIndctCont")), num(it.get("apslEvlAmt"))
        is_apt = "아파트" in use
        if (not is_apt) and minp and minp > VILLA_CAP: continue
        stat["가격"] += 1

        jibun_addr, bldg, umd, jibun = parse_addr(full)
        coord = geocode(jibun_addr or f"{REGION_SD} {gu}", bldg, gc)
        if not coord: continue
        stat["지오코딩"] += 1

        hist = deal_history(lawd, umd, jibun, bldg, area) if umd else []
        last = hist[0]["amt"] * 10000 if hist else None
        avg  = int(sum(h["amt"] for h in hist) / len(hist) * 10000) if hist else None
        apt  = apt_info(it.get("ltnoPnu", ""), bldg) if is_apt else {}

        rows.append({
            "id": it.get("cltrMngNo", ""), "name": bldg or f"{umd} {jibun}",
            "addr": full, "gu": gu, "emd": umd, "jibun": jibun,
            "use": it.get("cltrUsgSclsCtgrNm", "") or it.get("cltrUsgMclsCtgrNm", ""),
            "isApt": is_apt, "kind": it.get("prptDivNm", ""),
            "area": area or "", "land": fnum(it.get("landSqms")) or "",
            "min": minp, "aprs": aprs, "disc": it.get("apslPrcCtrsLowstBidRto", ""),
            "fail": num(it.get("usbdNft")), "round": num(it.get("pbctNsq")),
            "status": it.get("pbctStatNm", ""), "end": it.get("cltrBidEndDt", ""),
            "org": it.get("orgNm", ""),
            "thumb": (it.get("thnlImgUrlAdr") or "").replace("&amp;", "&"),
            "deal": last, "dealAvg": avg,
            "hist": [{"ym": h["ym"], "amt": h["amt"] * 10000, "area": h["area"], "fl": h["floor"]} for h in hist],
            "gap": (last - minp) if (last and minp) else None,
            "hh": apt.get("hh"), "dong": apt.get("dong"), "used": apt.get("used"),
            "heat": apt.get("heat"), "kaptName": apt.get("kaptName"),
            "lat": coord[1], "lng": coord[0]})

    best = {}
    for r in rows:   # 회차 중복: 최저입찰가가 가장 낮은 행(=현재 회차)만
        k = r["id"] or f"{r['addr']}|{r['area']}"
        cur = best.get(k)
        if not cur or (r["min"] or 9e18) < (cur["min"] or 9e18):
            r["rounds"] = (cur["rounds"] + 1) if cur else 1
            best[k] = r
        else:
            cur["rounds"] = cur.get("rounds", 1) + 1
    out = list(best.values())
    print(f"    {gu}: " + " → ".join(f"{k} {v}" for k, v in stat.items()) + f" → 물건 {len(out)}건")
    return out

# ── 알림 ─────────────────────────────────────────────────────────────────
def read_prev():
    try:
        s = open(fp("data.js"), encoding="utf-8").read()
        return json.loads(s[s.index("["):s.rindex("]") + 1])
    except Exception: return []

def kakao_send(text, link):
    if not (KAKAO_REFRESH and KAKAO_REST):
        print("  (카카오 리프레시 토큰 없음 → 알림 생략)"); return
    try:
        data = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": KAKAO_REST,
                                       "refresh_token": KAKAO_REFRESH}).encode()
        tok = json.loads(urllib.request.urlopen(
            urllib.request.Request("https://kauth.kakao.com/oauth/token", data=data), timeout=10).read())["access_token"]
        tmpl = json.dumps({"object_type": "text", "text": text[:900],
                           "link": {"web_url": link, "mobile_web_url": link},
                           "button_title": "지도에서 보기"}, ensure_ascii=False)
        urllib.request.urlopen(urllib.request.Request(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            data=urllib.parse.urlencode({"template_object": tmpl}).encode(),
            headers={"Authorization": f"Bearer {tok}"}), timeout=10)
        print("  ✅ 카카오톡 알림 전송 완료")
    except urllib.error.HTTPError as e:
        print(f"  (카카오 알림 실패 HTTP {e.code}: {e.read().decode('utf-8','ignore')[:200]})")
    except Exception as e:
        print(f"  (카카오 알림 실패: {e})")

if __name__ == "__main__":
    if not DATA_KEY:   print("ERROR: DATA_KEY 없음"); sys.exit(1)
    if not KAKAO_REST: print("ERROR: KAKAO_REST_KEY 없음"); sys.exit(1)
    if not kakao_selftest(): sys.exit(1)

    gus = [ONLY_GU] if ONLY_GU in SEOUL_GU else list(SEOUL_GU)
    print(f"수집 시작 — 서울 {len(gus)}개 구")

    gc = {}
    if os.path.exists(fp("geocode_cache.json")):
        gc = {k: v for k, v in json.load(open(fp("geocode_cache.json"), encoding="utf-8")).items() if v}

    prev_ids = {x.get("id") for x in read_prev() if x.get("id")}
    cur = []
    for gu in gus:
        items = fetch_list(gu)
        if items: cur += build(items, gu, gc)

    cur.sort(key=lambda x: (x["gap"] is None, -(x["gap"] or 0)))
    json.dump(gc, open(fp("geocode_cache.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(fp("data.js"), "w", encoding="utf-8").write(
        "window.GONMAE = " + json.dumps(cur, ensure_ascii=False) + ";\n"
        "window.GONMAE_AT = " + json.dumps(time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 9 * 3600))) + ";")
    print(f"완료: 총 {len(cur)}건 → data.js")

    new = [x for x in cur if x["id"] and x["id"] not in prev_ids]
    if new or FORCE_NOTIFY:
        lines = [f"🏠 신규 공매 {len(new)}건 (서울 전체 {len(cur)}건)"]
        for x in new[:8]:
            eok = (x["min"] / 1e8) if x["min"] else 0
            gap = f" / 실거래차 {x['gap']/1e8:.1f}억" if x.get("gap") else ""
            lines.append(f"· [{x['gu']}] {x['use']} {x['area']}㎡ / 최저 {eok:.2f}억{gap}")
        kakao_send("\n".join(lines), PAGE_URL)
    else:
        print("  신규 0건 → 알림 생략")
