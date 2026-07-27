import io,re
p='index.html'; s=io.open(p,encoding='utf-8').read()
io.open(p+'.bak2','w',encoding='utf-8').write(s); E=[]
def rex(q,b):
    global s
    n=len(re.findall(q,s,re.S))
    if n!=1: E.append(q[:20]+'|%d'%n); return
    s=re.sub(q,lambda m:b,s,flags=re.S)
rex(r"function zdone\(n\)\{[^}]*\}","function zdone(n){var v=zstage(n);if(v&&window.ZDONE.indexOf(v)>=0)return true;var F=(window.ZSTAGE&&window.ZSTAGE.fin)||[];return F.indexOf(n)>=0;}")
rex(r"function zstage\(n\)\{[^}]*\}","function zstage(n){return (window.ZSTAGE&&window.ZSTAGE.st&&window.ZSTAGE.st[n])||'';}\nfunction zcol(z){var t=(z.s||'')+(z.n||'');if(/모아|소규모|가로|자율/.test(t))return '#FFC24B';if(/역세권/.test(t))return '#4DA3FF';if(/공공재개발|공공재건축/.test(t))return '#3DD68C';if(/촉진|뉴타운/.test(t))return '#B98CFF';if(/재건축/.test(t))return '#FF6B6B';return '#FF8A3D';}")
rex(r"최초고시","진행단계 ${(typeof z!=='undefined'&&z&&zstage(z.n))||'미확인'}<br>최초고시")
rex(r"ZCOL\[z\.c\]","zcol(z)")
io.open(p,'w',encoding='utf-8').write(s)
print('실패:',E)
m=re.search(r'.{0,150}zoneLegend.{0,700}',s,re.S)
print('--- 범례 ---'); print(m.group() if m else 'none')
