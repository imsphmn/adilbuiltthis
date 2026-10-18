const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const previous = execFileSync('git', ['show', '5108803:index.html'], {cwd:root});
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const file = path.join(root, pathname === '/' ? 'index.html' : pathname);
  res.setHeader('Content-Type', pathname.endsWith('.js') ? 'application/javascript' : 'text/html');
  if (pathname === '/previous.html') return res.end(previous);
  try { res.end(fs.readFileSync(file)); } catch { res.writeHead(404).end(); }
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://localhost:${server.address().port}`;
  const browser = await chromium.launch({headless:true,executablePath:process.env.TEST_BROWSER || chromium.executablePath()});
  const errors = [];
  const contexts = [];
  async function pageFor(seed, fault) {
    const context = await browser.newContext({viewport:{width:390,height:844}, serviceWorkers:'block', acceptDownloads:true});
    contexts.push(context);
    await context.addInitScript(({seed,fault}) => {
      if (!localStorage.getItem('test_seeded')) {
        localStorage.setItem('test_seeded','yes');
        localStorage.setItem('unrelated_data','leave this alone');
        if (seed.raw !== null) localStorage.setItem('adil_v2', seed.raw);
        if (seed.full) {
          for (let i=0; i<100; i++) {
            try {localStorage.setItem('adil_v2_backup_before_fixture_'+i, seed.raw);} catch {break;}
          }
        } else if (seed.backup) localStorage.setItem('adil_v2_backup_before_fixture',seed.backup);
      }
      if(fault === 'all-writes' || fault === 'main-write') {
        const original = Storage.prototype.setItem;
        Storage.prototype.setItem = function(key, value) {
          if(key === 'adil_v2' || (fault === 'all-writes' && key.startsWith('adil_v2_backup_before_')))
            throw new DOMException('Test storage quota exceeded','QuotaExceededError');
          return original.call(this,key,value);
        };
      }
      if(fault === 'all-writes') Object.defineProperty(window,'indexedDB',{get(){throw new Error('Test archive unavailable');}});
    }, {seed,fault});
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('dialog', dialog => dialog.dismiss());
    return page;
  }
  async function ready(page) { await page.waitForFunction(() => window.db && window.App && document.querySelector('.today-wrap .today-day-card')); }
  async function downloadJson(page, action) {
    const pending = page.waitForEvent('download');
    await page.evaluate(action);
    const download = await pending;
    return fs.readFileSync(await download.path(),'utf8');
  }
  try {
    const base = await pageFor({raw:null});
    await base.goto(url); await ready(base);
    const raw = await base.evaluate(() => {
      const d=dbDefault(), completed=createSession(1,true);
      completed.sets=initWorkoutSets(1,d,completed);
      completed.dayTitle='Saved chest workout';completed.finished=true;
      completed.startTime=Date.now()-86400000;completed.endTime=completed.startTime+3600000;
      completed.sets[0].weight=26;completed.sets[0].reps=9;completed.sets[0].completed=true;
      d.completedSessions=[completed];
      const active=createSession(2,true);active.sets=initWorkoutSets(2,d,active);
      active.sets[0].weight=45;active.sets[0].reps=9;active.sets[0].draftTouched=true;
      d.activeSession=active;d.homeRoutineLogs=[{date:'2026-10-18',items:{breathing_9090:true}}];
      d.customPayload={provenance:'keep',padding:'x'.repeat(500000)};
      delete d.engagement;
      return JSON.stringify(d);
    });
    const original=JSON.parse(raw);

    const recovery=await pageFor({raw,full:true});
    await recovery.goto(url+'/previous.html'); await ready(recovery);
    assert.equal(await recovery.evaluate(() => DB_STORAGE_BLOCKED),true);
    assert.equal(await recovery.evaluate(() => db.completedSessions.length),0);
    assert.equal(await recovery.evaluate(() => localStorage.getItem('adil_v2')),raw);
    const before=await recovery.evaluate(() => Object.keys(localStorage).filter(key=>key.startsWith('adil_v2_backup_before_')));
    assert.ok(before.length>1);
    await recovery.goto(url); await ready(recovery);
    assert.equal(await recovery.evaluate(() => DB_STORAGE_BLOCKED),false);
    assert.deepEqual(await recovery.evaluate(() => db.completedSessions[0].sets),original.completedSessions[0].sets);
    assert.deepEqual(await recovery.evaluate(() => db.activeSession.sets),original.activeSession.sets);
    assert.deepEqual(await recovery.evaluate(() => db.customPayload),original.customPayload);
    assert.equal(await recovery.evaluate(() => localStorage.getItem('unrelated_data')),'leave this alone');
    assert.deepEqual(await recovery.evaluate(() => localBackupKeys()),[]);
    const archived=await recovery.evaluate(() => readArchivedBackups());
    for(const key of before) assert.ok(archived.some(row => row.sourceKey===key && row.raw===raw));
    await recovery.evaluate(() => App.showScreen('history'));
    assert.match(await recovery.locator('#scr-history').innerText(),/Saved chest workout/);
    await recovery.evaluate(() => {db.activeSession.sets[0].reps=10; if(!dbSave(db)) throw Error('Save failed');});
    await recovery.reload(); await ready(recovery);
    assert.equal(await recovery.evaluate(() => db.activeSession.sets[0].reps),10);
    assert.equal((await recovery.evaluate(() => readArchivedBackups())).length,archived.length);
    for(const screen of ['program','home','volume','history','today']) await recovery.evaluate(screen => App.showScreen(screen),screen);
    await recovery.screenshot({path:'/tmp/gym-recovered-mobile.png',fullPage:true});
    console.log('PASS: reproduced original quota/empty-history bug; recovered history, drafts and saving; verified archives, unrelated data and repeat load.');

    for(const fault of ['main-write','all-writes']) {
      const page=await pageFor({raw,backup:raw},fault);
      await page.goto(url);await ready(page);
      assert.equal(await page.evaluate(() => DB_STORAGE_BLOCKED),true);
      assert.equal(await page.evaluate(() => DB_SAFE_TO_EXPORT),true);
      assert.equal(await page.evaluate(() => db.completedSessions.length),1);
      assert.deepEqual(await page.evaluate(() => db.activeSession.sets),original.activeSession.sets);
      assert.equal(await page.evaluate(() => localStorage.getItem('adil_v2')),raw);
      if(fault==='all-writes')assert.equal(await page.evaluate(() => localStorage.getItem('adil_v2_backup_before_fixture')),raw);
      const exported=JSON.parse(await downloadJson(page,() => App.doExport()));
      assert.deepEqual(exported.data.completedSessions[0].sets,original.completedSessions[0].sets);
      console.log('PASS: '+fault+' retains visible history, original saved data, active drafts and a downloadable workout backup.');
    }

    const malformed=await pageFor({raw:'{broken saved json'});
    await malformed.goto(url);await ready(malformed);
    assert.equal(await malformed.evaluate(() => DB_STORAGE_BLOCKED),true);
    assert.equal(await malformed.evaluate(() => dbSave(db)),false);
    assert.equal(await downloadJson(malformed,() => App.doExport()),'{broken saved json');
    assert.equal(await malformed.evaluate(() => localStorage.getItem('adil_v2')),'{broken saved json');
    console.log('PASS: malformed original cannot be overwritten; recovery export preserves its exact bytes.');

    const missing=await pageFor({raw:null,backup:raw});
    await missing.goto(url);await ready(missing);
    assert.equal(await missing.evaluate(() => DB_STORAGE_BLOCKED),true);
    assert.equal(await missing.evaluate(() => localStorage.getItem('adil_v2')),null);
    const copies=JSON.parse(await downloadJson(missing,() => exportRecoveryCopies()));
    assert.equal(copies.backups[0].raw,raw);
    console.log('PASS: missing main database protects recovery copies and exports them without guessing which to restore.');

    const importPage=await pageFor({raw});await importPage.goto(url);await ready(importPage);
    await Promise.all([importPage.waitForNavigation(),importPage.evaluate(() => App.handleImport(new File([JSON.stringify({version:3,data:db})],'backup.json',{type:'application/json'})))]);
    await importPage.waitForFunction(() => window.db && !DB_STORAGE_BLOCKED);
    assert.equal(await importPage.evaluate(() => db.completedSessions.length),1);
    console.log('PASS: backup import preserves completed history and active session.');

    const swContext=await browser.newContext({viewport:{width:390,height:844}});contexts.push(swContext);
    const swPage=await swContext.newPage();swPage.on('pageerror',error=>errors.push(error.message));
    await swPage.goto(url);await ready(swPage);
    await swPage.evaluate(() => navigator.serviceWorker.ready);
    await swPage.reload();await ready(swPage);
    assert.equal(await swPage.evaluate(() => APP_VERSION),'3.6.1');
    assert.equal(await swPage.evaluate(() => DB_STORAGE_BLOCKED),false);
    assert.ok((await swPage.evaluate(() => caches.keys())).includes('adil-gym-shell-v23'));
    console.log('PASS: service worker first/repeat load serves app 3.6.1 and cache v23.');
    assert.deepEqual(errors,[]);
    console.log('PASS: no browser JavaScript errors.');
  } finally {
    await Promise.all(contexts.map(context=>context.close()));
    await browser.close();await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error);server.close();process.exitCode=1;});
