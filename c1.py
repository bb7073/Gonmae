import json,os,urllib.parse,urllib.request,concurrent.futures as F
KK=os.environ['KAKAO_REST_KEY']
L=json.load(open('apt_list.json'))
try: G=json.load(open('apt_geo.json'))
except Exception: G={}
def geo(a):
    c=a.get('kaptCode')
    if not c or c in G: return
    p=' '.join(str(a.get(k) or '') for k in ('as1','as2','as3','as4')).strip()
    s=(p+' '+(a.get('kaptName') or '')).strip()
    u='https://dapi.kakao.com/v2/local/search/keyword.json?size=1&query='+urllib.parse.quote(s)
    r=urllib.request.Request(u,headers={'Authorization':'KakaoAK '+KK})
    try:
        d=json.loads(urllib.request.urlopen(r,timeout=8).read().decode())
        v=(d.get('documents') or [None])[0]
        G[c]=[float(v['x']),float(v['y'])] if v else None
    except Exception: G[c]=None
with F.ThreadPoolExecutor(12) as ex: list(ex.map(geo,L))
json.dump(G,open('apt_geo.json','w'),ensure_ascii=False)
print('좌표',sum(1 for v in G.values() if v),'/',len(G))
