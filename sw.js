const CACHE_NAME = 'adil-gym-shell-v3';
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

function addStallDetection(html) {
  var cssMarker = '/* finish section */';
  var stallCss = '.stall-box { margin-top:10px; padding:10px 12px; background:var(--warn-bg); border:1px solid oklch(0.80 0.13 90 / 0.28); border-radius:var(--radius-sm); color:var(--muted); font-size:13px; line-height:1.4; }\n' +
    '.stall-box b { display:block; color:var(--warn); font-family:var(--mono); font-size:11px; letter-spacing:.1em; text-transform:uppercase; margin-bottom:3px; }\n\n' + cssMarker;
  html = html.replace(cssMarker, stallCss);

  var helperMarker = '// ---- next day in rotation ----';
  var helperCode = "// ---- stall detection ----\n" +
    "function getExerciseExposureSummaries(db, exId, limit) {\n" +
    "  var out = [];\n" +
    "  var sessions = db.completedSessions.slice().sort(function(a,b){ return b.startTime - a.startTime; });\n" +
    "  for (var i = 0; i < sessions.length && out.length < limit; i++) {\n" +
    "    var sets = sessions[i].sets.filter(function(s) {\n" +
    "      return s.exId === exId && s.completed && !s.skipped && s.setType !== 'warmup';\n" +
    "    });\n" +
    "    if (!sets.length) continue;\n" +
    "    var bestWeight = Math.max.apply(null, sets.map(function(s){ return s.weight || 0; }));\n" +
    "    var bestReps = sets.filter(function(s){ return (s.weight || 0) === bestWeight; }).reduce(function(max, s){ return Math.max(max, s.reps || 0); }, 0);\n" +
    "    out.push({ sessionId: sessions[i].id, startTime: sessions[i].startTime, bestWeight: bestWeight, bestReps: bestReps });\n" +
    "  }\n" +
    "  return out;\n" +
    "}\n" +
    "function exposureImproved(a, b) {\n" +
    "  if (!a || !b) return false;\n" +
    "  if (a.bestWeight > b.bestWeight) return true;\n" +
    "  return a.bestWeight === b.bestWeight && a.bestReps > b.bestReps;\n" +
    "}\n" +
    "function getStallInfo(db, exId) {\n" +
    "  var e = getExerciseExposureSummaries(db, exId, 3);\n" +
    "  if (e.length < 3) return null;\n" +
    "  var lastStalled = !exposureImproved(e[0], e[1]);\n" +
    "  var previousStalled = !exposureImproved(e[1], e[2]);\n" +
    "  if (!lastStalled || !previousStalled) return null;\n" +
    "  var load = e[0].bestWeight ? (e[0].bestWeight + ' kg x ' + e[0].bestReps) : (e[0].bestReps + ' reps');\n" +
    "  return { load: load, message: 'No progress for 2 exposures. Hold the load and add one clean rep; if it stalls again, reduce 5 to 10 percent and rebuild.' };\n" +
    "}\n\n" + helperMarker;
  html = html.replace(helperMarker, helperCode);

  var setRowsLine = "  var setRows = exSets.map(function(s) {\n";
  var stallVars = "  var stallInfo = getStallInfo(db, exId);\n" +
    "  var stallBox = stallInfo ? '<div class=\\\"stall-box\\\"><b>Stall watch</b>' + esc(stallInfo.message) + '<br><span>Last best: ' + esc(stallInfo.load) + '</span></div>' : '';\n" +
    setRowsLine;
  html = html.replace(setRowsLine, stallVars);

  var headerInsert = "      '<div class=\\\"exc-badges\\\">' +\n" +
    "        '<span class=\\\"xb\\\">'+ex.sDef+(ex.sMin!==ex.sMax?'\\u2013'+ex.sMax:'')+' sets</span>' +\n" +
    "        '<span class=\\\"xb\\\">'+ex.rMin+'\\u2013'+ex.rMax+' reps</span>' +\n" +
    "        '<span class=\\\"xb\\\">'+fmtRestLabel(ex.rest)+'</span>' +\n" +
    "      '</div>' +\n" +
    "      stallBox +\n";
  var headerOriginal = "      '<div class=\\\"exc-badges\\\">' +\n" +
    "        '<span class=\\\"xb\\\">'+ex.sDef+(ex.sMin!==ex.sMax?'\\u2013'+ex.sMax:'')+' sets</span>' +\n" +
    "        '<span class=\\\"xb\\\">'+ex.rMin+'\\u2013'+ex.rMax+' reps</span>' +\n" +
    "        '<span class=\\\"xb\\\">'+fmtRestLabel(ex.rest)+'</span>' +\n" +
    "      '</div>' +\n";
  html = html.replace(headerOriginal, headerInsert);

  return html;
}

function transformIndexResponse(request, response) {
  return response.text().then(function (html) {
    var transformed = addStallDetection(openCoachSections(html));
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
