import io,re,sys
p='index.html'; s=io.open(p,encoding='utf-8').read()
io.open('index.html.bak','w',encoding='utf-8').write(s)
E=[]
def rep(a,b):
    global s
    if s.count(a)!=1: E.append(a[:24]+'|%d'%s.count(a)); return
    s=s.replace(a,b)
def rex(q,b):
    global s
    n=len(re.findall(q,s,re.S))
    if n!=1: E.append(q[:24]+'|%d'%n); return
    s=re.sub(q,lambda m:b,s,flags=re.S)
A='<script src="data_gyeongmae.js"></script>'
if 'stages.js' not in s:
    rep(A,A+'''
<script src="stages.js"></script>
<script>
window.ZDONE=(window.ZSTAGE&&window.ZSTAGE.done)||['준공인가','이전고시','조합해산','조합청산'];
function zstage(n){return (window.ZSTAGE&&window.ZSTAGE.st&&window.ZSTAGE.st[n])||'';}
function zdone(n){var v=zstage(n);return !!v&&window.ZDONE.indexOf(v)>=0;}
</script>''')
rex(r"const zOld\s*=\s*zYear && zYear < 2010;","const zOld = zYear && zYear < 2010;\n  const zSt = zstage(d.zone), zFin = !!zSt && zdone(d.zone);")
rex(r"const zoneBox = d\.zone \?","const zoneBox = (d.zone && !zFin) ?")
rex(r'class="zonebox\$\{zOld[^}]*\}"','class="zonebox"')
B="${d.zoneDate ? `<br>최초 결정고시 <b>${d.zoneDate}</b>` : ''}"
rep(B,B+"\n      ${zSt ? `<br>진행단계 <b>${zSt}</b>` : ''}")
rex(r"\$\{zOld \? `<small>⚠.*?</small>` : ''\}","")
rep('<b>진행단계 정보가 없습니다</b>','<b>진행단계는 정보몽땅 기준</b>(표시 없으면 미확인)')
rex(r"for\(const z of window\.JEONGBI\)\{","for(const z of window.JEONGBI){\n    if(zdone(z.n)) continue;")
if E: print('실패:',E); sys.exit(1)
io.open(p,'w',encoding='utf-8').write(s); print('패치 OK')
