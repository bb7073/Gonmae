import json,re,os,urllib.parse,urllib.request
from concurrent.futures import ThreadPoolExecutor as T
K=os.environ['KAKAO_REST_KEY']
L=json.load(open('apt_list.json'));G=json.load(open('apt_geo.json'))
S=next(v for v in G.values() if v);print('형식샘플',S)
def pack(x,y):
 if isinstance(S,dict):return {k:(x if ('x' in k or 'ln' in k) else y) for k in S}
 return [x,y] if abs(S[0])>100 else [y,x]
def q(s):
 u='https://dapi.kakao.com/v2/local/search/keyword.json?size=1&query='+urllib.parse.quote(s)
 r=urllib.request.Request(u,headers={'Authorization':'KakaoAK '+K})
 d=json.loads(urllib.request.urlopen(r,timeout=10).read().decode()).get('documents',[])
 return pack(float(d[0]['x']),float(d[0]['y'])) if d else None
def go(a):
 c=a['kaptCode']
 nm=re.sub(r'\((분양|임대)\)|임대$','',a.get('kaptName') or '').strip()
 ad=' '.join(x for x in [a.get('as1'),a.get('as2'),a.get('as3')] if x)
 for s in [ad+' '+nm,nm+'아파트',ad+' '+nm+'아파트']:
  try:v=q(s)
  except Exception:v=None
  if v:return c,v
 return c,None
m=[a for a in L if not G.get(a['kaptCode'])];print('미확보',len(m))
ok=0
with T(4) as ex:
 for c,v in ex.map(go,m):
  if v:G[c]=v;ok+=1
json.dump(G,open('apt_geo.json','w'))
print('신규',ok,'총',sum(1 for v in G.values() if v))
print('신당삼성분양',G.get('A10045403'),'임대',G.get('A10045401'))
