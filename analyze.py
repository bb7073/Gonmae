# -*- coding: utf-8 -*-
"""권리배지 / 단지명 / 대지지분 분석 — fetch_gyeongmae.py에서 호출"""
import re

SAFE = [
    (r"대항력[은를]?\s*포기", "선순위포기"),
    (r"(주택도시보증공사|한국토지주택공사|서울주택도시공사).{0,80}확약서", "기관포기"),
    (r"대지권등기가?\s*완료", "대지권해소"),
    (r"대지권\s*가격이?\s*포함", "대지권해소"),
    (r"사실상\s*대지권을\s*취득", "대지권해소"),
    (r"임차인\s*없", "임차인없음"),
]
DANGER = [
    (r"유치권", "유치권"),
    (r"토지\s*별도등기\s*있", "별도등기"),
    (r"집합건축물대장이?\s*없|사용승인\s*받지\s*않", "미준공"),
    (r"선순위\s*(가등기|가처분)", "선순위등기"),
    (r"법정지상권", "법정지상권"),
]
WARN = [
    (r"조합원의?\s*지위를?\s*승계|추가부담금|분담금|현금청산", "조합원지위"),
    (r"누수|균열|파손", "하자"),
    (r"재감정|변경에\s*따라", "재감정"),
    (r"맹지|도로에\s*접하지", "맹지"),
]
LEASE = r"임차|전입|확정일자|배당요구|전세권"

def _hit(pats, t):
    return [n for p, n in pats if re.search(p, t)]

def badges(special, jibun_flag=False):
    """(배지리스트, 탈락여부) — 안전 신호를 위험보다 먼저 평가"""
    t = re.sub(r"\s+", " ", special or "")
    safe = set(_hit(SAFE, t)); dang = set(_hit(DANGER, t)); warn = set(_hit(WARN, t))
    # 대지권: 해소 문구가 있으면 위험에서 제외
    if re.search(r"대지권\s*미등기", t) and "대지권해소" not in safe:
        dang.add("대지권미등기")
    # 임차인: 언급은 있는데 포기 문구가 없으면 인수 위험
    if re.search(LEASE, t) and not (safe & {"선순위포기", "기관포기", "임차인없음"}):
        dang.add("임차인확인")
    out, kill = [], False
    for n in sorted(dang):
        out.append("🔴" + n)
        if n in ("유치권", "대지권미등기", "미준공", "선순위등기", "법정지상권"): kill = True
    if jibun_flag: out.append("🔴지분매각"); kill = True
    for n in sorted(safe): out.append("🟢" + n)
    for n in sorted(warn): out.append("⚠" + n)
    if not out and len(t) > 100: out.append("🟡확인요망")
    return out, kill

def base_right(dm):
    """말소기준권리 — 토지/건물 중 이른 날짜"""
    s = (dm.get("dspslGdsDxdyInfo") or {}).get("tprtyRnkHypthcStngDts") or ""
    ds = re.findall(r"(\d{4})[.\-\s]+(\d{1,2})[.\-\s]+(\d{1,2})", s)
    if not ds: return None
    return min("%s-%02d-%02d" % (y, int(m), int(d)) for y, m, d in ds)

def _flat(v):
    """[[{..},{..}]] 같은 중첩 리스트를 dict 단위로 펼친다"""
    out=[]; stack=[v]
    while stack:
        x=stack.pop()
        if isinstance(x,list): stack.extend(x)
        elif isinstance(x,dict): out.append(x)
    return out

def land_share(dm):
    """대지지분 ㎡ — 여러 필지면 합산"""
    tot=0.0
    for L in _flat(dm.get("rgltLandLstAll")):
        try:
            ar=float(re.sub(r"[^\d.]","",L.get("landArDts") or ""))
            dn=float(L.get("rgltRateDnmnVal") or 0)
            nm=float(L.get("rgltRateNmrtVal") or 0)
            if ar and dn: tot+=ar*nm/dn
        except Exception: pass
    return round(tot,2) if tot else None

def apt_from_aee(dm):
    """감정요항 위치항목의 따옴표 안 단지명"""
    SUF = ("아파트", "단지", "빌라", "맨션", "타운", "캐슬", "자이", "푸르지오",
           "힐스테이트", "e편한세상", "래미안", "빌", "하우스", "팰리스")
    for a in _flat(dm.get("aeeWevlMnpntLst")):
        c = a.get("aeeWevlMnpntCtt") or ""
        for q in re.findall(r"[\"'\u201c\u2018]([^\"'\u201d\u2019]{2,25})[\"'\u201d\u2019]", c):
            q = q.strip()
            if q.endswith(SUF): return q
    return None

def is_apt(dm):
    for b in _flat(dm.get("bldSdtrDtlLstAll")):
        if "아파트" in (b.get("bldSdtrDtlDts") or ""):
            return True
    return False
