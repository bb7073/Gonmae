#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
공매(온비드) 수집 → data.js 생성 + 신규매물 카카오톡 알림 (서버/GitHub Actions용)
"""
import json, os, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

DATA_KEY  = os.environ.get("DATA_KEY", "")
KAKAO_REST= os.environ.get("KAKAO_REST_KEY", "")
KAKAO_REFRESH = os.environ.get("KAKAO_REFRESH_TOKEN", "")

REGION_SD = os.environ.get("REGION_SD", "서울특별시")
REGION_GU = os.environ.get("REGION_GU", "광진구")
MAX_PAGES, ROWS = 8, 100
REALDEAL_MONTHS = 6
PRPT_DIV = "0007,0005,0006,0008"

BASE = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2"
OP_CANDIDATES = ["getRlstCltrList2"]
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
    try: return int(str(v).replace(",","").strip())
    except: return 0

def http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")

def onbid_url(op, page, minimal=False):
    params = {"serviceKey":DATA_KEY,"pageNo":page,"numOfRows":ROWS,"resultType":"json"}
    if not minimal:
        params.update({"prptDivCd":PRPT_DIV,"pvctTrgtYn":"N"})
    params.update({"lctnSdnm":REGION_SD,"lctnSggnm":REGION_GU})
    q = urllib.parse.urlencode(params, safe="=,")
    return f"{BASE}/{op}?{q}"

def json_items(raw, debug_label=""):
    d = json.loads(raw)
    root = d.get("response", d)
    body = root.get("body",{})
    header = root.get("header",{})
    total = body.get("totalCount", "?")
    print(f"    [{debug_label}] resultCode={header.get('resultCode')} resultMsg={header.get('resultMsg')} totalCount={total}")
    it = body.get("items") or {}
    it = it.get("item", []) if isinstance(it, dict) else it
    return it if isinstance(it, list) else ([it] if it else [])

def fetch_list():
    for op in OP_CANDIDATES:
        try:
            raw = http_get(onbid_url(op,1))
            its = json_items(raw, f"{op}/필터있음")
        except Exception as e:
            print(f"  ({op} 필터포함 실패: {e})"); its=[]
        if not its:
            try:
                raw2 = http_get(onbid_url(op,1,minimal=True))
                its = json_items(raw2, f"{op}/필터없음(지역만)")
                if its: print(f"  → 필터 없이는 데이터 있음. prptDivCd/pvctTrgtYn 값이 원인일 가능성 높음")
            except Exception as e:
                print(f"  ({op} 필터없음도 실패: {e})")
        if not its:
            print(f"  응답 원문 앞부분: {raw[:300] if 'raw' in dir() else ''}")
            continue
        print(f"  오퍼레이션 '{op}' 확정 사용")
        out = list(its)
        for pg in range(2, MAX_PAGES+1):
            try: more = json_items(http_get(onbid_url(op,pg)), f"{op}/p{pg}")
            except Exception: break
            if not more: break
            out += more; time.sleep(0.2)
        return out
    return []

def geocode(addr, cache):
    if addr in cache: return cache[addr]
    try:
        docs = json.loads(http_get(
            "https://dapi.kakao.com/v2/local/search/address.json?query="+urllib.parse.quote(addr),
            headers={"Authorization": f"KakaoAK {KAKAO_REST}"}))["documents"]
        c = [float(docs[0]["x"]), float(docs[0]["y"])] if docs else None
    except Exception: c = None
    cache[addr] = c; time.sleep(0.1); return c

def ym_list(n):
    import datetime as dt
    b = dt.date.today().replace(day=1); out=[]
    for i in range(n):
        m,y = b.month-i, b.year
        while m<=0: m+=12; y-=1
        out.append(f"{y}{m:02d}")
    return out
def xml_items(raw): return [ {c.tag:(c.text or "").strip() for c in it} for it in ET.fromstring(raw).findall(".//item") ]
def pickf(d, keys):
    for k in keys:
        if d.get(k) not in (None,""): return d[k]
    return ""
def load_deals(lawd):
    idx={"apt":[],"rh":[],"silv":[]}
    NM={"apt":["aptNm","아파트"],"rh":["mhouseNm","연립다세대"],"silv":["aptNm","단지","아파트"]}
    for kind in idx:
        for ym in ym_list(REALDEAL_MONTHS):
            q=urllib.parse.urlencode({"serviceKey":DATA_KEY,"LAWD_CD":lawd,"DEAL_YMD":ym,"numOfRows":1000,"pageNo":1},safe="=")
            try: its=xml_items(http_get(f"{RT[kind]}?{q}"))
            except Exception: its=[]
            for it in its:
                nm=pickf(it,NM[kind]); ar=pickf(it,["excluUseAr","전용면적"])
                am=pickf(it,["dealAmount","거래금액"]).replace(",","").strip()
                if nm and am: idx[kind].append({"name":nm,"area":ar,"amount":am,"ym":ym})
            time.sleep(0.1)
    return idx
def match(name, area, idx, kind):
    try: a=float(area)
    except: a=None
    tgt=name.replace(" ",""); best=None
    for d in idx.get(kind,[]):
        dn=d["name"].replace(" ","")
        if len(dn)>=2 and dn in tgt:
            if a and d["area"]:
                try:
                    if abs(float(d["area"])-a)>3: continue
                except: pass
            if not best or d["ym"]>best["ym"]: best=d
    return best

RESI = ("아파트","연립","다세대","빌라","단독","다가구")
def build(items):
    gc = json.load(open(fp("geocode_cache.json"),encoding="utf-8")) if os.path.exists(fp("geocode_cache.json")) else {}
    lawd = SEOUL_GU.get(REGION_GU)
    deals = load_deals(lawd) if lawd else {"apt":[],"rh":[],"silv":[]}
    out=[]
    for it in items:
        sd,sgg,emd = it.get("lctnSdnm",""), it.get("lctnSggnm",""), it.get("lctnEmdNm","")
        if REGION_GU not in (sgg or ""): continue
        use = " ".join([it.get("cltrUsgMclsCtgrNm",""), it.get("cltrUsgSclsCtgrNm","")])
        if "오피스텔" in use: continue
        if not any(k in use for k in RESI): continue
        name = it.get("onbidCltrNm","")
        coord = geocode(name, gc) or geocode(f"{sd} {sgg} {emd}", gc)
        if not coord: continue
        bld = it.get("bldSqms","")
        minp = num(it.get("lowstBidPrcIndctCont",""))
        is_apt = "아파트" in use
        pnu = it.get("ltnoPnu",""); gu_lawd = pnu[:5] if len(pnu)>=5 else lawd
        deals2 = deals if gu_lawd==lawd else load_deals(gu_lawd)
        deal = match(name, bld, deals2, "apt" if is_apt else "rh")
        silv = match(name, bld, deals2, "silv") if is_apt else None
        gap  = (num(deal["amount"])*10000 - minp) if (deal and minp) else None
        out.append({"name":name,"addr":f"{sd} {sgg} {emd}".strip(),
            "use":it.get("cltrUsgSclsCtgrNm","") or it.get("cltrUsgMclsCtgrNm",""),
            "isApt":is_apt,"area":bld,"min":minp,"aprs":num(it.get("apslEvlAmt","")),
            "disc":it.get("apslPrcCtrsLowstBidRto",""),"fail":it.get("usbdNft",""),
            "status":it.get("pbctStatNm",""),"id":it.get("cltrMngNo",""),
            "thumb":it.get("thnlImgUrlAdr","").replace("&amp;","&"),
            "deal":num(deal["amount"])*10000 if deal else None,
            "silv":num(silv["amount"])*10000 if silv else None,"gap":gap,
            "naver":NAVER_TMPL.format(q=urllib.parse.quote(name or f"{sgg} {emd}")),
            "lng":coord[0],"lat":coord[1]})
    json.dump(gc, open(fp("geocode_cache.json"),"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    return out

def read_prev():
    try:
        s = open(fp("data.js"),encoding="utf-8").read()
        return json.loads(s[s.index("["):s.rindex("]")+1])
    except Exception: return []

def kakao_token():
    data = urllib.parse.urlencode({"grant_type":"refresh_token","client_id":KAKAO_REST,
        "refresh_token":KAKAO_REFRESH}).encode()
    req = urllib.request.Request("https://kauth.kakao.com/oauth/token", data=data)
    return json.loads(urllib.request.urlopen(req,timeout=10).read())["access_token"]

def kakao_send(text, link):
    if not (KAKAO_REFRESH and KAKAO_REST):
        print("  (카카오 토큰 없음 → 알림 생략)"); return
    try:
        tok = kakao_token()
        tmpl = json.dumps({"object_type":"text","text":text[:900],
            "link":{"web_url":link,"mobile_web_url":link}}, ensure_ascii=False)
        data = urllib.parse.urlencode({"template_object":tmpl}).encode()
        req = urllib.request.Request("https://kapi.kakao.com/v2/api/talk/memo/default/send",
            data=data, headers={"Authorization": f"Bearer {tok}"})
        urllib.request.urlopen(req,timeout=10)
        print("  카카오톡 알림 전송 완료")
    except Exception as e:
        print(f"  (카카오 알림 실패: {e})")

if __name__=="__main__":
    if not DATA_KEY:
        print("ERROR: DATA_KEY 환경변수가 없습니다 (GitHub Secrets 확인)"); sys.exit(1)
    print("수집 시작")
    prev_ids = {x.get("id") for x in read_prev()}
    cur = build(fetch_list())
    open(fp("data.js"),"w",encoding="utf-8").write("window.GONMAE = "+json.dumps(cur,ensure_ascii=False)+";")
    print(f"완료: {len(cur)}건 → data.js")
    new = [x for x in cur if x.get("id") and x["id"] not in prev_ids]
    if prev_ids and new:
        lines = [f"🏠 신규 공매 {len(new)}건 ({REGION_GU})"]
        for x in new[:8]:
            eok = (x["min"]/1e8) if x["min"] else 0
            lines.append(f"· {x['use']} {x['area']}㎡ / 최저 {eok:.1f}억 / {x['addr']}")
        kakao_send("\n".join(lines), "https://bb7073.github.io/Gonmae/")
    else:
        print(f"  신규 {len(new)}건 (알림조건 미해당)")
