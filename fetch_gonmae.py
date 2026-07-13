#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
공매(온비드) 수집 → data.js + 신규매물 카카오톡 알림
v9: ★현재 회차 선택(회차 사다리 보존) / 아파트 재분류 / 온비드 딥링크 ID / 가격컷 제거
"""
import json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

DATA_KEY      = os.environ.get("DATA_KEY", "").strip()
KAKAO_REST    = os.environ.get("KAKAO_REST_KEY", "").strip()
KAKAO_REFRESH = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
ONLY_GU       = os.environ.get("ONLY_GU", "").strip()
FORCE_NOTIFY  = os.environ.get("FORCE_NOTIFY", "") == "1"

REGION_SD       = "서울특별시"
MAX_PAGES, ROWS = 10, 100
REALDEAL_MONTHS = 24
PRPT_DIV        = "0007,0005,0006,0008"
MIN_AREA        = 25.0          # 전용 25㎡ 미만은 수집 안 함 (그 위 크기·가격은 앱에서 필터)
PAGE_URL        = "https://bb7073.github.io/Gonmae/"

BASE = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2"
OP   = "getRlstCltrList2"
DTL_BASE = "https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2"   # 부동산 물건상세 조회 (승인 2026-07-09)
# 포털에 오퍼레이션ID가 한글명으로만 표시돼 후보를 순차 시도한다.
# 정확한 ID를 알면 Actions env DTL_OP=... 로 넣으면 추측 없이 그것만 쓴다.
# 오퍼레이션 ID 확정(포털 미리보기로 확인, 2026-07-14): getRlstDtlInf2
DTL_OPS  = [os.environ.get("DTL_OP", "").strip()] if os.environ.get("DTL_OP", "").strip() else ["getRlstDtlInf2"]
KAKAO_ADDR = "https://dapi.kakao.com/v2/local/search/address.json?query="
KAKAO_KW   = "https://dapi.kakao.com/v2/local/search/keyword.json?query="
RT = {"apt":"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
      "rh": "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
      "silv":"https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"}
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
def gi(d, *keys):
    """대소문자·언더스코어 무시 키 조회 (API가 필드명을 바꿔도 견디게)"""
    low = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in d.items()}
    for k in keys:
        v = low.get(re.sub(r"[^a-z0-9]", "", k.lower()))
        if v: return v
    return ""
def nrm(s): return re.sub(r"[\s\(\)0-9\-]|아파트|주상복합", "", s or "")
def now_kst(): return time.strftime("%Y%m%d%H%M", time.gmtime(time.time() + 9 * 3600))

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

_LIST_DUMPED = {"x": False}

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
        if not _LIST_DUMPED["x"]:
            _LIST_DUMPED["x"] = True
            print("  [목록필드] " + json.dumps(it[0], ensure_ascii=False)[:2000])
        out += it
        if len(it) < ROWS: break
        time.sleep(0.15)
    return out

# ── ★회차 처리 ───────────────────────────────────────────────────────────
# 목록 API는 한 물건을 '회차별로 여러 행'으로 준다(1회차 100% → 마지막 회차 10%).
# 예전 코드는 그 중 '가장 싼 행'을 골라서 마지막 회차 가격/마감일이 찍혔다.
# → 지금 입찰 가능한(마감이 아직 안 지난) 회차 중 가장 임박한 것을 채택하고,
#   나머지 회차는 ladder(가격 사다리)로 보존해 상세화면에 보여준다.
def _end(it): return re.sub(r"\D", "", gi(it, "cltrBidEndDt", "pbctBidEndDt", "bidEndDt", "bidClsgDt") or "")[:12]
def _bgn(it): return re.sub(r"\D", "", gi(it, "cltrBidBgnDt", "pbctBidBgnDt", "bidBgnDt", "bidStrtDt") or "")[:12]

def group_rounds(items):
    by = {}
    for it in items:
        k = gi(it, "cltrMngNo") or f"{gi(it,'onbidCltrNm')}|{gi(it,'bldSqms')}"
        by.setdefault(k, []).append(it)
    out, NOW = [], now_kst()
    for rows in by.values():
        rows.sort(key=lambda r: _end(r) or "999999999999")
        live = [r for r in rows if _end(r) and _end(r) >= NOW]
        cur = live[0] if live else rows[-1]
        ladder = [{"rd": num(gi(r, "pbctNsq", "pbctSqnc")) or None,
                   "min": num(gi(r, "lowstBidPrcIndctCont", "lowstBidPrc", "minBidPrc")),
                   "bgn": _bgn(r), "end": _end(r), "st": gi(r, "pbctStatNm")} for r in rows]
        out.append((cur, ladder))
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
    """[경도, 위도, 법정동코드10]. 법정동코드는 단지정보 조회(PNU 대체용)로 쓴다."""
    for q in [jibun_addr, f"{jibun_addr} {bldg}".strip()]:
        if not q: continue
        if cache.get(q): return cache[q]
        for url in (KAKAO_ADDR, KAKAO_KW):
            try:
                docs = json.loads(http_get(url + urllib.parse.quote(q),
                       headers={"Authorization": f"KakaoAK {KAKAO_REST}"})).get("documents", [])
                if docs:
                    d0 = docs[0]
                    ad = d0.get("address") or d0.get("road_address") or {}
                    bcode = (ad.get("b_code") or "")[:10]
                    c = [float(d0["x"]), float(d0["y"]), bcode]
                    cache[q] = c; return c
            except Exception: pass
            time.sleep(0.05)
    return None

# ── 온비드 상세(딥링크용 ID) ──────────────────────────────────────────────
_DTL_OP, _DUMPED = {"op": None}, {"x": False}

_DTL_ERR = {"n": 0}

def fetch_detail(mng, cdtn):
    if not (mng and cdtn):
        if _DTL_ERR["n"] < 1:
            _DTL_ERR["n"] += 1
            print(f"  [상세] 키 부족 → 호출 생략 (cltrMngNo={mng!r}, pbctCdtnNo={cdtn!r})")
        return {}
    if _DTL_ERR["n"] >= 10 and not _DTL_OP["op"]:
        return {}                      # 후보 전멸 → 상세 API 호출 중단
    ops = [_DTL_OP["op"]] if _DTL_OP["op"] else DTL_OPS
    for op in ops:
        q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "cltrMngNo": mng, "pbctCdtnNo": cdtn,
                                    "resultType": "json", "numOfRows": 10, "pageNo": 1}, safe="=")
        try:
            raw = http_get(f"{DTL_BASE}/{op}?{q}")
            d = json.loads(raw)
        except Exception as e:
            if _DTL_ERR["n"] < 10:
                _DTL_ERR["n"] += 1
                body = e.read().decode("utf-8", "ignore")[:180] if hasattr(e, "read") else str(e)[:180]
                print(f"  [상세] {op} 실패: {body}")
            continue
        if isinstance(d.get("result"), dict):          # {"result":{"resultCode":"03",...}}
            if _DTL_ERR["n"] < 3:
                _DTL_ERR["n"] += 1
                print(f"  [상세] {op} 응답: {json.dumps(d['result'], ensure_ascii=False)[:120]} "
                      f"(cltrMngNo={mng}, pbctCdtnNo={cdtn})")
            continue
        body = d.get("response", d).get("body", {})
        it = body.get("items") or {}
        it = it.get("item", []) if isinstance(it, dict) else it
        if isinstance(it, dict): it = [it]
        if not it: continue
        if not _DTL_OP["op"]:
            _DTL_OP["op"] = op; print(f"  [상세] 오퍼레이션 '{op}' 사용")
        if not _DUMPED["x"]:
            _DUMPED["x"] = True
            print("  [상세필드] " + json.dumps(it[0], ensure_ascii=False)[:1500])
        return it[0]
    return {}

def onbid_ids(dtl, cdtn):
    """온비드 물건상세 URL 파라미터. 4개 ID가 다 모여야 링크 생성."""
    o = {"plnmNo": gi(dtl, "plnmNo", "onbidPbancNo", "pbancNo"),
         "pbctNo": gi(dtl, "pbctNo"),
         "cltrNo": gi(dtl, "cltrNo", "onbidCltrno"),
         "cltrHstrNo": gi(dtl, "cltrHstrNo"),
         "pbctCdtnNo": gi(dtl, "pbctCdtnNo") or cdtn,
         "scrnGrpCd": gi(dtl, "scrnGrpCd", "cltrScrnGrpCd") or "0001"}
    return o if all(o[k] for k in ("plnmNo", "pbctNo", "cltrNo", "cltrHstrNo")) else {}

# ── 아파트 단지정보 ───────────────────────────────────────────────────────
_APT_LIST_OP, _APT_BASIS_OP = {"op": None}, {"op": None}
_BJD_CACHE, _KAPT_CACHE = {}, {}

def apt_list_by_bjd(bjd):
    if bjd in _BJD_CACHE: return _BJD_CACHE[bjd]
    ops = [_APT_LIST_OP["op"]] if _APT_LIST_OP["op"] else APT_LIST_OPS
    res = []
    for op in ops:
        q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "bjdCode": bjd,
                                    "numOfRows": 200, "pageNo": 1}, safe="=")
        try: its = xml_items(http_get(f"{APT_LIST_BASE}/{op}?{q}"))
        except Exception: continue
        if its or _APT_LIST_OP["op"]:
            if not _APT_LIST_OP["op"]:
                _APT_LIST_OP["op"] = op; print(f"  [단지목록] 오퍼레이션 '{op}' 사용")
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
        try: its = xml_items(http_get(f"{APT_BASIS_BASE}/{op}?{q}"))
        except Exception: continue
        if its:
            if not _APT_BASIS_OP["op"]:
                _APT_BASIS_OP["op"] = op; print(f"  [단지정보] 오퍼레이션 '{op}' 사용")
            it = its[0]
            info = {"hh": num(g(it, "kaptdaCnt")), "dong": num(g(it, "kaptDongCnt")),
                    "used": g(it, "kaptUsedate"), "heat": g(it, "codeHeatNm"),
                    "hall": g(it, "codeHallNm"), "kaptName": g(it, "kaptName")}
            break
    _KAPT_CACHE[kapt] = info
    time.sleep(0.05)
    return info

_MATCH_STAT = {"try": 0, "hit": 0, "nobjd": 0}

def apt_info(pnu, bjd, bldg):
    """공동주택 단지목록에 이름이 잡히면 = 아파트로 확정(+세대수·동수·사용승인일).
       - 법정동코드: 온비드 PNU 앞10자리 → 없으면 카카오 지오코딩의 b_code 사용
       - 이름: '제105동', '제씨동', '아파트' 같은 꼬리표를 떼고 부분일치
       온비드 용도가 '기타주거용건물'로 잘못 찍힌 아파트(예: 여의도자이)도 여기서 구제된다."""
    code10 = (pnu or "")[:10] if pnu and len(pnu) >= 10 else (bjd or "")
    if not bldg: return {}
    if not code10 or len(code10) < 10:
        _MATCH_STAT["nobjd"] += 1
        return {}
    base = re.sub(r"\s*제?\s*[0-9A-Za-z가-힣]{0,4}동\s*$", "", bldg).strip()  # 제105동/제씨동 제거
    key = nrm(base) or nrm(bldg)
    if not key: return {}
    _MATCH_STAT["try"] += 1
    for kcode, name in apt_list_by_bjd(code10):
        n = nrm(name)
        if n and (n in key or key in n):
            _MATCH_STAT["hit"] += 1
            return apt_basis(kcode)
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
def _fetch_deal_chunk(lawd, kind, ym):
    q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "LAWD_CD": lawd, "DEAL_YMD": ym,
                                "numOfRows": 1000, "pageNo": 1}, safe="=")
    try: return kind, ym, xml_items(http_get(f"{RT[kind]}?{q}"))
    except Exception: return kind, ym, []

def load_deals(lawd):
    if lawd in _DEAL: return _DEAL[lawd]
    by_jb, by_nm = {}, {}
    jobs = [(k, ym) for k in ("apt", "rh", "silv") for ym in ym_list(REALDEAL_MONTHS)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        for kind, ym, its in ex.map(lambda j: _fetch_deal_chunk(lawd, j[0], j[1]), jobs):
            for it in its:
                amt = num(g(it, "dealAmount", "거래금액"))
                if not amt: continue
                nm  = g(it, "aptNm", "mhouseNm", "아파트", "연립다세대")
                umd, jb = g(it, "umdNm", "법정동"), g(it, "jibun", "지번")
                rec = {"ym": ym, "amt": amt, "area": fnum(g(it, "excluUseAr", "전용면적")) or "",
                       "floor": g(it, "floor", "층"), "name": nm}
                if umd and jb: by_jb.setdefault((umd.strip(), jb.strip()), []).append(rec)
                if nm: by_nm.setdefault(nm.replace(" ", ""), []).append(rec)
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
RESI  = ("아파트", "연립", "다세대", "빌라", "단독", "다가구", "도시형생활주택", "주거용")
VILLA = ("다세대", "다가구", "단독")     # ★사용자 정의: 이 셋만 빌라

def _process_one(pack, gu, lawd, gc):
    it, ladder = pack
    use  = f"{gi(it,'cltrUsgMclsCtgrNm')} {gi(it,'cltrUsgSclsCtgrNm')}"
    full = (gi(it, "onbidCltrNm") or "").strip()
    if "오피스텔" in use: return "skip", None
    if not any(k in use for k in RESI): return "skip", None

    area = fnum(gi(it, "bldSqms"))
    if area is not None and area < MIN_AREA: return "resi", None

    minp = num(gi(it, "lowstBidPrcIndctCont", "lowstBidPrc", "minBidPrc"))
    aprs = num(gi(it, "apslEvlAmt"))

    jibun_addr, bldg, umd, jibun = parse_addr(full)
    coord = geocode(jibun_addr or f"{REGION_SD} {gu}", bldg, gc)
    if not coord: return "area", None
    bjd = coord[2] if len(coord) > 2 else ""

    apt = apt_info(gi(it, "ltnoPnu"), bjd, bldg)
    if "아파트" in use or apt.get("hh"): typ = "apt"
    elif any(k in use for k in VILLA):   typ = "villa"
    else:                                typ = "etc"

    hist = deal_history(lawd, umd, jibun, bldg, area) if umd else []
    last = hist[0]["amt"] * 10000 if hist else None
    avg  = int(sum(h["amt"] for h in hist) / len(hist) * 10000) if hist else None

    row = {
        "id": gi(it, "cltrMngNo"), "cd": gi(it, "pbctCdtnNo"),
        "name": bldg or f"{umd} {jibun}", "addr": full, "gu": gu, "emd": umd, "jibun": jibun,
        "use": gi(it, "cltrUsgSclsCtgrNm") or gi(it, "cltrUsgMclsCtgrNm"),
        "type": typ, "isApt": typ == "apt", "kind": gi(it, "prptDivNm"),
        "area": area or "", "land": fnum(gi(it, "landSqms")) or "",
        "min": minp, "aprs": aprs,
        "disc": round(minp / aprs * 100) if (minp and aprs) else None,
        "fail": num(gi(it, "usbdNft")), "round": num(gi(it, "pbctNsq", "pbctSqnc")),
        "status": gi(it, "pbctStatNm"), "bgn": _bgn(it), "end": _end(it),
        "ladder": ladder, "rounds": len(ladder),
        "org": gi(it, "orgNm"),
        "thumb": (gi(it, "thnlImgUrlAdr") or "").replace("&amp;", "&"),
        "deal": last, "dealAvg": avg,
        "hist": [{"ym": h["ym"], "amt": h["amt"] * 10000, "area": h["area"], "fl": h["floor"]} for h in hist],
        "gap": (last - minp) if (last and minp) else None,
        "hh": apt.get("hh"), "dong": apt.get("dong"), "used": apt.get("used"),
        "heat": apt.get("heat"), "hall": apt.get("hall"), "kaptName": apt.get("kaptName"),
        "lat": coord[1], "lng": coord[0]}
    row["on"] = onbid_ids(it, row["cd"]) or onbid_ids(fetch_detail(row["id"], row["cd"]), row["cd"])
    return "ok", row

_STAGE = {"resi": 1, "area": 2, "ok": 3}

def build(items, gu, gc):
    lawd = SEOUL_GU[gu]
    packs = group_rounds(items)
    stat = {"행": len(items), "물건": len(packs), "주거용": 0, "면적": 0, "지오코딩": 0}
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for tag, row in ex.map(lambda p: _process_one(p, gu, lawd, gc), packs):
            lvl = _STAGE.get(tag, 0)
            if lvl >= 1: stat["주거용"] += 1
            if lvl >= 2: stat["면적"] += 1
            if lvl >= 3: stat["지오코딩"] += 1; rows.append(row)
    print(f"    {gu}: " + " → ".join(f"{k} {v}" for k, v in stat.items()) + f" → 물건 {len(rows)}건"
          f" (아파트 {sum(1 for r in rows if r['type']=='apt')}, 세대수확보 {sum(1 for r in rows if r.get('hh'))})")
    return rows

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
    print(f"수집 시작 — 서울 {len(gus)}개 구 (기준 {now_kst()} KST)")

    gc = {}
    if os.path.exists(fp("geocode_cache.json")):
        # 법정동코드(3번째 값)가 없는 구버전 캐시는 버리고 다시 지오코딩한다(세대수 조회에 필요)
        gc = {k: v for k, v in json.load(open(fp("geocode_cache.json"), encoding="utf-8")).items()
              if v and len(v) >= 3}

    prev_ids = {x.get("id") for x in read_prev() if x.get("id")}
    cur, t0 = [], time.time()
    for i, gu in enumerate(gus, 1):
        print(f"[{i}/{len(gus)}] {gu} 시작 — 경과 {int(time.time()-t0)}초")
        items = fetch_list(gu)
        if items: cur += build(items, gu, gc)

    print(f"전체 소요 {int(time.time()-t0)}초")
    cur.sort(key=lambda x: (x["gap"] is None, -(x["gap"] or 0)))
    json.dump(gc, open(fp("geocode_cache.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(fp("data.js"), "w", encoding="utf-8").write(
        "window.GONMAE = " + json.dumps(cur, ensure_ascii=False) + ";\n"
        "window.GONMAE_AT = " + json.dumps(time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 9 * 3600))) + ";")
    print(f"[단지매칭] 시도 {_MATCH_STAT['try']} / 성공 {_MATCH_STAT['hit']} / 법정동코드없음 {_MATCH_STAT['nobjd']}")
    print(f"완료: 총 {len(cur)}건 → data.js "
          f"(아파트 {sum(1 for x in cur if x['type']=='apt')} / "
          f"빌라 {sum(1 for x in cur if x['type']=='villa')} / "
          f"기타 {sum(1 for x in cur if x['type']=='etc')} / "
          f"온비드링크 {sum(1 for x in cur if x['on'])}건)")

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
