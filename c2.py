import io,json,os,urllib.parse,urllib.request,concurrent.futures as F
K=os.environ['DATA_KEY']
G=json.load(open('apt_geo.json'))
t=io.open('jeongbi_map.js',encoding='utf-8').read()
Z=json.loads(t[t.index('=')+1:].strip().rstrip(';'))
def rg(g,o):
    if not isinstance(g,list) or not g: return
    if isinstance(g[0],(int,float)): return
    if isinstance(g[0][0],(int,float)): o.append(g); return
    for x in g: rg(x,o)
for z in Z:
    o=[]; rg(z['g'],o); z['_r']=o
    xs=[p[0] for r in z['_r'] for p in r]; ys=[p[1] for r in z['_r'] for p in r]
    z['_b']=(min(xs),min(ys),max(xs),max(ys)) if xs else None
def inp(x,y,r):
    c=False; j=len(r)-1
    for i in range(len(r)):
        a,b=r[i]; d,e=r[j]
        if (b>y)!=(e>y) and x<(d-a)*(y-b)/(e-b)+a: c=not c
        j=i
    return c
hit={}
for c,p in G.items():
    if not p: continue
    x,y=p
    for z in Z:
        b=z['_b']
        if not b or x<b[0] or x>b[2] or y<b[1] or y>b[3]: continue
        if any(inp(x,y,r) for r in z['_r']): hit.setdefault(c,[]).append(z)
print('구역내 단지',len(hit),flush=True)
try: B=json.load(open('apt_basis.json'))
except Exception: B={}
def bas(c):
    u='https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusBassInfoV4?'+urllib.parse.urlencode({'serviceKey':K,'kaptCode':c,'_type':'json'},safe='=')
    try:
        it=json.loads(urllib.request.urlopen(u,timeout=12).read().decode('utf-8','ignore'))['response']['body']['item']
        B[c]={'nm':it.get('kaptName'),'ud':str(it.get('kaptUsedate') or '')}
    except Exception: B.setdefault(c,{})
need=[c for c in hit if not (B.get(c) or {}).get('ud')]
print('조회필요',len(need),flush=True)
with F.ThreadPoolExecutor(10) as ex: list(ex.map(bas,need))
json.dump(B,open('apt_basis.json','w'),ensure_ascii=False)
fin=set()
for c,zs in hit.items():
    ud=(B.get(c) or {}).get('ud') or ''
    if len(ud)<6: continue
    y=int(ud[:4])
    for z in zs:
        t=(z.get('s') or '')+(z.get('c') or '')+(z.get('n') or '')
        d=(z.get('d') or '').replace('.','')[:6]
        ok=len(d)>=6 and int(ud[:6])>=int(d)
        if not ok and '재건축' not in t and y>=1995: ok=True
        if ok: fin.add(z['n'])
s=io.open('stages.js',encoding='utf-8').read()
D=json.loads(s[s.index('=')+1:].strip().rstrip(';'))
D['fin']=sorted(fin)
io.open('stages.js','w',encoding='utf-8').write('window.ZSTAGE='+json.dumps(D,ensure_ascii=False)+';')
print('종료 확정 구역',len(fin))
