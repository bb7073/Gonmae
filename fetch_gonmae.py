#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
공매(온비드) 수집 → data.js + 신규매물 카카오톡 알림
v10: ★지분물건 판별(상세 API 면적정보 '비고' 파싱 + 실거래가 지분보정)
     ★세대수 매칭 강화(실거래 단지명 사용 + 시군구 단지목록 폴백 + 실패로그)
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
TG_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "").strip()
TG_CHAT       = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
FORCE_NOTIFY  = os.environ.get("FORCE_NOTIFY", "") == "1"
DEBUG_MNG     = os.environ.get("DEBUG_MNG", "").strip()   # 예: 2026-01663-001 → 상세 응답 원문 통째 출력

REGION_SD       = "서울특별시"
MAX_PAGES, ROWS = 10, 100
REALDEAL_MONTHS = 24
PRPT_DIV        = "0007,0005,0006,0008"
MIN_AREA        = 25.0          # ★지분물건은 '전체면적' 기준으로 판정 (지분면적으로 자르지 않음)
PAGE_URL        = "https://bb7073.github.io/Gonmae/"

BASE = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2"
OP   = "getRlstCltrList2"
DTL_BASE = "https://apis.data.go.kr/B010003/OnbidRlstDtlSrvc2"
DTL_OPS  = [os.environ.get("DTL_OP", "").strip()] if os.environ.get("DTL_OP", "").strip() else ["getRlstDtlInf2"]
KAKAO_ADDR = "https://dapi.kakao.com/v2/local/search/address.json?query="
KAKAO_KW   = "https://dapi.kakao.com/v2/local/search/keyword.json?query="
RT = {"apt":"https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
      "rh": "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
      "silv":"https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"}
APT_LIST_BASE  = "https://apis.data.go.kr/1613000/AptListService3"
APT_LIST_OPS   = ["getLegaldongAptList3"]                     # 확인됨(2026-07-14)
APT_SGG_OPS    = ["getSigunguAptList3", "getSigunguAptList"]  # ★구 단위 폴백(후보 순차 시도)
APT_BASIS_BASE = "https://apis.data.go.kr/1613000/AptBasisInfoServiceV4"
APT_BASIS_OPS  = ["getAphusBassInfoV4"]                       # kaptdaCnt = 세대수
APT_DTL_OP     = "getAphusDtlInfoV4"

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

def api_items(raw):
    raw = (raw or "").strip()
    if raw.startswith("{"):
        d = json.loads(raw)
        body = d.get("response", d).get("body", {}) or {}
        it = body.get("items", body.get("item", []))
        if isinstance(it, dict): it = it.get("item", it)
        if isinstance(it, dict): it = [it]
        return it or []
    return xml_items(raw)
def g(d, *keys):
    for k in keys:
        if d.get(k): return d[k]
    return ""
def gi(d, *keys):
    low = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in d.items()}
    for k in keys:
        v = low.get(re.sub(r"[^a-z0-9]", "", k.lower()))
        if v: return v
    return ""
def nrm(s): return re.sub(r"[\s\(\)0-9\-]|아파트|주상복합", "", s or "")
def now_kst(): return time.strftime("%Y%m%d%H%M", time.gmtime(time.time() + 9 * 3600))

# ── ★지분 파싱 ────────────────────────────────────────────────────────────
# 온비드 세부정보 '면적정보'의 비고 문구:
#   건물(건물) 29.985㎡ / 비고 "지분(총면적 59.97 2분의1 지분)"          ← 이게 진짜 지분매각
#   토지(대)  10.37㎡  / 비고 "지분(총면적 28,587.8 28587.8분의 10.37 지분)"  ← 대지권 비율(일반물건에도 있음)
# 상세 API의 필드명을 모르므로 응답 안의 모든 문자열을 훑되,
# '총면적 × 지분율 ≈ 온비드 건물면적(bldSqms)'을 만족하는 것만 채택 → 토지행과 자동 분리된다.
FRAC_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*분\s*의\s*([\d,]+(?:\.\d+)?)")
TOT_RE  = re.compile(r"총\s*면적\s*([\d,]+(?:\.\d+)?)")

def _f(s):
    try: return float(str(s).replace(",", ""))
    except Exception: return None
def _fmt(x):
    return str(int(x)) if abs(x - int(x)) < 1e-9 else f"{x:g}"
def _strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from _strings(v)
    elif isinstance(o, list):
        for v in o: yield from _strings(v)
    elif isinstance(o, str):
        yield o

def parse_share(detail, bld_area):
    """{'ratio':0.5,'full':59.97,'txt':'1/2','raw':...} 또는 None"""
    if not detail: return None
    for s in _strings(detail):
        if "분의" not in s: continue
        mf = FRAC_RE.search(s)
        if not mf: continue
        den, nume = _f(mf.group(1)), _f(mf.group(2))
        if not den or not nume or den <= 0: continue
        ratio = nume / den
        if ratio >= 0.999: continue
        mt  = TOT_RE.search(s)
        tot = _f(mt.group(1)) if mt else None
        if not (tot and bld_area): continue
        if abs(tot * ratio - bld_area) > max(0.5, bld_area * 0.05): continue   # 건물행 검증
        return {"ratio": round(ratio, 6), "full": tot,
                "txt": f"{_fmt(nume)}/{_fmt(den)}", "raw": s.strip()[:80]}
    return None

def share_from_name(name):
    t = name or ""
    if "지분" not in t: return None
    m = re.search(r"(\d+)\s*/\s*(\d+)", t)
    return {"ratio": (int(m.group(1)) / int(m.group(2))) if m else None,
            "full": None, "txt": (f"{m.group(1)}/{m.group(2)}" if m else "지분"), "raw": "물건명 표기"}

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
            print("  [목록필드] " + json.dumps(it[0], ensure_ascii=False)[:1200])
        out += it
        if len(it) < ROWS: break
        time.sleep(0.15)
    return out

# ── 회차 처리 ────────────────────────────────────────────────────────────
def _end(it): return re.sub(r"\D", "", gi(it, "cltrBidEndDt", "pbctBidEndDt", "bidEndDt", "bidClsgDt") or "")[:12]
def _bgn(it): return re.sub(r"\D", "", gi(it, "cltrBidBgngDt", "cltrBidBgnDt", "pbctBidBgngDt", "bidBgngDt") or "")[:12]

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
                    c = [float(d0["x"]), float(d0["y"]), (ad.get("b_code") or "")[:10]]
                    cache[q] = c; return c
            except Exception: pass
            time.sleep(0.05)
    return None

# ── 온비드 상세 ──────────────────────────────────────────────────────────
_DTL_OP, _DUMPED, _DTL_ERR = {"op": None}, {"x": False}, {"n": 0}

def fetch_detail(mng, cdtn):
    """지분·면적 확인용. 응답 JSON 통째로 반환(필드명 의존 없이 문자열 스캔)."""
    if not mng: return {}
    if _DTL_ERR["n"] >= 10 and not _DTL_OP["op"]: return {}
    for op in ([_DTL_OP["op"]] if _DTL_OP["op"] else DTL_OPS):
        prm = {"serviceKey": DATA_KEY, "cltrMngNo": mng, "resultType": "json",
               "numOfRows": 50, "pageNo": 1}
        if cdtn: prm["pbctCdtnNo"] = cdtn
        try:
            d = json.loads(http_get(f"{DTL_BASE}/{op}?{urllib.parse.urlencode(prm, safe='=')}"))
        except Exception as e:
            if _DTL_ERR["n"] < 5:
                _DTL_ERR["n"] += 1
                body = e.read().decode("utf-8", "ignore")[:160] if hasattr(e, "read") else str(e)[:160]
                print(f"  [상세] {op} 실패: {body}")
            continue
        if isinstance(d.get("result"), dict) and str(d["result"].get("resultCode", "00")) not in ("00", "0"):
            if _DTL_ERR["n"] < 3:
                _DTL_ERR["n"] += 1
                print(f"  [상세] {op} 응답: {json.dumps(d['result'], ensure_ascii=False)[:120]} ({mng})")
            continue
        if not _DTL_OP["op"]:
            _DTL_OP["op"] = op; print(f"  [상세] 오퍼레이션 '{op}' 사용")
        if DEBUG_MNG and mng == DEBUG_MNG:
            print(f"  [상세원문 {mng}] " + json.dumps(d, ensure_ascii=False)[:4000])
        elif not _DUMPED["x"]:
            _DUMPED["x"] = True
            print("  [상세필드] " + json.dumps(d, ensure_ascii=False)[:1200])
        return d
    return {}

def onbid_ids(it, cdtn):
    o = {"c":  str(gi(it, "onbidCltrno", "cltrNo") or ""),
         "p":  str(gi(it, "onbidPbancNo", "plnmNo", "pbancNo") or ""),
         "b":  str(gi(it, "pbctNo") or ""),
         "cd": str(gi(it, "pbctCdtnNo") or cdtn or ""),
         "dv": str(gi(it, "prptDivCd") or "0007")}
    return o if (o["c"] and o["p"] and o["b"] and o["cd"]) else {}

# ── 아파트 단지정보 ───────────────────────────────────────────────────────
_APT_LIST_OP, _APT_SGG_OP, _APT_BASIS_OP = {"op": None}, {"op": None}, {"op": None}
_BJD_CACHE, _SGG_CACHE, _KAPT_CACHE = {}, {}, {}
_APT_ERR, _APT_SERR, _APT_BERR = {"x": False}, {"x": False}, {"x": False}
_MATCH_STAT = {"try": 0, "hit": 0, "viaSgg": 0, "nobjd": 0}
_MISS_LOG = {"n": 0}

def _pairs(its):
    return [(g(it, "kaptCode", "kaptcode"), g(it, "kaptName", "kaptname")) for it in its]

def apt_list_by_bjd(bjd):
    if bjd in _BJD_CACHE: return _BJD_CACHE[bjd]
    res = []
    for op in ([_APT_LIST_OP["op"]] if _APT_LIST_OP["op"] else APT_LIST_OPS):
        q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "bjdCode": bjd,
                                    "numOfRows": 500, "pageNo": 1}, safe="=")
        try:
            its = api_items(http_get(f"{APT_LIST_BASE}/{op}?{q}"))
        except Exception as e:
            if not _APT_ERR["x"]:
                _APT_ERR["x"] = True
                body = e.read().decode("utf-8", "ignore")[:200] if hasattr(e, "read") else str(e)[:200]
                print(f"  [단지목록/동] {op} 실패: {body}")
            continue
        if not _APT_LIST_OP["op"] and its:
            _APT_LIST_OP["op"] = op; print(f"  [단지목록/동] 오퍼레이션 '{op}' 사용")
        res = _pairs(its); break
    _BJD_CACHE[bjd] = res
    time.sleep(0.05)
    return res

def apt_list_by_sgg(sgg):
    """★법정동 목록이 비거나 매칭 실패할 때 쓰는 구(區) 전체 단지목록. 구별 1회만 조회."""
    if sgg in _SGG_CACHE: return _SGG_CACHE[sgg]
    res = []
    for op in ([_APT_SGG_OP["op"]] if _APT_SGG_OP["op"] else APT_SGG_OPS):
        q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "sigunguCode": sgg,
                                    "numOfRows": 2000, "pageNo": 1}, safe="=")
        try:
            its = api_items(http_get(f"{APT_LIST_BASE}/{op}?{q}"))
        except Exception as e:
            if not _APT_SERR["x"]:
                _APT_SERR["x"] = True
                body = e.read().decode("utf-8", "ignore")[:200] if hasattr(e, "read") else str(e)[:200]
                print(f"  [단지목록/구] {op} 실패: {body}")
            continue
        if its:
            if not _APT_SGG_OP["op"]:
                _APT_SGG_OP["op"] = op
                print(f"  [단지목록/구] 오퍼레이션 '{op}' 사용 — {sgg} {len(its)}단지")
            res = _pairs(its); break
    _SGG_CACHE[sgg] = res
    time.sleep(0.05)
    return res

def apt_basis(kapt):
    if kapt in _KAPT_CACHE: return _KAPT_CACHE[kapt]
    info = {}
    for op in ([_APT_BASIS_OP["op"]] if _APT_BASIS_OP["op"] else APT_BASIS_OPS):
        q = urllib.parse.urlencode({"serviceKey": DATA_KEY, "kaptCode": kapt}, safe="=")
        try:
            its = api_items(http_get(f"{APT_BASIS_BASE}/{op}?{q}"))
            if not its and not _APT_BERR["x"]:
                _APT_BERR["x"] = True; print(f"  [단지정보] {op} 응답 비어있음")
        except Exception as e:
            if not _APT_BERR["x"]:
                _APT_BERR["x"] = True
                body = e.read().decode("utf-8", "ignore")[:200] if hasattr(e, "read") else str(e)[:200]
                print(f"  [단지정보] {op} 실패: {body}")
            continue
        if its:
            if not _APT_BASIS_OP["op"]:
                _APT_BASIS_OP["op"] = op; print(f"  [단지정보] 오퍼레이션 '{op}' 사용")
            it = its[0]
            info = {"hh": num(gi(it, "kaptdaCnt")), "dong": num(gi(it, "kaptDongCnt")),
                    "used": gi(it, "kaptUsedate"), "heat": gi(it, "codeHeatNm"),
                    "hall": gi(it, "codeHallNm"), "kaptName": gi(it, "kaptName"),
                    "top": num(gi(it, "kaptTopFloor")) or None}
            try:
                q2 = urllib.parse.urlencode({"serviceKey": DATA_KEY, "kaptCode": kapt}, safe="=")
                d2 = api_items(http_get(f"{APT_BASIS_BASE}/{APT_DTL_OP}?{q2}"))
                if d2:
                    info["park"] = num(gi(d2[0], "kaptdPcnt")) + num(gi(d2[0], "kaptdPcntu")) or None
                    info["subway"] = gi(d2[0], "subwayLine")
                    info["subwayMin"] = gi(d2[0], "kaptdWtimesub")
            except Exception:
                pass
            break
    _KAPT_CACHE[kapt] = info
    time.sleep(0.05)
    return info

def _keys(bldg, names):
    """매칭 후보키: 물건명에서 뽑은 건물명 + ★실거래에 잡힌 단지명(같은 지번)"""
    out = []
    for s in [bldg] + list(names or []):
        if not s: continue
        base = re.sub(r"\s*제?\s*[0-9A-Za-z가-힣]{0,4}동\s*$", "", str(s)).strip()
        for k in (nrm(base), nrm(s)):
            if k and len(k) >= 2 and k not in out: out.append(k)
    return out

def _match(pool, keys):
    for kcode, name in pool:
        n = nrm(name)
        if not n or len(n) < 2: continue
        for k in keys:
            if n == k or n in k or k in n: return kcode
    return None

def apt_info(pnu, bjd, lawd, bldg, names, apt_use):
    code10 = (pnu or "")[:10] if pnu and len(pnu) >= 10 else (bjd or "")
    keys = _keys(bldg, names)
    if not keys: return {}
    _MATCH_STAT["try"] += 1
    if not code10 or len(code10) < 10:
        _MATCH_STAT["nobjd"] += 1
        pool = []
    else:
        pool = apt_list_by_bjd(code10)
    kcode = _match(pool, keys)
    if not kcode:                                    # ★구 전체 목록으로 재시도
        kcode = _match(apt_list_by_sgg(lawd), keys)
        if kcode: _MATCH_STAT["viaSgg"] += 1
    if not kcode:
        if apt_use and _MISS_LOG["n"] < 10:
            _MISS_LOG["n"] += 1
            print(f"  [단지매칭 실패] 키={keys} 법정동={code10} 동목록후보={[n for _, n in pool][:6]}")
        return {}
    _MATCH_STAT["hit"] += 1
    return apt_basis(kcode)

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

def deal_names(lawd, umd, jibun):
    """★같은 지번의 실거래에 찍힌 단지명 — 단지매칭 키로 재활용"""
    if not (umd and jibun): return []
    by_jb, _ = load_deals(lawd)
    return list({r["name"] for r in by_jb.get((umd, jibun), []) if r["name"]})

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
VILLA = ("다세대", "다가구", "단독")

def _process_one(pack, gu, lawd, gc):
    it, ladder = pack
    use  = f"{gi(it,'cltrUsgMclsCtgrNm')} {gi(it,'cltrUsgSclsCtgrNm')}"
    full = (gi(it, "onbidCltrNm") or "").strip()
    if "오피스텔" in use: return "skip", None
    if not any(k in use for k in RESI): return "skip", None

    area = fnum(gi(it, "bldSqms"))          # ★지분물건이면 이 값은 '지분면적'이다
    mng, cdtn = gi(it, "cltrMngNo"), gi(it, "pbctCdtnNo")

    sh = parse_share(fetch_detail(mng, cdtn), area) or share_from_name(full)
    ratio = (sh or {}).get("ratio")
    farea = (sh or {}).get("full") or (round(area / ratio, 2) if (area and ratio) else area)

    if farea is not None and farea < MIN_AREA: return "resi", None   # 전체면적 기준 컷

    minp = num(gi(it, "lowstBidPrcIndctCont", "lowstBidPrc", "minBidPrc"))
    aprs = num(gi(it, "apslEvlAmt"))

    jibun_addr, bldg, umd, jibun = parse_addr(full)
    coord = geocode(jibun_addr or f"{REGION_SD} {gu}", bldg, gc)
    if not coord: return "area", None
    bjd = coord[2] if len(coord) > 2 else ""

    names = deal_names(lawd, umd, jibun)
    apt = apt_info(gi(it, "ltnoPnu"), bjd, lawd, bldg, names, "아파트" in use or "아파트" in (bldg or ""))
    if "아파트" in use or apt.get("hh"): typ = "apt"
    elif any(k in use for k in VILLA):   typ = "villa"
    else:                                typ = "etc"

    hist = deal_history(lawd, umd, jibun, bldg, farea) if umd else []   # ★전체면적으로 매칭
    last = hist[0]["amt"] * 10000 if hist else None
    avg  = int(sum(h["amt"] for h in hist) / len(hist) * 10000) if hist else None
    # ★지분물건은 실거래(전체) × 지분율로 환산해야 최저입찰가와 비교가 성립한다
    last_adj = int(last * ratio) if (last and ratio) else last

    row = {
        "id": mng, "cd": cdtn,
        "name": bldg or f"{umd} {jibun}", "addr": full, "gu": gu, "emd": umd, "jibun": jibun,
        "use": gi(it, "cltrUsgSclsCtgrNm") or gi(it, "cltrUsgMclsCtgrNm"),
        "type": typ, "isApt": typ == "apt", "kind": gi(it, "prptDivNm"),
        "area": area or "", "land": fnum(gi(it, "landSqms")) or "",
        "fullArea": farea if ratio else "",              # 전체 전용면적(지분물건만)
        "share": (sh or {}).get("txt", ""),              # "1/2"
        "shareRatio": ratio or "",                       # 0.5
        "shareRaw": (sh or {}).get("raw", ""),           # 온비드 비고 원문
        "min": minp, "aprs": aprs,
        "disc": round(minp / aprs * 100) if (minp and aprs) else None,
        "fail": num(gi(it, "usbdNft")), "round": num(gi(it, "pbctNsq", "pbctSqnc")),
        "status": gi(it, "pbctStatNm"), "bgn": _bgn(it), "end": _end(it),
        "ladder": ladder, "rounds": len(ladder),
        "org": gi(it, "orgNm"),
        "thumb": (gi(it, "thnlImgUrlAdr") or "").replace("&amp;", "&"),
        "deal": last,                                    # 실거래(전체 1채 기준)
        "dealAdj": last_adj,                             # 지분 환산 실거래
        "dealAvg": avg,
        "hist": [{"ym": h["ym"], "amt": h["amt"] * 10000, "area": h["area"], "fl": h["floor"]} for h in hist],
        "gap": (last_adj - minp) if (last_adj and minp) else None,
        "hh": apt.get("hh"), "dong": apt.get("dong"), "used": apt.get("used"),
        "heat": apt.get("heat"), "hall": apt.get("hall"), "kaptName": apt.get("kaptName"),
        "park": apt.get("park"), "subway": apt.get("subway"), "subwayMin": apt.get("subwayMin"),
        "lat": coord[1], "lng": coord[0]}
    row["on"] = onbid_ids(it, row["cd"])
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
          f" (아파트 {sum(1 for r in rows if r['type']=='apt')},"
          f" 세대수확보 {sum(1 for r in rows if r.get('hh'))},"
          f" 지분 {sum(1 for r in rows if r.get('share'))})")
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

# ── 텔레그램 신규매물 알림 ──────────────────────────────────────────────
def _eok(v):
    try: return f"{v/1e8:.2f}억"
    except Exception: return "—"

def onbid_url(d):
    o = d.get("on") or {}
    if o.get("c") and o.get("p") and o.get("b") and o.get("cd"):
        return ("https://m.onbid.co.kr/op/cltrpbancinf/cltrdtl/CltrDtlController/mvmnCltrDtl.do"
                f"?cltrScrnGrpCd=0001&cltrPrptDivCd={o.get('dv') or '0007'}"
                f"&onbidCltrno={o['c']}&onbidPbancNo={o['p']}&pbctNo={o['b']}&pbctCdtnNo={o['cd']}")
    return ""

def naver_map_url(d):
    addr = re.sub(r"\s*외\s*\d+\s*필지", "", d.get("addr") or "")
    addr = re.split(r"\s제?\s*[지B]?\d+\s*층", addr)[0]
    addr = re.sub(r"\s*\([^)]*\)\s*$", "", addr).strip()
    return "https://map.naver.com/p/search/" + urllib.parse.quote(addr)

def tg_send(text):
    if not (TG_TOKEN and TG_CHAT):
        print("  (텔레그램 토큰/챗ID 없음 → 알림 생략)"); return False
    try:
        data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text,
                                       "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=data), timeout=15)
        return True
    except urllib.error.HTTPError as e:
        print(f"  (텔레그램 실패 HTTP {e.code}: {e.read().decode('utf-8','ignore')[:200]})")
    except Exception as e:
        print(f"  (텔레그램 실패: {e})")
    return False

def notify_new(items):
    if not items:
        print("  신규매물 없음 → 텔레그램 생략"); return
    items = sorted(items, key=lambda x: -(x.get("gap") or 0))
    header = f"🏠 새 공매 {len(items)}건 ({time.strftime('%Y-%m-%d', time.gmtime(time.time()+9*3600))})\n"
    blocks = []
    for d in items:
        L = [f"• {d.get('name') or d.get('addr')}", f"  {d.get('addr','')}"]
        disc = f" ({d['disc']}%)" if d.get("disc") else ""
        L.append(f"  최저 {_eok(d.get('min'))} / 감정 {_eok(d.get('aprs'))}{disc}")
        if (d.get("gap") or 0) > 0:
            L.append(f"  실거래 대비 {_eok(d['gap'])} 낮음")
        if d.get("hh"):    L.append(f"  세대수 {d['hh']}세대")
        if d.get("share"): L.append(f"  ⚠️ 지분물건 {d['share']}")
        ou = onbid_url(d)
        if ou: L.append(f"  온비드 {ou}")
        L.append(f"  네이버지도 {naver_map_url(d)}")
        blocks.append("\n".join(L))
    msg, sent = header, 0
    for b in blocks:
        if len(msg) + len(b) + 2 > 3800:
            if tg_send(msg): sent += 1
            msg = "(계속)\n"
        msg += ("\n" if msg.strip() else "") + b
    if msg.strip():
        if tg_send(msg): sent += 1
    print(f"  ✅ 텔레그램 신규매물 {len(items)}건 전송 (메시지 {sent}통)")

if __name__ == "__main__":
    if not DATA_KEY:   print("ERROR: DATA_KEY 없음"); sys.exit(1)
    if not KAKAO_REST: print("ERROR: KAKAO_REST_KEY 없음"); sys.exit(1)
    if not kakao_selftest(): sys.exit(1)

    gus = [ONLY_GU] if ONLY_GU in SEOUL_GU else list(SEOUL_GU)
    print(f"수집 시작 — 서울 {len(gus)}개 구 (기준 {now_kst()} KST)")

    gc = {}
    if os.path.exists(fp("geocode_cache.json")):
        gc = {k: v for k, v in json.load(open(fp("geocode_cache.json"), encoding="utf-8")).items()
              if v and len(v) >= 3}

    prev_by_id = {x.get("id"): x for x in read_prev() if x.get("id")}
    cur, t0 = [], time.time()
    for i, gu in enumerate(gus, 1):
        print(f"[{i}/{len(gus)}] {gu} 시작 — 경과 {int(time.time()-t0)}초")
        items = fetch_list(gu)
        if items: cur += build(items, gu, gc)

    print(f"전체 소요 {int(time.time()-t0)}초")
    cur.sort(key=lambda x: (x["gap"] is None, -(x["gap"] or 0)))

    # 신규매물 판별: 최초 등장일(first) 기록 + 오늘 새로 뜬 건 골라내기
    today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 9 * 3600))
    for x in cur:
        p = prev_by_id.get(x.get("id"))
        if p and p.get("first"):
            x["first"] = p["first"]          # 이전 등장일 승계
        elif p:
            x["first"] = "-"                  # 이전에도 있었으나 미기록 → 오늘 신규 아님
        else:
            x["first"] = today                # 처음 보는 물건
    new_items = [x for x in cur if x["first"] == today] if prev_by_id else []

    json.dump(gc, open(fp("geocode_cache.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(fp("data.js"), "w", encoding="utf-8").write(
        "window.GONMAE = " + json.dumps(cur, ensure_ascii=False) + ";\n"
        "window.GONMAE_AT = " + json.dumps(time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 9 * 3600))) + ";")
    print(f"[단지매칭] 시도 {_MATCH_STAT['try']} / 성공 {_MATCH_STAT['hit']} "
          f"(구목록으로 구제 {_MATCH_STAT['viaSgg']}) / 법정동코드없음 {_MATCH_STAT['nobjd']}")
    print(f"완료: 총 {len(cur)}건 → data.js "
          f"(아파트 {sum(1 for x in cur if x['type']=='apt')} / "
          f"빌라 {sum(1 for x in cur if x['type']=='villa')} / "
          f"기타 {sum(1 for x in cur if x['type']=='etc')} / "
          f"세대수 {sum(1 for x in cur if x.get('hh'))} / "
          f"지분물건 {sum(1 for x in cur if x.get('share'))} / "
          f"온비드링크 {sum(1 for x in cur if x['on'])}건)")
    notify_new(new_items)

    new = [x for x in cur if x["id"] and x["id"] not in prev_ids]
    if new or FORCE_NOTIFY:
        lines = [f"🏠 신규 공매 {len(new)}건 (서울 전체 {len(cur)}건)"]
        for x in new[:8]:
            eok = (x["min"] / 1e8) if x["min"] else 0
            gap = f" / 실거래차 {x['gap']/1e8:.1f}억" if x.get("gap") else ""
            sh  = f" ⚠{x['share']}지분" if x.get("share") else ""
            lines.append(f"· [{x['gu']}] {x['use']} {x['area']}㎡{sh} / 최저 {eok:.2f}억{gap}")
        kakao_send("\n".join(lines), PAGE_URL)
    else:
        print("  신규 0건 → 알림 생략")
