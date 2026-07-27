import re,json,os,time,importlib.util as u
s=u.spec_from_file_location("m","fetch_jeongbi_stage.py");m=u.module_from_spec(s);s.loader.exec_module(m)
def pr(h):
 o=[]
 for rh in m.ROW.findall(h):
  c=[m.text(x) for x in m.CELL.findall(rh)]
  if len(c)<6:continue
  i=next((k for k,v in enumerate(c) if v in m.STAGES),-1)
  if i<2:continue
  g=m.MAPID.search(rh)
  o.append({"gu":c[i-4] if i>=4 else "","nm":c[i-2],"jibun":c[i-1],"stage":c[i],"wt":g.group(1) if g else ""})
 return o
m.parse_rows=pr
R,_=m.crawl()
print("총",len(R),"(이전1042)")
for x in R[:3]:print(" ",x)
if len(R)<800:raise SystemExit("수집 비정상")
m.geocode_all(R,os.environ.get("KAKAO_REST_KEY"))
print("좌표",sum(1 for r in R if r.get("ll")),"/",len(R),"(이전724)")
from zone_tag import ZoneIndex
zi=ZoneIndex();F=json.load(open("jeongbi.geojson",encoding="utf-8"))["features"]
N=lambda x:m.norm(re.sub(r"\s*(조합|추진위원회|준비위원회)\s*$","",x.strip()))
B={}
for q in F:B.setdefault(N(q["properties"]["nm"]),q["properties"]["nm"])
K={x:i for i,x in enumerate(m.STAGES)};S={};a=b=0;M=[]
for r in R:
 nm=None;l=r.get("ll")
 if l:
  z=zi.find(l[0],l[1])
  if z:nm=z.get("nm");a+=1
 if not nm:
  nm=B.get(N(r["nm"]))
  if nm:b+=1
 if nm:
  if nm not in S or K.get(r["stage"],0)>K.get(S[nm],0):S[nm]=r["stage"]
 else:M.append(r["nm"])
cov=sum(1 for q in F if q["properties"]["nm"] in S)
print("좌표매칭%d 이름매칭%d 미연결%d (이전470/56/516)"%(a,b,len(M)))
print("폴리곤 %d/%d %.1f%% (이전782 26.3%%)"%(cov,len(F),100.0*cov/len(F)))
print("미연결:",M[:6])
if cov<782:raise SystemExit("나빠져서 저장안함")
json.dump(R,open("stages_raw.json","w",encoding="utf-8"),ensure_ascii=False)
open("stages.js","w",encoding="utf-8").write("window.ZSTAGE="+json.dumps({"gen":time.strftime("%Y-%m-%d"),"done":sorted(m.DONE),"st":S},ensure_ascii=False,separators=(",",":"))+";\n")
print("stages.js %.0fKB 구역%d 완료%d"%(os.path.getsize("stages.js")/1024,len(S),sum(1 for v in S.values() if v in m.DONE)))
