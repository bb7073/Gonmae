import os,re,urllib.parse,urllib.request
K=os.environ['DATA_KEY']
def g(b,op,**kw):
    kw['serviceKey']=K; kw.setdefault('pageNo',1); kw.setdefault('numOfRows',5)
    u="https://apis.data.go.kr/1613000/%s/%s?%s"%(b,op,urllib.parse.urlencode(kw,safe="="))
    try: return urllib.request.urlopen(u,timeout=30).read().decode('utf-8','ignore')
    except Exception as e: return 'ERR '+repr(e)[:55]
for b,op in [("AptListService3","getTotalAptList3"),("AptListService3","getSidoAptList3"),("AptListService2","getTotalAptList"),("AptListService2","getSidoAptList"),("AptListService","getSidoAptList")]:
    x=g(b,op,sidoCode='11')
    print(op,len(re.findall('<kaptCode>',x)),'|',x[:85].replace('\n',' '))
