import os,json,time,urllib.parse,urllib.request
K=os.environ['DATA_KEY']
L=json.load(open('apt_list.json'))
try: C=json.load(open('apt_basis.json'))
except Exception: C={}
def g(u):
    for i in range(3):
        try: return urllib.request.urlopen(u,timeout=30).read().decode('utf-8','ignore')
        except Exception: time.sleep(1.5)
    return ''
n=0
for a in L:
    c=a.get('kaptCode')
    if not c or c in C: continue
    u='https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusBassInfoV4?'+urllib.parse.urlencode({'serviceKey':K,'kaptCode':c,'_type':'json'},safe='=')
    try:
        it=json.loads(g(u))['response']['body']['item']
        C[c]={'nm':it.get('kaptName'),'ad':it.get('kaptAddr'),'ud':str(it.get('kaptUsedate') or '')}
    except Exception:
        C[c]={}
    n+=1
    if n%200==0:
        json.dump(C,open('apt_basis.json','w'),ensure_ascii=False); print(n,flush=True)
json.dump(C,open('apt_basis.json','w'),ensure_ascii=False)
print('완료',len(C),flush=True)
