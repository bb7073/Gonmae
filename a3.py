import os,json,time,urllib.parse,urllib.request
K=os.environ['DATA_KEY']
def U(path,**kw):
    kw['serviceKey']=K; kw['_type']='json'
    return 'https://apis.data.go.kr/1613000/'+path+'?'+urllib.parse.urlencode(kw,safe="=")
def g(u):
    e=''
    for i in range(3):
        try: return urllib.request.urlopen(u,timeout=40).read().decode('utf-8','ignore')
        except Exception as x: e=repr(x)[:60]; time.sleep(2)
    return 'ERR '+e
def items(x):
    try:
        b=json.loads(x)['response']['body']; it=b.get('items') or []
        if isinstance(it,dict): it=it.get('item') or []
        if isinstance(it,dict): it=[it]
        return it,int(b.get('totalCount') or 0)
    except Exception: return [],0
out=[]; p=1
while p<12:
    it,tc=items(g(U('AptListService3/getSidoAptList3',sidoCode='11',pageNo=p,numOfRows=1000)))
    out+=it
    if not it or len(out)>=tc: break
    p+=1
json.dump(out,open('apt_list.json','w'),ensure_ascii=False)
print('서울 단지',len(out))
c=out[0]['kaptCode'] if out else 'A10021295'
for b,op in [('AptBasisInfoServiceV4','getAphusBassInfoV4'),('AptBasisInfoServiceV3','getAphusBassInfoV3'),('AptBasisInfoServiceV2','getAphusBassInfoV2'),('AptBasisInfoService','getAphusBassInfo')]:
    print(op,'|',g(U(b+'/'+op,kaptCode=c))[:120].replace('\n',' '))
