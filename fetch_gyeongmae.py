# -*- coding: utf-8 -*-
"""
fetch_gyeongmae.py  v2
법원경매정보(courtauction.go.kr) 수집기 — 공매(fetch_gonmae) 자매편.

파이프라인:
  5개 법원 반복 → 목록 페이징(searchControllerMain.on)
    → 주거용(아파트/다세대/다가구/연립)만, 오피스텔·토지·상가 제외
    → 물건별 상세(selectAuctnCsSrchRslt.on)로 기일 사다리·유찰이력·특별매각조건
    → 카카오 지오코딩(공매앱과 동일 캐시 geocode_cache.json 공유)
    → data_gyeongmae.js  (각 물건 src:'경매')

필요 시크릿(공매앱과 동일):  KAKAO_REST_KEY, DATA_KEY(국토부, 실거래 확장용)

실행:
  python fetch_gyeongmae.py            # 전체 수집
  python fetch_gyeongmae.py --court B000210 --pages 1   # 빠른 테스트
"""
import sys, os, re, json, time, argparse, datetime, threading, base64, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import requests

try:
    import deals_cache as DC
except Exception:
    DC = None   # 단독 테스트 시 실거래 없이도 동작

# 서울 25개구 법정동 앞5자리(LAWD_CD) — 실거래 조회용
SEOUL_GU = {"종로구":"11110","중구":"11140","용산구":"11170","성동구":"11200","광진구":"11215",
"동대문구":"11230","중랑구":"11260","성북구":"11290","강북구":"11305","도봉구":"11320",
"노원구":"11350","은평구":"11380","서대문구":"11410","마포구":"11440","양천구":"11470",
"강서구":"11500","구로구":"11530","금천구":"11545","영등포구":"11560","동작구":"11590",
"관악구":"11620","서초구":"11650","강남구":"11680","송파구":"11710","강동구":"11740"}

BASE = "https://www.courtauction.go.kr"
LIST_URL = BASE + "/pgj/pgjsearch/searchControllerMain.on"
DTL_URL  = BASE + "/pgj/pgj15B/selectAuctnCsSrchRslt.on"
IDX_URL  = BASE + "/pgj/index.on"

KAKAO_KEY = os.environ.get("KAKAO_REST_KEY", "").strip()
DATA_KEY  = os.environ.get("DATA_KEY", "").strip()
if DATA_KEY:
    DC.init(DATA_KEY, months=24)

COURTS = {
    "B000210": "서울중앙지방법원",
    "B000211": "서울동부지방법원",
    "B000215": "서울서부지방법원",
    "B000212": "서울남부지방법원",
    "B000213": "서울북부지방법원",
}

APT_USG   = {"아파트"}
VILLA_USG = {"다세대", "다가구주택", "연립", "연립주택", "단독주택", "다가구"}
def kind_of(usg):
    if usg in APT_USG:   return "아파트"
    if usg in VILLA_USG: return "빌라"
    return None

PAGE_SIZE = 40
SLEEP = 0.6
DTL_WORKERS = 4
GEO_CACHE = "geocode_cache.json"

def new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
        "Accept": "application/json",
        "Accept-Language": "ko,en;q=0.9",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": BASE,
        "Referer": BASE + "/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml",
    })
    try:
        s.get(IDX_URL, timeout=20)
    except Exception as e:
        print("[경고] 부트스트랩 실패:", e)
    return s

def today_ymd():
    return datetime.datetime.now().strftime("%Y%m%d")
def plus_days(n):
    return (datetime.datetime.now() + datetime.timedelta(days=n)).strftime("%Y%m%d")

def _srch_info(court):
    return {
        "rletDspslSpcCondCd": "", "bidDvsCd": "000331",
        "mvprpRletDvsCd": "00031R", "cortAuctnSrchCondCd": "0004601",
        "rprsAdongSdCd": "", "rprsAdongSggCd": "", "rprsAdongEmdCd": "",
        "rdnmSdCd": "", "rdnmSggCd": "", "rdnmNo": "",
        "mvprpDspslPlcAdongSdCd": "", "mvprpDspslPlcAdongSggCd": "",
        "mvprpDspslPlcAdongEmdCd": "", "rdDspslPlcAdongSdCd": "",
        "rdDspslPlcAdongSggCd": "", "rdDspslPlcAdongEmdCd": "",
        "cortOfcCd": court, "jdbnCd": "", "execrOfcDvsCd": "",
        "lclDspslGdsLstUsgCd": "", "mclDspslGdsLstUsgCd": "",
        "sclDspslGdsLstUsgCd": "", "cortAuctnMbrsId": "",
        "aeeEvlAmtMin": "", "aeeEvlAmtMax": "",
        "lwsDspslPrcRateMin": "", "lwsDspslPrcRateMax": "",
        "flbdNcntMin": "", "flbdNcntMax": "",
        "objctArDtsMin": "", "objctArDtsMax": "",
        "mvprpArtclKndCd": "", "mvprpArtclNm": "",
        "mvprpAtchmPlcTypCd": "", "notifyLoc": "off", "lafjOrderBy": "",
        "pgmId": "PGJ151F01", "csNo": "", "cortStDvs": "1", "statNum": 1,
        "bidBgngYmd": today_ymd(), "bidEndYmd": plus_days(90),
        "dspslDxdyYmd": "", "fstDspslHm": "", "scndDspslHm": "",
        "thrdDspslHm": "", "fothDspslHm": "", "dspslPlcNm": "",
        "lwsDspslPrcMin": "", "lwsDspslPrcMax": "",
        "grbxTypCd": "", "gdsVendNm": "", "fuelKndCd": "",
        "carMdyrMax": "", "carMdyrMin": "", "carMdlNm": "", "sideDvsCd": "",
    }

def list_body(court, page):
    return {
        "dma_pageInfo": {"pageNo": page, "pageSize": PAGE_SIZE, "bfPageNo": "",
                         "startRowNo": "", "totalCnt": "", "totalYn": "Y",
                         "groupTotalCount": ""},
        "dma_srchGdsDtlSrchInfo": _srch_info(court),
    }

def fetch_list(s, court, page):
    h = {"submissionid": "mf_wfm_mainFrame_sbm_selectGdsDtlSrch"}
    r = s.post(LIST_URL, headers=h,
               data=json.dumps(list_body(court, page), ensure_ascii=False).encode("utf-8"),
               timeout=30)
    r.raise_for_status()
    data = r.json().get("data", {})
    rows = data.get("dlt_srchResult", []) or []
    total = int(data.get("dma_pageInfo", {}).get("totalCnt", 0) or 0)
    return rows, total

def dtl_body(court, sa_no, gds_seq):
    return {"dma_srchGdsDtlSrch": {
        "csNo": sa_no, "cortOfcCd": court, "dspslGdsSeq": str(gds_seq),
        "pgmId": "PGJ151F01", "srchInfo": _srch_info(court),
        "srchRowIndex": 1000, "menuNm": ""}}

def fetch_detail(s, court, sa_no, gds_seq):
    h = {"SC-Pgmid": "PGJ15BM01", "SC-Userid": "NONUSER"}
    r = s.post(DTL_URL, headers=h,
               data=json.dumps(dtl_body(court, sa_no, gds_seq), ensure_ascii=False).encode("utf-8"),
               timeout=30)
    r.raise_for_status()
    return r.json().get("data", {}).get("dma_result", {}) or {}

RSLT = {"001": "변경", "002": "유찰", "003": "매각", "010": "기타"}
def parse_ladder(dma_result):
    lst = dma_result.get("gdsDspslDxdyLst", []) or []
    ladder, sold_amt = [], 0
    for x in lst:
        if x.get("auctnDxdyKndCd") != "01":
            continue
        rc = x.get("auctnDxdyRsltCd")
        row = {"ymd": x.get("dxdyYmd"), "low": x.get("tsLwsDspslPrc") or 0,
               "rslt": RSLT.get(rc, rc or ""), "amt": x.get("dspslAmt") or 0}
        ladder.append(row)
        if rc == "003" and row["amt"]:
            sold_amt = row["amt"]
    info = dma_result.get("dspslGdsDxdyInfo", {}) or {}
    special = ((info.get("gdsSpcfcRmk") or "") + " " + (info.get("dspslGdsRmk") or "")).strip()
    return ladder, sold_amt, special

_geo_lock = threading.Lock()
def load_geo():
    if os.path.exists(GEO_CACHE):
        try: return json.load(open(GEO_CACHE, encoding="utf-8"))
        except Exception: return {}
    return {}
GEO = load_geo()

def geocode(addr):
    if not addr: return None
    with _geo_lock:
        if addr in GEO: return GEO[addr]
    if not KAKAO_KEY:
        return None
    try:
        r = requests.get("https://dapi.kakao.com/v2/local/search/address.json",
                         headers={"Authorization": "KakaoAK " + KAKAO_KEY},
                         params={"query": addr}, timeout=10)
        docs = r.json().get("documents", [])
        out = None
        if docs:
            d = docs[0]
            out = {"lat": float(d["y"]), "lng": float(d["x"]),
                   "bcode": (d.get("address") or {}).get("b_code", "")}
        with _geo_lock:
            GEO[addr] = out
        return out
    except Exception as e:
        print("[지오코딩 예외]", addr[:30], e)
    return None

def save_geo():
    try:
        with open(GEO_CACHE, "w", encoding="utf-8") as f:
            json.dump(GEO, f, ensure_ascii=False)
    except Exception as e:
        print("[지오코딩 캐시 저장 실패]", e)

def build_addr(r):
    parts = [r.get("hjguSido",""), r.get("hjguSigu",""), r.get("hjguDong","")]
    lot = r.get("daepyoLotno","")
    base = " ".join(p for p in parts if p).strip()
    if lot: base = (base + " " + lot).strip()
    road = " ".join(p for p in [r.get("rd1Nm",""), r.get("rd2Nm",""),
                                r.get("rdNm",""), r.get("buldNo","")] if p).strip()
    return base, road

def is_jibun_sale(r, special):
    bigo = (r.get("mulBigo") or "")
    mj   = (r.get("maejibun") or "")
    return ("지분" in bigo) or ("지분" in mj) or ("지분" in (special or ""))

def parse_share_ratio(r, special):
    """지분매각 물건의 지분율(0~1) 추출. 예: '1345.8분의 281.23' → 0.209, '1/2' → 0.5.
       못 찾으면 None(=전체로 간주)."""
    txt = " ".join([r.get("maejibun") or "", r.get("mulBigo") or "", special or ""])
    # 'A분의 B'
    m = re.search(r"([\d,\.]+)\s*분의\s*([\d,\.]+)", txt)
    if m:
        try:
            den = float(m.group(1).replace(",", "")); numr = float(m.group(2).replace(",", ""))
            if den > 0: return round(numr / den, 4)
        except Exception: pass
    # 'B/A'
    m = re.search(r"(\d+)\s*/\s*(\d+)", txt)
    if m:
        try:
            numr = float(m.group(1)); den = float(m.group(2))
            if den > 0 and numr < den: return round(numr / den, 4)
        except Exception: pass
    return None

# 사진 추출: 법원 상세 응답에 base64로 박혀오는 이미지를 jpg로 저장
PHOTO_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
MAX_PHOTOS = 1
MIN_IMG_KB = 8
JPG_MAGIC  = bytes.fromhex("ffd8")
PNG_MAGIC  = bytes.fromhex("89504e470d0a1a0a")
_B64_RE    = re.compile("^[A-Za-z0-9+/]{500,}={0,2}$")

def _walk_strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from _walk_strings(v)
    elif isinstance(o, list):
        for v in o: yield from _walk_strings(v)
    elif isinstance(o, str):
        yield o

def extract_photos(detail, key):
    if not detail: return []
    key = re.sub("[^0-9A-Za-z가-힣_-]", "_", str(key or "x"))[:40]
    try:
        exist = sorted(fn for fn in os.listdir(PHOTO_DIR) if fn.startswith(key + "_"))
    except FileNotFoundError:
        exist = []
    if exist:
        return ["photos/" + fn for fn in exist[:MAX_PHOTOS]]
    saved, seen = [], set()
    for raw_s in _walk_strings(detail):
        t = raw_s.strip()
        if t.startswith("data:image"): t = t.split(",", 1)[-1]
        t = "".join(t.split())
        if len(t) < 500 or not _B64_RE.match(t): continue
        try: blob = base64.b64decode(t + "=" * (-len(t) % 4))
        except Exception: continue
        if   blob[:2] == JPG_MAGIC: ext = ".jpg"
        elif blob[:8] == PNG_MAGIC: ext = ".png"
        else: continue
        if len(blob) < MIN_IMG_KB * 1024: continue
        h = hashlib.md5(blob).hexdigest()[:8]
        if h in seen: continue
        seen.add(h)
        os.makedirs(PHOTO_DIR, exist_ok=True)
        fn = key + "_" + str(len(saved) + 1) + ext
        try:
            with open(os.path.join(PHOTO_DIR, fn), "wb") as fp: fp.write(blob)
        except Exception as e:
            print("  [사진저장 실패]", fn, e); continue
        saved.append("photos/" + fn)
        if len(saved) >= MAX_PHOTOS: break
    return saved


def process_one(s, r):
    kind = kind_of(r.get("dspslUsgNm",""))
    if not kind:
        return None
    court = r.get("boCd")
    sa_no = r.get("saNo")
    gds_seq = r.get("mokmulSer") or r.get("maemulSer") or "1"

    ladder, sold_amt, special = [], 0, ""
    photos = []
    try:
        dm = fetch_detail(s, court, sa_no, gds_seq)
        ladder, sold_amt, special = parse_ladder(dm)
        photos = extract_photos(dm, r.get("srnSaNo") or str(sa_no) + "_" + str(gds_seq))
    except Exception as e:
        print(f"[상세 실패] {r.get('srnSaNo')} {e}")
    time.sleep(SLEEP)

    addr, road = build_addr(r)
    geo = geocode(addr) or (geocode(road) if road else None)

    gaman = int(r.get("gamevalAmt") or 0)
    lowp  = int(r.get("minmaePrice") or 0)
    maeamt = int(r.get("maeAmt") or 0) or sold_amt
    yuchal = int(r.get("yuchalCnt") or 0)
    lowrate = round(lowp / gaman * 100) if gaman else None

    area = None
    m = re.search(r"([\d.]+)\s*㎡", r.get("pjbBuldList") or "")
    if m:
        try: area = float(m.group(1))
        except Exception: area = None

    # ── 실거래 매칭 (공유 캐시) ──
    jibun_flag = is_jibun_sale(r, special)
    deal = deal_adj = deal_avg = gap = None
    hist = []
    apt_nm = ""
    gu   = (r.get("hjguSigu") or "").strip()
    umd  = (r.get("hjguDong") or "").strip()
    jibun = (r.get("daepyoLotno") or "").strip()
    bldg = (r.get("buldNm") or r.get("buldList") or "").strip()
    lawd = SEOUL_GU.get(gu)
    if DC and lawd and umd:
        try:
            h = DC.deal_history(lawd, umd, jibun, bldg, area)
            hist = [{"ym": x["ym"], "amt": x["amt"] * 10000,
                     "area": x["area"], "fl": x["floor"]} for x in h]
            for x in h:
                nm = (x.get("name") or x.get("aptNm") or "").strip()
                if nm:
                    apt_nm = nm; break
            if h:
                deal = h[0]["amt"] * 10000                      # 최근 실거래(전체 1채)
                deal_avg = int(sum(x["amt"] for x in h) / len(h) * 10000)
                # 지분매각이면 실거래를 지분율만큼 환산해야 최저가와 비교 성립
                share_ratio = parse_share_ratio(r, special)
                deal_adj = int(deal * share_ratio) if (deal and share_ratio) else deal
                gap = (deal_adj - lowp) if (deal_adj and lowp) else None
        except Exception as e:
            print(f"[실거래 실패] {r.get('srnSaNo')} {e}")

    return {
        "src": "경매",
        "court": COURTS.get(court, court),
        "caseNo": r.get("srnSaNo"),
        "saNo": sa_no, "gdsSeq": gds_seq, "boCd": court,
        "kind": kind, "usg": r.get("dspslUsgNm",""),
        "name": ((apt_nm + " " + (r.get("buldList") or r.get("printSt") or "")).strip() if apt_nm else (r.get("buldList") or r.get("printSt") or "").strip()),
        "addr": addr, "road": road,
        "gyae": r.get("jpDeptNm",""),
        "lat": geo["lat"] if geo else None,
        "lng": geo["lng"] if geo else None,
        "bcode": geo["bcode"] if geo else "",
        "gaman": gaman, "low": lowp, "lowRate": lowrate,
        "maeAmt": maeamt, "yuchal": yuchal,
        "saleDate": r.get("maeGiil",""),
        "decideDate": r.get("maegyuljGiil",""),
        "area": area,
        "jibun": jibun_flag,
        "bigo": (r.get("mulBigo") or "").strip(),
        "special": special[:200],
        "ladder": ladder,
        "inq": int(r.get("inqCnt") or 0),
        "deal": deal,            # 최근 실거래(전체 1채)
        "dealAdj": deal_adj,     # 지분 환산 실거래
        "dealAvg": deal_avg,
        "gap": gap,              # 실거래(환산) - 최저가
        "hist": hist,
        "photo": photos[0] if photos else None,
        "photos": photos,
    }

def crawl():
    s = new_session()
    picked, seen = [], set()
    max_pages = crawl.max_pages
    for court, cname in COURTS.items():
        print(f"\n===== {cname} ({court}) =====")
        s = new_session()
        try:
            rows, total = fetch_list(s, court, 1)
        except Exception as e:
            print(f"  목록 실패 {e}"); continue
        pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1
        if max_pages: pages = min(pages, max_pages)
        print(f"  총 {total}건 / 조회 {pages}p")
        allrows = list(rows)
        for p in range(2, pages + 1):
            time.sleep(SLEEP)
            try:
                more, _ = fetch_list(s, court, p)
                allrows += more
                print(f"  p{p} +{len(more)} (누적 {len(allrows)})")
            except Exception as e:
                print(f"  p{p} 실패 {e}")
        cand = []
        for r in allrows:
            if kind_of(r.get("dspslUsgNm","")) is None:
                continue
            key = r.get("docid") or (r.get("saNo"), r.get("mokmulSer"))
            if key in seen: continue
            seen.add(key); cand.append(r)
        print(f"  주거용 {len(cand)}건 상세 조회…")
        with ThreadPoolExecutor(max_workers=DTL_WORKERS) as ex:
            futs = [ex.submit(process_one, s, r) for r in cand]
            for f in as_completed(futs):
                try:
                    o = f.result()
                    if o: picked.append(o)
                except Exception as e:
                    import traceback; print("  [처리 예외]", e); traceback.print_exc()
    save_geo()
    return picked
crawl.max_pages = None

def write_js(items):
    items.sort(key=lambda x: (x["saleDate"] or "99999999"))
    payload = {"updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
               "count": len(items), "items": items}
    with open("data_gyeongmae.js", "w", encoding="utf-8") as f:
        f.write("window.GYEONGMAE = ")
        json.dump(payload, f, ensure_ascii=False)
        f.write(";")
    print(f"\n✔ data_gyeongmae.js 저장: {len(items)}건 "
          f"(아파트 {sum(i['kind']=='아파트' for i in items)} / "
          f"빌라 {sum(i['kind']=='빌라' for i in items)} / "
          f"지분 {sum(i['jibun'] for i in items)} / "
          f"좌표없음 {sum(i['lat'] is None for i in items)})")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--court", help="특정 법원코드만")
    ap.add_argument("--pages", type=int, help="법원당 최대 페이지(테스트용)")
    a = ap.parse_args()
    if a.court:
        COURTS = {a.court: COURTS.get(a.court, a.court)}
    if a.pages:
        crawl.max_pages = a.pages
    t0 = time.time()
    items = crawl()
    write_js(items)
    print(f"소요 {time.time()-t0:.0f}s")
