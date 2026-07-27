import io,json,re
def L(f):
    t=io.open(f,encoding='utf-8').read(); return json.loads(t[t.index('=')+1:].strip().rstrip(';'))
Z=L('jeongbi_map.js'); D=L('stages.js'); st=D['st']
R=json.load(open('stages_raw.json'))
NO=re.compile(r'(주택재개발|도시환경|주택재건축|재개발|재건축|정비사업|정비구역|재정비촉진|가로주택|자율주택|소규모주택|소규모|공공지원|공공|역세권|도시정비형|주택정비형|조합|추진위원회|사업|구역|지구|일대|일원|제|\s|·|\(|\)|-)')
def k(x): return NO.sub('',x or '')
zk={}
for z in Z: zk.setdefault(k(z['n']),set()).add(z['n'])
a=0
for r in R:
    g=r.get('stage')
    if not g: continue
    for f in ('nm','jibun'):
        key=k(r.get(f)); c=zk.get(key)
        if c and len(c)==1 and len(key)>2:
            n=list(c)[0]
            if n not in st: st[n]=g; a+=1
io.open('stages.js','w',encoding='utf-8').write('window.ZSTAGE='+json.dumps(D,ensure_ascii=False)+';')
s=io.open('index.html',encoding='utf-8').read()
n=len(re.findall(r'이 데이터에는.*?확인하세요\.',s,re.S))
s=re.sub(r'이 데이터에는.*?확인하세요\.','',s,flags=re.S)
io.open('index.html','w',encoding='utf-8').write(s)
print('구역 추가',a,'총',len(st),'/ 안내문 제거',n)
