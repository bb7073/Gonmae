const C="gonmae-v13";
self.addEventListener("install",e=>self.skipWaiting());
self.addEventListener("activate",e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.map(n=>n!==C&&caches.delete(n)))).then(()=>clients.claim())));
self.addEventListener("fetch",e=>{
if(e.request.method!=="GET")return;
if(e.request.url.indexOf("/photos/")>-1)return;
if(e.request.mode==="navigate"){e.respondWith(fetch(e.request,{cache:"reload"}).catch(()=>caches.match(e.request)));return;}
e.respondWith(fetch(e.request).then(r=>{const c=r.clone();caches.open(C).then(x=>x.put(e.request,c));return r;}).catch(()=>caches.match(e.request)));
});
