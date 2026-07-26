# -*- coding: utf-8 -*-
"""
정비구역 판정 모듈 (외부 라이브러리 불필요 — 표준 라이브러리만 사용)

사용법:
    from zone_tag import ZoneIndex
    ZI = ZoneIndex()                      # jeongbi.geojson 자동 로드
    z = ZI.find(lat, lng)                 # -> {"nm":..,"cat":..,"sub":..} 또는 None

데이터: jeongbi.geojson (서울시 의제처리구역 SHP를 WGS84 GeoJSON으로 변환한 것)
"""
import json, os, math

HERE = os.path.dirname(os.path.abspath(__file__))
GEOJSON = os.path.join(HERE, "jeongbi.geojson")

# 카테고리 우선순위 — 한 지점이 여러 구역에 겹칠 때 더 중요한 쪽을 채택
PRIORITY = {"정비": 0, "소규모": 1, "촉진": 2, "기타": 3}


def _rings(geom):
    """Polygon / MultiPolygon -> [(외곽링, [내부링...]), ...]"""
    t = geom["type"]
    if t == "Polygon":
        polys = [geom["coordinates"]]
    elif t == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return []
    out = []
    for p in polys:
        if p:
            out.append((p[0], p[1:]))
    return out


def _pip(x, y, ring):
    """Ray casting: 점(x,y)이 ring 안에 있는가"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


class ZoneIndex:
    def __init__(self, path=GEOJSON):
        self.items = []          # (minx, miny, maxx, maxy, rings, props)
        self.ok = False
        if not os.path.exists(path):
            print("[zone] jeongbi.geojson 없음 — 구역 태그 생략:", path)
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            for outer, holes in _rings(feat.get("geometry") or {}):
                xs = [c[0] for c in outer]
                ys = [c[1] for c in outer]
                self.items.append((min(xs), min(ys), max(xs), max(ys),
                                   (outer, holes), props))
        self.ok = True
        print("[zone] 정비구역 %d개 로드" % len(self.items))

    def find(self, lat, lng):
        """좌표가 속한 구역 반환. 없으면 None"""
        if not self.ok or lat is None or lng is None:
            return None
        try:
            x, y = float(lng), float(lat)
        except (TypeError, ValueError):
            return None
        if not (126.5 < x < 127.5 and 37.2 < y < 37.9):
            return None

        best = None
        for minx, miny, maxx, maxy, (outer, holes), props in self.items:
            if x < minx or x > maxx or y < miny or y > maxy:
                continue                       # bbox 프리필터 (대부분 여기서 탈락)
            if not _pip(x, y, outer):
                continue
            if any(_pip(x, y, h) for h in holes):
                continue                       # 구멍(도넛) 안이면 제외
            rank = PRIORITY.get(props.get("cat"), 9)
            if best is None or rank < best[0]:
                best = (rank, props)
        return best[1] if best else None


if __name__ == "__main__":
    import time
    ZI = ZoneIndex()
    tests = [
        ("한남동", 37.5340, 127.0000),
        ("성수동", 37.5373, 127.0524),
        ("노량진", 37.5101, 126.9414),
        ("강남역", 37.4979, 127.0276),
    ]
    t0 = time.time()
    for nm, la, ln in tests:
        print(nm, "->", ZI.find(la, ln))
    print("4건 %.3fs" % (time.time() - t0))
