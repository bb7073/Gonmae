import re,json,os,time,importlib.util,requests
s=importlib.util.spec_from_file_location("m","fetch_jeongbi_stage.py");m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
U="https://cleanup.seoul.go.kr/cleanup/bsnssttus/lscrMainIndx.do?scupBsnsSttus.signguCode=%s&cpage=N&pageSize=500"
T=lambda x:re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",x).replace("&nbsp;"," ")).strip()
I=None;R=[]
for c in "11110,11140,11170,11200,11215,11230,11260,11290,11305,11320,11350,11380,11410,11440,11470,11500,11530,11545,11560,11590,11620,11650,11680,11710,11740".split(","):
 h=requests.get(U%c,headers={"User-Agent":"Mozilla/5.0"},timeout=40).text
 rs=re.findall(r"<tr[^>]*>(.*?)</tr>",max(re.findall(r"<table.*?</table>",h,re.S),key=len,default=""),re.S)
 if I is None:
  for r in rs:
   H=[T(x) for x in re.findall(r"<th[^>]*>(.*?)</th>",r,re.S)]
   if any("진행단계" in x for x in H):
    f=lambda n:next((i for i,x in enumerate(H) if n in x),-1)
    I=(f("사업장명"),f("대표지번"),f("진행단계"),f("자치구"));print(H,I);break
  if not I or I[0]<0:raise SystemExit("컬럼 못찾음")
 n=len(R)
 for r in rs:
  d=[T(x) for x in re.findall(r"<td[^>]*>(.*?)</td>",r,re.S)]
  if len(d)<=max(I) or not d[I[0]] or not d[I[2]]:continue
  w=re.search(r"mapOpenPopup\(\s*'([^']+)'",r)
  R.append({"gu":d[I[3]],"nm":d[I[0]],"jibun":d[I[1]],"stage":d[I[2]],"wt":w.group(1) if w else ""})
 print(c,len(R)-n)
print("총",len(R),R[:2])
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
