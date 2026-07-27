import io,re
p='index.html'; s=io.open(p,encoding='utf-8').read()
io.open(p+'.bak3','w',encoding='utf-8').write(s); E=[]
def rep(a,b):
    global s
    if s.count(a)!=1: E.append(a[:22]+'|%d'%s.count(a)); return
    s=s.replace(a,b)
rep("strokeWeight: 2, strokeColor: color, strokeOpacity: 0.95","strokeWeight: 2, strokeColor: zcol(z), strokeOpacity: 0.9")
rep("fillColor: color, fillOpacity: 0.22","fillColor: zcol(z), fillOpacity: 0.08")
L=''.join('<span><i style="background:%s"></i>%s</span>'%(c,t) for c,t in [('#FF8A3D','재개발'),('#FF6B6B','재건축'),('#FFC24B','모아·가로·소규모'),('#4DA3FF','역세권'),('#3DD68C','공공재개발'),('#B98CFF','촉진(뉴타운)')])
q=r'(<div id="zoneLegend">).*?(<b)'
n=len(re.findall(q,s,re.S))
if n!=1: E.append('legend|%d'%n)
else: s=re.sub(q,lambda m:m.group(1)+L+m.group(2),s,flags=re.S)
io.open(p,'w',encoding='utf-8').write(s)
print('실패:',E)
