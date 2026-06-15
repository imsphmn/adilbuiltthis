const CACHE_NAME = 'adil-gym-shell-v2';
const APP_SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './apple-touch-icon.png',
  './icon-192.png',
  './icon-512.png'
];

function shouldTransformIndex(request, response) {
  if (!response || response.status !== 200 || response.type !== 'basic') return false;
  if (request.mode === 'navigate') return true;
  var url = new URL(request.url);
  return url.pathname.endsWith('/index.html') || url.pathname.endsWith('/');
}

function openCoachSections(html) {
  return html
    .replace(/<details class=\"ex-coll\">/g, '<details class=\"ex-coll\" open>')
    .replace(/<details class=\"pe-coll\">/g, '<details class=\"pe-coll\" open>');
}

function transformIndexResponse(request, response) {
  return response.text().then(function (html) {
    var transformed = openCoachSections(html);
    var headers = new Headers(response.headers);
    headers.set('content-type', 'text/html; charset=utf-8');
    var transformedResponse = new Response(transformed, {
      status: response.status,
      statusText: response.statusText,
      headers: headers
    });
    var cacheCopy = transformedResponse.clone();
    caches.open(CACHE_NAME).then(function (cache) {
      cache.put(request, cacheCopy);
    });
    return transformedResponse;
  });
}

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(APP_SHELL);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) {
        return key !== CACHE_NAME;
      }).map(function (key) {
        return caches.delete(key);
      }));
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function (event) {
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request).then(function (response) {
      if (shouldTransformIndex(event.request, response)) {
        return transformIndexResponse(event.request, response);
      }
      if (response && response.status === 200 && response.type === 'basic') {
        var copy = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(event.request, copy);
        });
      }
      return response;
    }).catch(function () {
      return caches.match(event.request).then(function (cached) {
        if (cached) return cached;
        if (event.request.mode === 'navigate') return caches.match('./index.html');
        return Response.error();
      });
    })
  );
});
