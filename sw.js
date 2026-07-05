const CACHE_NAME = 'adil-gym-shell-v9';
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

function applyBlueTheme(html) {
  var replacements = [
    [/content=\"#1a1816\"/g, 'content="#090d1a"'],
    [/<title>Adil Gym<\/title>/g, '<title>Adil · Aesthetic Program</title>'],
    [/--bg:\s*[^;]+;/g, '--bg:         oklch(0.100 0.015 255);'],
    [/--bg-soft:\s*[^;]+;/g, '--bg-soft:    oklch(0.135 0.016 255);'],
    [/--card:\s*[^;]+;/g, '--card:       oklch(0.158 0.018 255);'],
    [/--card-hi:\s*[^;]+;/g, '--card-hi:    oklch(0.192 0.022 255);'],
    [/--line:\s*[^;]+;/g, '--line:       oklch(0.280 0.025 255);'],
    [/--line-soft:\s*[^;]+;/g, '--line-soft:  oklch(0.220 0.020 255);'],
    [/--text:\s*[^;]+;/g, '--text:       oklch(0.960 0.004 220);'],
    [/--muted:\s*[^;]+;/g, '--muted:      oklch(0.680 0.014 230);'],
    [/--faint:\s*[^;]+;/g, '--faint:      oklch(0.500 0.012 225);'],
    [/--accent:\s*[^;]+;/g, '--accent:     oklch(0.720 0.180 240);'],
    [/--accent-dk:\s*[^;]+;/g, '--accent-dk:  oklch(0.620 0.165 240);'],
    [/--accent-bg:\s*[^;]+;/g, '--accent-bg:  oklch(0.720 0.180 240 / 0.12);'],
    [/--accent-ln:\s*[^;]+;/g, '--accent-ln:  oklch(0.720 0.180 240 / 0.30);'],
    [/--steel:\s*[^;]+;/g, '--steel:      oklch(0.740 0.055 235);'],
    [/--steel-bg:\s*[^;]+;/g, '--steel-bg:   oklch(0.740 0.055 235 / 0.10);'],
    [/--danger:\s*[^;]+;/g, '--danger:     oklch(0.720 0.148 30);'],
    [/--danger-bg:\s*[^;]+;/g, '--danger-bg:  oklch(0.720 0.148 30 / 0.10);'],
    [/--danger-ln:\s*[^;]+;/g, '--danger-ln:  oklch(0.720 0.148 30 / 0.30);'],
    [/--ok:\s*[^;]+;/g, '--ok:         oklch(0.778 0.132 148);'],
    [/--ok-bg:\s*[^;]+;/g, '--ok-bg:      oklch(0.778 0.132 148 / 0.10);'],
    [/--warn:\s*[^;]+;/g, '--warn:       oklch(0.798 0.128 90);'],
    [/--warn-bg:\s*[^;]+;/g, '--warn-bg:    oklch(0.798 0.128 90 / 0.10);']
  ];
  replacements.forEach(function (pair) {
    html = html.replace(pair[0], pair[1]);
  });
  return html.replace('</style>', '\n#bottom-nav { background: oklch(0.112 0.016 255 / 0.94); }\n.wo-header { background: oklch(0.100 0.015 255 / 0.96); }\n</style>');
}

function addStallDetection(html) {
  if (html.indexOf('function getStallInfo') !== -1) return html;
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

function addUpdateHandling(html) {
  if (html.indexOf('id="update-banner"') !== -1) return html;

  var updateCss = '\n.update-banner { position:fixed; left:12px; right:12px; bottom:calc(var(--nav-h) + env(safe-area-inset-bottom,0px) + 10px); z-index:260; max-width:560px; margin:0 auto; display:flex; align-items:center; gap:10px; padding:11px 12px; border:1px solid var(--accent-ln); border-radius:var(--radius-sm); background:oklch(0.135 0.016 255 / 0.97); color:var(--text); box-shadow:0 12px 32px oklch(0 0 0 / 0.34); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }\n' +
    '.update-banner span { flex:1; font-size:13px; line-height:1.3; color:var(--muted); }\n' +
    '.update-banner button { flex:none; min-height:34px; border:none; border-radius:9px; padding:0 12px; background:var(--accent); color:oklch(0.12 0.004 60); font-size:13px; font-weight:750; cursor:pointer; }\n' +
    '.update-banner button:last-child { background:transparent; border:1px solid var(--line); color:var(--muted); padding:0 10px; }\n';
  html = html.replace('</style>', updateCss + '</style>');

  var updateScript = '<script>\n' +
    '(function(){\n' +
    "  if (!('serviceWorker' in navigator)) return;\n" +
    '  var controllerChanged = false;\n' +
    '  function showUpdateBanner(message) {\n' +
    "    if (document.getElementById('update-banner')) return;\n" +
    "    var el = document.createElement('div');\n" +
    "    el.id = 'update-banner';\n" +
    "    el.className = 'update-banner';\n" +
    "    el.innerHTML = '<span>' + message + '</span><button type=\\\"button\\\" data-action=\\\"reload\\\">Reload</button><button type=\\\"button\\\" data-action=\\\"dismiss\\\">Later</button>';\n" +
    "    el.querySelector('[data-action=\\\"reload\\\"]').onclick = function(){ location.reload(); };\n" +
    "    el.querySelector('[data-action=\\\"dismiss\\\"]').onclick = function(){ el.remove(); };\n" +
    '    document.body.appendChild(el);\n' +
    '  }\n' +
    '  function watchWorker(worker) {\n' +
    '    if (!worker) return;\n' +
    "    worker.addEventListener('statechange', function(){\n" +
    "      if (worker.state === 'installed' && navigator.serviceWorker.controller) {\n" +
    "        showUpdateBanner('Update ready. Reload to use the latest version.');\n" +
    '      }\n' +
    '    });\n' +
    '  }\n' +
    "  navigator.serviceWorker.addEventListener('controllerchange', function(){\n" +
    '    if (controllerChanged) return;\n' +
    '    controllerChanged = true;\n' +
    "    showUpdateBanner('Update installed. Reload to finish.');\n" +
    '  });\n' +
    "  window.addEventListener('load', function(){\n" +
    '    navigator.serviceWorker.ready.then(function(reg){\n' +
    '      watchWorker(reg.installing);\n' +
    '      watchWorker(reg.waiting);\n' +
    "      reg.addEventListener('updatefound', function(){ watchWorker(reg.installing); });\n" +
    '      reg.update().catch(function(){});\n' +
    '      setInterval(function(){ reg.update().catch(function(){}); }, 60 * 60 * 1000);\n' +
    '    }).catch(function(){});\n' +
    '  });\n' +
    '})();\n' +
    '</script>\n';
  return html.replace('</body>', updateScript + '</body>');
}

function transformIndexResponse(request, response) {
  return response.text().then(function (html) {
    var transformed = addUpdateHandling(addStallDetection(openCoachSections(applyBlueTheme(html))));
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
