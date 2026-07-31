(function boot(){
if(typeof map==="undefined"||!map||!window.SINTONG_OV||!window.kakao)
  return setTimeout(boot,400);
var MX=88200,MY=111100,OV=window.SINTONG_OV.filter(function(o){return !o.bad;});
var cur=null,img=null,idx=0,saved={},polys=[];
try{saved=JSON.parse(localStorage.getItem("sfit")||"{}");}catch(e){}
var mc=document.getElementById("map");
function bnd(o,st){var s=o.s*st.k;
 var a=st.lon-o.cx*s/MX,b=st.lat+o.cy*s/MY;
 return [a,b,a+o.w*s/MX,b-o.h*s/MY];}
function place(){if(!cur)return;var b=bnd(cur.o,cur.st),pj=map.getProjection();
 var p=pj.containerPointFromCoords(new kakao.maps.LatLng(b[1],b[0]));
 var q=pj.containerPointFromCoords(new kakao.maps.LatLng(b[3],b[2]));
 img.style.left=p.x+"px";img.style.top=p.y+"px";
 img.style.width=(q.x-p.x)+"px";img.style.height=(q.y-p.y)+"px";}
function geo(o,st){var s=o.s*st.k,b=bnd(o,st);
 return o.p.map(function(c){return [b[0]+c[0]*s/MX,b[1]-c[1]*s/MY];});}
function drawSaved(){polys.forEach(function(p){p.setMap(null);});polys=[];
 Object.keys(saved).forEach(function(k){
  var pg=new kakao.maps.Polygon({path:saved[k].map(function(c){
   return new kakao.maps.LatLng(c[1],c[0]);}),
   strokeWeight:2,strokeColor:"#FF2D95",strokeStyle:"shortdash",
   strokeOpacity:0.9,fillColor:"#FF2D95",fillOpacity:0.12,zIndex:9100});
  pg.setMap(map);polys.push(pg);});}
function open(i){
 if(i<0||i>=OV.length)return;idx=i;var o=OV[i];
 cur={o:o,st:{lon:o.xy[0],lat:o.xy[1],k:1}};
 if(!img){img=document.createElement("img");
  img.style.cssText="position:absolute;z-index:8000;opacity:.55;pointer-events:auto;cursor:move";
  mc.appendChild(img);
  var dx,dy,dr=false;
  img.onpointerdown=function(e){dr=true;dx=e.clientX;dy=e.clientY;
   img.setPointerCapture(e.pointerId);e.preventDefault();};
  img.onpointermove=function(e){if(!dr)return;
   var pj=map.getProjection(),b=bnd(cur.o,cur.st);
   var p=pj.containerPointFromCoords(new kakao.maps.LatLng(b[1],b[0]));
   var n=pj.coordsFromContainerPoint(new kakao.maps.Point(
     p.x+(e.clientX-dx),p.y+(e.clientY-dy)));
   var s=cur.o.s*cur.st.k;
   cur.st.lon=n.getLng()+cur.o.cx*s/MX;cur.st.lat=n.getLat()-cur.o.cy*s/MY;
   dx=e.clientX;dy=e.clientY;place();};
  img.onpointerup=function(){dr=false;};}
 img.src=o.u;img.style.display="block";
 document.getElementById("sfTit").textContent=(i+1)+"/"+OV.length+" "+o.n;
 document.getElementById("sfK").value=100;
 map.setCenter(new kakao.maps.LatLng(o.xy[1],o.xy[0]));
 map.setLevel(4);setTimeout(place,300);}
var bar=document.createElement("div");
bar.style.cssText="position:fixed;left:0;right:0;bottom:56px;z-index:9999;"+
 "background:rgba(20,20,25,.94);color:#fff;padding:8px 10px;font-size:13px;display:none";
bar.innerHTML='<div id="sfTit" style="margin-bottom:6px"></div>'+
 '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">'+
 '<span>크기</span><input id="sfK" type="range" min="40" max="250" value="100" style="flex:1">'+
 '<span>투명</span><input id="sfO" type="range" min="15" max="90" value="55" style="width:70px"></div>'+
 '<div style="display:flex;gap:6px"><button id="sfP">◀</button>'+
 '<button id="sfOK" style="flex:1;background:#FF2D95;color:#fff;border:0;padding:6px">확정</button>'+
 '<button id="sfNO" style="flex:1">건너뜀</button><button id="sfN">▶</button>'+
 '<button id="sfX">닫기</button><button id="sfE">내보내기</button></div>';
document.body.appendChild(bar);
document.getElementById("sfK").oninput=function(){cur.st.k=this.value/100;place();};
document.getElementById("sfO").oninput=function(){img.style.opacity=this.value/100;};
document.getElementById("sfP").onclick=function(){open(idx-1);};
document.getElementById("sfN").onclick=function(){open(idx+1);};
document.getElementById("sfNO").onclick=function(){open(idx+1);};
document.getElementById("sfOK").onclick=function(){
 saved[cur.o.n]=geo(cur.o,cur.st);
 localStorage.setItem("sfit",JSON.stringify(saved));
 drawSaved();open(idx+1);};
document.getElementById("sfX").onclick=function(){
 bar.style.display="none";if(img)img.style.display="none";};
document.getElementById("sfE").onclick=function(){
 var w=window.open("");w.document.write("<pre>"+
  JSON.stringify(saved).replace(/</g,"&lt;")+"</pre>");};
window.sintongFit=function(){bar.style.display="block";open(0);};
kakao.maps.event.addListener(map,"idle",place);
kakao.maps.event.addListener(map,"zoom_changed",place);
drawSaved();
console.log("FIT ready",OV.length);
})();
