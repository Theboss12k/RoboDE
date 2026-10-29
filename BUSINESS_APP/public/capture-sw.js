// Cache only the self-contained capture page. Never cache authenticated API data.
const capture=new URL('room-capture.html',self.location).href;
self.addEventListener('install',event=>event.waitUntil(caches.open('robot-capture-v1').then(cache=>cache.add(capture))));
self.addEventListener('fetch',event=>{if(event.request.method==='GET'&&event.request.url===capture)event.respondWith(fetch(event.request).then(response=>{if(response.ok){const saved=response.clone();caches.open('robot-capture-v1').then(cache=>cache.put(capture,saved));}return response}).catch(()=>caches.match(capture)));});
