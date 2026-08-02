const C="gonmae-v12";
self.addEventListener("install",e=>self.skipWaiting());
self.addEventListener("activate",e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.map(n=>n!==C&&caches.delete(n)))).then(()=>clients.claim())));
self.addEventListener("fetch",e=>{
if(e.request.method!=="GET")return;
if(e.request.url.indexOf("/photos/")>-1)return;
e.respondWith(fetch(e.request).then(r=>{const c=r.clone();caches.open(C).then(x=>x.put(e.request,c));return r;}).catch(()=>caches.match(e.request)));
});
