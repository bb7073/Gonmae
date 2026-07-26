# -*- coding: utf-8 -*-
"""
서울시 의제처리구역 SHP(UPIS_C_UQ181) -> 정비구역 GeoJSON 변환
- 좌표계: EPSG:5174 (Bessel 중부원점) -> EPSG:4326 (WGS84)
- 인코딩: dbf는 cp949 (데이터셋 설명의 UTF-8 표기는 틀림)
- 관심 유형만 추출 + 폴리곤 단순화 + 좌표 6자리 반올림
"""
import json, shapefile, collections
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform

SRC = "shp#Ud30c#Uc77c/UPIS_C_UQ181"
OUT = "jeongbi.geojson"

# ATRB_SE(최종코드) -> (카테고리, 세부명)
CODE = {
    # === 정비구역 (도시 및 주거환경정비법) ===
    "UQ1211": ("정비", "주거환경개선사업"),
    "UQ1212": ("정비", "주거환경관리사업"),
    "UQ1221": ("정비", "주택정비형 재개발"),
    "UQ1222": ("정비", "도시정비형 재개발"),
    "UQ1231": ("정비", "주택정비형 재개발지구"),
    "UQ1232": ("정비", "도시정비형 재개발지구"),
    "UQ1240": ("정비", "재건축"),
    "UQ1206": ("정비", "주택재건축"),
    "UQ1250": ("정비", "결합정비구역"),
    "UQ1290": ("정비", "정비구역"),
    # === 소규모주택정비 (빈집 및 소규모주택 정비에 관한 특례법) ===
    "UQ1811": ("소규모", "자율주택정비"),
    "UQ1812": ("소규모", "가로주택정비"),
    "UQ1813": ("소규모", "소규모재건축"),
    "UQ1814": ("소규모", "소규모재개발"),
    "UQ1260": ("소규모", "자율주택정비"),
    "UQ1270": ("소규모", "가로주택정비"),
    "UQ1280": ("소규모", "소규모재건축"),
    # === 재정비촉진지구 (뉴타운) ===
    "UQ5100": ("촉진", "재정비촉진지구"),
    "UQ5110": ("촉진", "주거지형 촉진지구"),
    "UQ5120": ("촉진", "중심지형 촉진지구"),
    "UQ5130": ("촉진", "고밀복합형 촉진지구"),
    "UQ5140": ("촉진", "존치정비구역"),
    "UQ5150": ("촉진", "존치관리구역"),
    # === 기타 개발사업 ===
    "UQ1100": ("기타", "도시개발구역"),
    "UQ6300": ("기타", "공공지원민간임대 촉진지구"),
    "UQ5500": ("기타", "공공주택지구"),
    "UQ5400": ("기타", "국민임대주택"),
    "UQ6500": ("기타", "택지개발지구"),
    "UQ1700": ("기타", "아파트지구개발사업"),
    "UQ9100": ("기타", "주택건설사업"),
}
# 제외: UQ1900(토지구획정리·과거사업), UQ5600/5700(일단의 조성사업·과거),
#       UQ6400(시장정비), UQ5300, UQ5900, UQ2999, UQA330

SIGUNGU = {  # SIGNGU_SE -> 자치구
    "11000": "서울시", "11110": "종로구", "11140": "중구", "11170": "용산구",
    "11200": "성동구", "11215": "광진구", "11230": "동대문구", "11260": "중랑구",
    "11290": "성북구", "11305": "강북구", "11320": "도봉구", "11350": "노원구",
    "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구",
    "11590": "동작구", "11620": "관악구", "11650": "서초구", "11680": "강남구",
    "11710": "송파구", "11740": "강동구",
}

tr = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
sf = shapefile.Reader(SRC, encoding="cp949")

feats, skipped = [], collections.Counter()
for sr in sf.iterShapeRecords():
    r = sr.record
    code = (r["ATRB_SE"] or r["MLSFC_CL"] or r["LCLAS_CL"] or "").strip()
    if code not in CODE:
        skipped[code] += 1
        continue
    cat, sub = CODE[code]

    try:
        g = shape(sr.shape.__geo_interface__)
        if not g.is_valid:
            g = g.buffer(0)
        g = shp_transform(lambda x, y, z=None: tr.transform(x, y), g)
        g = g.simplify(0.000018, preserve_topology=True)   # 약 2m
        if g.is_empty:
            continue
    except Exception as e:
        skipped["ERR:" + str(e)[:30]] += 1
        continue

    gj = mapping(g)

    def rnd(o):
        if isinstance(o, (list, tuple)):
            if len(o) == 2 and isinstance(o[0], float):
                return [round(o[0], 6), round(o[1], 6)]
            return [rnd(i) for i in o]
        return o
    gj["coordinates"] = rnd(gj["coordinates"])

    feats.append({
        "type": "Feature",
        "geometry": gj,
        "properties": {
            "nm": (r["DGM_NM"] or "").strip().replace("\u3000", " "),
            "cat": cat,
            "sub": sub,
            "gu": SIGUNGU.get(r["SIGNGU_SE"], ""),
            "ar": round(float(r["DGM_AR"] or 0)),
        },
    })

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)

print("추출:", len(feats), "/ 원본 3209")
print("\n=== 카테고리별 ===")
for k, v in collections.Counter(f["properties"]["cat"] for f in feats).most_common():
    print(f"  {v:5d}  {k}")
print("\n=== 제외된 코드 ===")
for k, v in skipped.most_common(10):
    print(f"  {v:5d}  {k}")
import os
print("\n파일크기: %.2f MB" % (os.path.getsize(OUT) / 1024 / 1024))
