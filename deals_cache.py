# -*- coding: utf-8 -*-
"""
deals_cache.py  —  국토부 실거래 공유 캐시 (공매 fetch_gonmae + 경매 fetch_gyeongmae 공용)

문제:
  기존 load_deals(lawd)는 매 실행마다 구별로 apt/rh/silv × 24개월 = 72콜을 전부 재호출.
  25구면 1,800콜/실행. 과거 달 데이터는 불변인데도 매번 다시 받아 → 일일한도(10,000/일) 소진.
  공매·경매를 각각 돌리면 한도가 2배로 터진다.

해결:
  · 과거 달(이번 달 이전)은 deals_store.json 에 (lawd,ym,kind)별로 영구 저장 → 두 번 다시 안 받음
  · 이번 달만 매 실행 갱신(거래가 계속 추가되므로)
  · 파일 하나를 공매·경매가 공유 → 한 번 받은 달은 둘 다 재사용
  결과: 구당 72콜 → 최대 3콜(이번달 apt/rh/silv). 호출량 1/24.

사용 (양쪽 수집기 공통):
  import deals_cache as DC
  DC.init(DATA_KEY, months=24)
  by_jb, by_nm = DC.load(lawd)          # 기존 load_deals 와 동일 반환형
  names = DC.deal_names(lawd, umd, jibun)
  hist  = DC.deal_history(lawd, umd, jibun, bldg, area)
"""
import os, json, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "deals_store.json")

RT = {"apt": "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
      "rh":  "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
      "silv":"https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade"}

_KEY = ""
_MONTHS = 24
_store = None          # {"lawd|ym|kind": [rec,...]}  과거달 영구본
_mem = {}              # {lawd: (by_jb, by_nm)}  실행중 조립본
_dirty = False

# ── 유틸 ──
def _num(v):
    try: return int(round(float(str(v).replace(",", "").strip())))
    except Exception: return 0
def _fnum(v):
    try: return float(str(v).replace(",", "").strip())
    except Exception: return None
def _g(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""): return str(d[k]).strip()
    return ""
def _xml_items(raw):
    try: root = ET.fromstring(raw)
    except Exception: return []
    return [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
def _http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def _this_ym():
    return time.strftime("%Y%m", time.gmtime(time.time() + 9 * 3600))

def ym_list(n):
    import datetime as dt
    b = dt.date.today().replace(day=1); out = []
    for i in range(n):
        m, y = b.month - i, b.year
        while m <= 0: m += 12; y -= 1
        out.append(f"{y}{m:02d}")
    return out

# ── 초기화 / 저장 ──
def init(data_key, months=24):
    global _KEY, _MONTHS, _store
    _KEY = (data_key or "").strip()
    _MONTHS = months
    if _store is None:
        if os.path.exists(STORE):
            try: _store = json.load(open(STORE, encoding="utf-8"))
            except Exception: _store = {}
        else:
            _store = {}
    return _store

def save():
    global _dirty
    if not _dirty: return
    try:
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_store, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, STORE)
        _dirty = False
    except Exception as e:
        print("[deals_cache] 저장 실패:", e)

# ── 한 (lawd,kind,ym) 청크 수집(원격) ──
def _fetch_chunk(lawd, kind, ym):
    q = urllib.parse.urlencode({"serviceKey": _KEY, "LAWD_CD": lawd, "DEAL_YMD": ym,
                                "numOfRows": 1000, "pageNo": 1}, safe="=")
    try:
        its = _xml_items(_http_get(f"{RT[kind]}?{q}"))
    except Exception:
        return []
    recs = []
    for it in its:
        amt = _num(_g(it, "dealAmount", "거래금액"))
        if not amt: continue
        recs.append({
            "ym": ym, "amt": amt,
            "area": _fnum(_g(it, "excluUseAr", "전용면적")) or "",
            "floor": _g(it, "floor", "층"),
            "name": _g(it, "aptNm", "mhouseNm", "아파트", "연립다세대"),
            "umd": _g(it, "umdNm", "법정동").strip(),
            "jibun": _g(it, "jibun", "지번").strip(),
        })
    return recs

def _chunk(lawd, kind, ym):
    """과거달이면 store에서, 이번달이면 원격. store엔 과거달만 영구 저장."""
    global _dirty
    key = f"{lawd}|{ym}|{kind}"
    cur = _this_ym()
    if ym != cur and isinstance(_store, dict) and key in _store:
        return _store[key]                 # 과거달 캐시 히트
    recs = _fetch_chunk(lawd, kind, ym)
    if ym != cur:                          # 과거달만 영구 저장(이번달은 계속 바뀌니 저장X)
        _store[key] = recs
        _dirty = True
    return recs

# ── 구 단위 로드 (기존 load_deals 대체, 반환형 동일) ──
def load(lawd):
    if lawd in _mem:
        return _mem[lawd]
    by_jb, by_nm = {}, {}
    jobs = [(k, ym) for k in ("apt", "rh", "silv") for ym in ym_list(_MONTHS)]
    # 과거달 store히트는 즉시, 미스+이번달만 원격 → 스레드 소수로 충분
    def _one(j):
        k, ym = j
        return _chunk(lawd, k, ym)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for recs in ex.map(_one, jobs):
            for r in recs:
                if r["umd"] and r["jibun"]:
                    by_jb.setdefault((r["umd"], r["jibun"]), []).append(r)
                if r["name"]:
                    by_nm.setdefault(r["name"].replace(" ", ""), []).append(r)
    _mem[lawd] = (by_jb, by_nm)
    return _mem[lawd]

# ── 조회 헬퍼 (공매 코드와 동일 시그니처) ──
def deal_names(lawd, umd, jibun):
    if not (umd and jibun): return []
    by_jb, _ = load(lawd)
    return list({r["name"] for r in by_jb.get((umd, jibun), []) if r["name"]})

def deal_history(lawd, umd, jibun, bldg, area):
    by_jb, by_nm = load(lawd)
    recs = list(by_jb.get((umd, jibun), []))
    if not recs and bldg:
        key = bldg.replace(" ", "")
        for nm, rs in by_nm.items():
            if len(nm) >= 2 and (nm in key or key in nm):
                recs += rs
    same = [r for r in recs if not (area and r["area"]) or abs(r["area"] - area) <= 3]
    return sorted(same or recs, key=lambda r: r["ym"], reverse=True)[:24]
