self.addEventListener('install', function(event) {
    event.waitUntil(
      caches.open('static-cache').then(function(cache) {
        return cache.addAll([
          '/',
          '/path/to/icon.png',
          // Add other static assets
        ]);
      })
    );
  });
  
  self.addEventListener('fetch', function(event) {
    event.respondWith(
      caches.match(event.request).then(function(response) {
        return response || fetch(event.request);
      })
    );
  });
  