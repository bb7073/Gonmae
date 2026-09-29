# -*- coding: utf-8 -*-
"""추천 점수 — 재개발 트랙 / 아파트 트랙 분리"""

def _under(d):
    """저평가율 = (실거래 환산 - 최저가) / 실거래 환산"""
    base = d.get("dealAdj") or d.get("deal")
    low = d.get("low") or 0
    if not base or not low: return None
    return (base - low) / base

def _stage_pt(sub, table):
    for k, v in table:
        if sub and k in sub: return v
    return 0

VILLA_STAGE = [("관리처분", 25), ("사업시행", 25), ("조합설립", 20),
               ("추진위", 15), ("정비구역", 15), ("대상지", 10), ("모아", 10)]
APT_STAGE   = [("사업시행", 20), ("조합설립", 15), ("안전진단", 10),
               ("정비구역", 10), ("추진위", 10)]

def score(d):
    """(점수, 등급, 사유리스트, 트랙) / kill이면 (0,'비추천',..)"""
    if d.get("kill"):
        return 0, "⚠비추천", [b for b in (d.get("badge") or []) if b.startswith("🔴")], "-"
    apt = bool(d.get("isApt"))
    zone = (d.get("zone") or "").strip() or None
    sub = d.get("zoneSub") or ""
    stage = _stage_pt(sub, APT_STAGE if apt else VILLA_STAGE) if zone else 0
    plain = apt and not stage          # 재건축 단계가 없으면 일반 아파트 트랙
    u = _under(d); why = []; s = 0

    # 저평가율
    if u is None:
        why.append("실거래 미확인")
    else:
        if plain:
            cuts = [(.30,60),(.20,45),(.15,32),(.10,18)]
        elif apt:
            cuts = [(.30,45),(.20,35),(.15,25),(.10,15)]
        else:
            cuts = [(.30,40),(.20,30),(.10,20),(.0,10)]
        for th, pt in cuts:
            if u >= th: s += pt; break
        why.append(f"실거래 대비 {u*100:.0f}%")

    # 정비구역
    s += stage
    if stage: why.append(f"{zone} {sub}")
    elif zone: why.append(f"{zone}(단계 미상)")

    # 권리 청결도
    bd = d.get("badge") or []
    if any("포기" in b for b in bd) or any("임차인없음" in b for b in bd):
        s += 25 if plain else 20; why.append("인수권리 없음")
    elif not bd:
        s += 22 if plain else 18; why.append("특기사항 없음")
    elif not any(b.startswith("🔴") for b in bd):
        s += 15 if plain else 12
    else:
        why.append("권리 확인 필요")

    # 면적 / 대지지분
    ar = d.get("area") or 0
    if apt:
        s += 10 if ar >= 59 else 7 if ar >= 40 else 4
    else:
        ls = d.get("landShare") or 0
        s += 10 if ls >= 20 else 7 if ls >= 12 else 3 if ls else 0
        if ls: why.append(f"대지 {ls}㎡")

    # 유찰
    y = d.get("yuchal") or 0
    s += 5 if 1 <= y <= 2 else 2 if y == 0 else 0
    if y: why.append(f"{y}회 유찰")

    if any("조합원지위" in b for b in bd): why.append("⚠지위승계 확인")
    g = "👍추천" if s >= 80 else "✅검토" if s >= 60 else "△보류" if s >= 40 else "⚠비추천"
    return s, g, why, "아파트" if apt else "빌라"
