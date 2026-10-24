const CACHE = 'fa-mobile-shell-v1';
const ASSETS = ['/', '/static/index.html', '/static/styles.css', '/static/app.js', '/manifest.webmanifest', '/static/icons/icon-192.png', '/static/icons/icon-512.png'];
self.addEventListener('install', ev => ev.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate', ev => ev.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch', ev => {
  const req=ev.request;
  if(req.method!=='GET' || new URL(req.url).origin!==location.origin || new URL(req.url).pathname.startsWith('/api/'))return;
  ev.respondWith(fetch(req).then(response=>{
    if(response.ok && (req.mode==='navigate' || ASSETS.includes(new URL(req.url).pathname))) {
      const copy=response.clone();caches.open(CACHE).then(c=>c.put(req,copy));
    }
    return response;
  }).catch(()=>caches.match(req).then(res=>res||caches.match('/'))));
});
