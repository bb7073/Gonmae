import json,os,urllib.parse,urllib.request,collections,concurrent.futures as F
KK=os.environ['KAKAO_REST_KEY']
L=json.load(open('apt_list.json')); G=json.load(open('apt_geo.json'))
E=collections.Counter()
need=[a for a in L if not G.get(a.get('kaptCode'))]
def q(a,m):
    p=' '.join(str(a.get(k) or '') for k in ('as1','as2','as3')).strip()
    n=a.get('kaptName') or ''
    return (p+' '+n) if m==0 else n
def geo(a):
    c=a['kaptCode']
    for m in (0,1):
        u='https://dapi.kakao.com/v2/local/search/keyword.json?size=1&query='+urllib.parse.quote(q(a,m))
        r=urllib.request.Request(u,headers={'Authorization':'KakaoAK '+KK})
        try:
            d=json.loads(urllib.request.urlopen(r,timeout=10).read().decode())
            v=(d.get('documents') or [None])[0]
            if v: G[c]=[float(v['x']),float(v['y'])]; E['ok']+=1; return
            E['empty%d'%m]+=1
        except Exception as ex: E[type(ex).__name__]+=1
    G[c]=None
with F.ThreadPoolExecutor(4) as ex: list(ex.map(geo,need))
json.dump(G,open('apt_geo.json','w'),ensure_ascii=False)
print('재시도',len(need),dict(E))
print('좌표총',sum(1 for v in G.values() if v),'/',len(G))
