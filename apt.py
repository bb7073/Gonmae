import os,re,urllib.parse,urllib.request
K=os.environ['DATA_KEY']
B="https://apis.data.go.kr/1613000/AptListService3"
def g(op,**kw):
    kw['serviceKey']=K; kw.setdefault('pageNo',1); kw.setdefault('numOfRows',9000)
    u=B+'/'+op+'?'+urllib.parse.urlencode(kw,safe="=")
    try: return urllib.request.urlopen(u,timeout=40).read().decode('utf-8','ignore')
    except Exception as e: return 'ERR '+repr(e)
for op,kw in [('getSidoAptList',{'sidoCode':'11'}),('getTotalAptList',{}),('getSigunguAptList',{'sigunguCode':'11110'})]:
    x=g(op,**kw)
    print(op,len(re.findall('<kaptCode>',x)),'|',x[:110].replace('\n',' '))
