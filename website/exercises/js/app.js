/*
 * Home Exercise Program builder.
 * Views (by URL hash): #build (default), #templates, #settings, #p=<code> (patient handout).
 * Everything is stored in this browser (localStorage). Patient programs travel inside the link.
 */
(function () {
  'use strict';

  var D = window.HEPData, F = window.HEPFig;
  var CFG = window.HEP_CONFIG || {};
  var QR_LIB = 'https://cdnjs.cloudflare.com/ajax/libs/qrcode-generator/1.4.4/qrcode.min.js';

  /* ---------- helpers ---------- */

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function fmtDate(iso) {
    if (!iso) return '';
    var p = iso.split('-');
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    return isNaN(d) ? iso : d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
  }
  function uid(prefix) { return prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function num(v, min, max) {
    var n = parseInt(v, 10);
    if (isNaN(n)) return 0;
    return Math.max(min, Math.min(max, n));
  }
  function hashStr(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  var store = {
    get: function (k, d) {
      try { var v = localStorage.getItem('hep.' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; }
    },
    set: function (k, v) {
      try { localStorage.setItem('hep.' + k, JSON.stringify(v)); return true; } catch (e) { return false; }
    }
  };

  var ICON = {
    up: '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15V5M5 10l5-5 5 5"/></svg>',
    down: '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 5v10M5 10l5 5 5-5"/></svg>',
    x: '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 5l10 10M15 5L5 15"/></svg>',
    text: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>'
  };

  /* ---------- state ---------- */

  var DEFAULT_FOOTER = 'Do these exercises as your therapist showed you. Mild stretching or muscle effort is normal. ' +
    'Stop and contact us if you have sharp pain, pain that lasts more than 2 hours after exercising, ' +
    'new numbness or tingling, dizziness, or new swelling.';
  var DEFAULT_SETTINGS = { clinic: CFG.clinic || '', therapist: '', phone: CFG.phone || '', contact: CFG.contact || '', footer: DEFAULT_FOOTER, theme: 'auto' };

  var settings = Object.assign({}, DEFAULT_SETTINGS, store.get('settings', {}));
  var custom = store.get('custom', []);
  var templates = store.get('templates', []);
  var draft = store.get('draft', null) || newDraft();
  var filter = { q: '', region: 'all', type: 'all' };

  function newDraft() { return { title: 'Home exercise program', patient: '', notes: '', date: today(), items: [] }; }
  function saveDraft() { store.set('draft', draft); }

  function allExercises() { return D.exercises.concat(custom); }
  function findEx(id, extra) {
    var list = allExercises().concat(extra || []);
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  function regionLabel(id, short) {
    if (short) return { neck: 'Neck', back: 'Back', shoulder: 'Shoulder', hand: 'Hand', leg: 'Leg' }[id] || id;
    var r = D.regions.filter(function (x) { return x.id === id; })[0];
    return r ? r.label : id;
  }
  function typeLabel(id) {
    var t = D.types.filter(function (x) { return x.id === id; })[0];
    return t ? t.label : id;
  }

  function applyTheme() {
    if (settings.theme === 'light' || settings.theme === 'dark') document.documentElement.setAttribute('data-theme', settings.theme);
    else document.documentElement.removeAttribute('data-theme');
  }

  /* ---------- dosage text ---------- */

  function fmtSecs(s) {
    if (s < 60) return s + ' sec';
    var m = Math.floor(s / 60), r = s % 60;
    return m + ' min' + (r ? ' ' + r + ' sec' : '');
  }
  function doseParts(d) {
    var out = [];
    var sets = d.sets || 0, reps = d.reps || 0;
    if (reps) out.push((sets > 1 ? sets + ' sets of ' : '') + reps + (reps === 1 ? ' time' : ' times'));
    else if (sets > 1) out.push(sets + ' sets');
    if (d.hold) out.push('Hold ' + fmtSecs(d.hold));
    if (d.sides) out.push('Each side');
    if (d.perDay) out.push(d.perDay === 1 ? 'Once a day' : d.perDay === 2 ? 'Twice a day' : d.perDay + ' times a day');
    return out;
  }

  /* ---------- figures & animation ---------- */

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function photosFor(ex) {
    var p = ex && window.HEPPhotos && window.HEPPhotos[ex.id];
    return p && p.length ? p : null;
  }
  function frames(ex) { var p = photosFor(ex); return p ? p.length : F.frameCount(ex.fig); }
  function hasPicture(ex) { return !!(ex.fig || photosFor(ex)); }
  function staticT(ex) { var n = frames(ex); return n > 2 ? Math.floor(n / 2) : n - 1; }

  function figHTML(ex, t) {
    var photos = photosFor(ex);
    if (photos) {
      var i = Math.max(0, Math.min(photos.length - 1, Math.round(t == null ? staticT(ex) : t)));
      return '<img class="photo" src="' + esc(photos[i]) + '" alt="' + esc(ex.name) + '">';
    }
    if (!ex.fig) return '<div class="nofig">' + ICON.text + '<span>Instructions only</span></div>';
    return F.render(ex.fig, t == null ? staticT(ex) : t, 'Illustration: ' + ex.name);
  }

  function framesHTML(ex) {
    var n = frames(ex);
    if (!n || (!ex.fig && !photosFor(ex))) return '';
    var out = '';
    for (var i = 0; i < n; i++) {
      var label = n === 1 ? '' : n === 2 ? (i === 0 ? 'Start' : 'End') : 'Step ' + (i + 1);
      out += '<div class="frame">' + figHTML(ex, i) + label + '</div>';
    }
    return '<div class="frames">' + out + '</div>';
  }

  // Ping-pong through key frames: hold, move, hold, move back...
  function animT(sec, n) {
    if (n < 2) return 0;
    var HOLD = 0.8, MOVE = 1.4, path = [];
    for (var i = 0; i < n; i++) path.push(i);
    for (var j = n - 2; j > 0; j--) path.push(j);
    var seg = HOLD + MOVE, x = sec % (path.length * seg);
    var idx = Math.floor(x / seg), local = x - idx * seg;
    var a = path[idx], b = path[(idx + 1) % path.length];
    if (local < HOLD) return a;
    var u = (local - HOLD) / MOVE;
    return a + (b - a) * (0.5 - 0.5 * Math.cos(Math.PI * u));
  }

  var anim = { els: [], raf: 0, last: 0 };
  function animate(el, ex) {
    if (reduceMotion || !hasPicture(ex) || frames(ex) < 2) return;
    if (anim.els.indexOf(el) < 0) { el._ex = ex; el._t0 = null; anim.els.push(el); }
    if (!anim.raf) anim.raf = requestAnimationFrame(tick);
  }
  function stopAnim(el) {
    var i = anim.els.indexOf(el);
    if (i >= 0) anim.els.splice(i, 1);
    var cur = el._ex && el.querySelector('svg.fig, img.photo');
    if (cur) cur.outerHTML = figHTML(el._ex);
  }
  function tick(ts) {
    anim.raf = 0;
    anim.els = anim.els.filter(function (el) { return el.isConnected; });
    if (!anim.els.length) return;
    if (ts - anim.last > 33) {
      anim.last = ts;
      anim.els.forEach(function (el) {
        if (el._paused) return;
        if (el._t0 == null) el._t0 = ts;
        var sec = (ts - el._t0) / 1000;
        var photos = photosFor(el._ex);
        if (photos) {
          // Photos: show each picture in turn.
          var img = el.querySelector('img.photo');
          var src = photos[Math.floor(sec / 1.8) % photos.length];
          if (img && img.getAttribute('src') !== src) img.setAttribute('src', src);
          return;
        }
        var svg = el.querySelector('svg.fig');
        if (!svg) return;
        svg.outerHTML = F.render(el._ex.fig, animT(sec, F.frameCount(el._ex.fig)), 'Illustration: ' + el._ex.name);
      });
    }
    anim.raf = requestAnimationFrame(tick);
  }

  /* ---------- modal, confirm, toast ---------- */

  var modalEl = null, modalOnClose = null, lastFocus = null;

  function openModal(opts) {
    closeModal();
    lastFocus = document.activeElement;
    modalEl = document.createElement('div');
    modalEl.className = 'modal';
    modalEl.innerHTML = '<div class="modal-backdrop" data-close></div>' +
      '<div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="modal-title">' +
      '<div class="modal-head"><h2 id="modal-title">' + opts.title + '</h2>' +
      '<button class="btn btn-ghost btn-icon" data-close aria-label="Close">' + ICON.x + '</button></div>' +
      '<div class="modal-body">' + opts.body + '</div>' +
      (opts.foot ? '<div class="modal-foot">' + opts.foot + '</div>' : '') + '</div>';
    document.body.appendChild(modalEl);
    modalOnClose = opts.onClose || null;
    modalEl.addEventListener('click', function (e) {
      if (e.target.closest('[data-close]')) closeModal();
    });
    if (opts.onMount) opts.onMount(modalEl);
    var f = modalEl.querySelector('[autofocus]') || modalEl.querySelector('.modal-body input, .modal-body textarea, .modal-foot .btn-primary') || modalEl.querySelector('[data-close].btn');
    if (f) f.focus();
    return modalEl;
  }
  function closeModal() {
    if (!modalEl) return;
    $$('[data-anim]', modalEl).forEach(stopAnim);
    modalEl.remove();
    modalEl = null;
    var cb = modalOnClose; modalOnClose = null;
    if (cb) cb();
    if (lastFocus && lastFocus.isConnected) lastFocus.focus();
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && modalEl) closeModal(); });

  function confirmModal(message, okLabel, danger) {
    return new Promise(function (resolve) {
      var answered = false;
      openModal({
        title: 'Please confirm',
        body: '<p>' + message + '</p>',
        foot: '<button class="btn" data-close>Cancel</button><button class="btn ' + (danger ? 'btn-danger' : 'btn-primary') + '" data-ok>' + (okLabel || 'OK') + '</button>',
        onMount: function (m) {
          m.querySelector('[data-ok]').addEventListener('click', function () { answered = true; closeModal(); resolve(true); });
        },
        onClose: function () { if (!answered) resolve(false); }
      });
    });
  }

  var toastTimer = 0;
  function toast(msg) {
    var t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2600);
  }

  /* ---------- link encoding ---------- */

  function b64u(bytes) {
    var s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function unb64u(str) {
    var s = atob(str.replace(/-/g, '+').replace(/_/g, '/'));
    var out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }
  function encodeProgram(obj) {
    var bytes = new TextEncoder().encode(JSON.stringify(obj));
    if (window.CompressionStream) {
      try {
        var cs = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'));
        return new Response(cs).arrayBuffer().then(function (buf) { return 'z' + b64u(new Uint8Array(buf)); })
          .catch(function () { return 'j' + b64u(bytes); });
      } catch (e) { /* fall through */ }
    }
    return Promise.resolve('j' + b64u(bytes));
  }
  function decodeProgram(code) {
    return Promise.resolve().then(function () {
      var kind = code.charAt(0), bytes = unb64u(code.slice(1));
      if (kind === 'z') {
        var ds = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
        return new Response(ds).arrayBuffer().then(function (b) { return new Uint8Array(b); });
      }
      if (kind !== 'j') throw new Error('Unknown format');
      return bytes;
    }).then(function (b) { return JSON.parse(new TextDecoder().decode(b)); });
  }

  function buildPayload() {
    var cx = [];
    draft.items.forEach(function (it) {
      var ex = findEx(it.id);
      if (ex && ex.custom && !cx.some(function (c) { return c.id === ex.id; })) {
        cx.push({ id: ex.id, name: ex.name, region: ex.region, type: ex.type, area: ex.area, position: ex.position,
          summary: ex.summary, steps: ex.steps, tips: ex.tips, caution: ex.caution });
      }
    });
    var c = [settings.clinic, settings.therapist, settings.phone, settings.contact,
      settings.footer === DEFAULT_FOOTER ? '' : settings.footer];
    return {
      v: 1, t: draft.title, n: draft.patient, d: draft.date, o: draft.notes, c: c,
      i: draft.items.map(function (it) { return [it.id, it.sets, it.reps, it.hold, it.perDay, it.sides ? 1 : 0, it.note || '']; }),
      x: cx
    };
  }

  function linkFor(code) { return location.href.split('#')[0] + '#p=' + code; }

  function canPhoneOpen() {
    return /^https?:$/.test(location.protocol) && !/^(localhost|127\.|\[::1\])/.test(location.hostname);
  }

  var qrPromise = null;
  function loadQR() {
    if (window.qrcode) return Promise.resolve(window.qrcode);
    if (!qrPromise) {
      qrPromise = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = QR_LIB;
        s.onload = function () { resolve(window.qrcode); };
        s.onerror = function () { qrPromise = null; reject(new Error('QR library unavailable')); };
        document.head.appendChild(s);
      });
    }
    return qrPromise;
  }
  function qrSVG(text) {
    return loadQR().then(function (qrcode) {
      var q = qrcode(0, 'L');
      q.addData(text);
      q.make();
      return q.createSvgTag(4, 2);
    });
  }

  /* ---------- routing ---------- */

  /* ---------- staff login ---------- */

  // A simple browser-side gate for the builder (see js/config.js). Patient links skip it.
  var memAuth = false;
  function isAuthed() {
    if (!CFG.username) return true; // no login configured
    try { return sessionStorage.getItem('hep.auth') === '1' || memAuth; } catch (e) { return memAuth; }
  }
  function setAuthed(on) {
    memAuth = on;
    try { if (on) sessionStorage.setItem('hep.auth', '1'); else sessionStorage.removeItem('hep.auth'); } catch (e) { /* private mode */ }
  }

  function renderLogin() {
    var bar = $('#topbar');
    bar.hidden = true;
    document.title = 'Sign in – SD Mobile PT Exercises';
    $('#main').innerHTML = '<div class="login">' +
      '<form class="panel login-card" id="login-form" novalidate>' +
      '<img class="login-logo" src="assets/sdmpt-logo.png" alt="SD Mobile PT – San Diego Mobile Physical Therapist">' +
      '<h1>Exercise Program Builder</h1>' +
      '<p class="muted">Staff sign in</p>' +
      '<label class="field"><span>Username</span><input type="text" id="login-user" autocomplete="username" autocapitalize="none" spellcheck="false" required></label>' +
      '<label class="field"><span>Password</span><input type="password" id="login-pass" autocomplete="current-password" required></label>' +
      '<p class="login-error" id="login-error" role="alert"></p>' +
      '<button class="btn btn-primary login-btn" type="submit">Sign in</button>' +
      '<p class="small muted login-note">Patients: open the exercise link your therapist sent you. You don’t need to sign in.</p>' +
      (CFG.websiteUrl ? '<a class="small login-back" href="' + esc(CFG.websiteUrl) + '">← Back to sdmobilept.com</a>' : '') +
      '</form></div>';
    var form = $('#login-form'), user = $('#login-user'), pass = $('#login-pass'), err = $('#login-error');
    user.focus();
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var ok = user.value.trim().toLowerCase() === String(CFG.username).toLowerCase() && pass.value === String(CFG.password);
      if (!ok) {
        err.textContent = 'Incorrect username or password. Please try again.';
        form.classList.remove('shake'); void form.offsetWidth; form.classList.add('shake');
        pass.value = '';
        pass.focus();
        return;
      }
      setAuthed(true);
      bar.hidden = false;
      if (location.hash === '#logout') location.hash = '#build';
      else route();
    });
  }

  function route() {
    var h = location.hash;
    closeModal();
    document.body.classList.remove('has-mobile-bar');
    var mb = $('.mobile-bar'); if (mb) mb.remove();
    $('#topbar').hidden = false;
    if (h.indexOf('#p=') === 0) return renderPatient(h.slice(3));
    if (h === '#logout') { setAuthed(false); }
    if (!isAuthed()) return renderLogin();
    store.set('isEditor', true);
    var view = h.slice(1) || 'build';
    if (['build', 'templates', 'settings'].indexOf(view) < 0) view = 'build';
    renderTopbar(view);
    document.title = 'Exercises – SD Mobile PT';
    if (view === 'templates') renderTemplates();
    else if (view === 'settings') renderSettings();
    else renderBuild();
    window.scrollTo(0, 0);
  }

  function renderTopbar(view) {
    var bar = $('#topbar');
    var name = settings.clinic || 'SD Mobile PT';
    var sub = view === 'patient' ? 'Your home exercise program' : 'Exercise program builder';
    bar.innerHTML = '<div class="brand"><div class="brand-mark"><img src="assets/sdmpt-mark.png" alt=""></div><div class="brand-text"><div>' + esc(name) +
      '</div><small>' + sub + '</small></div></div>' +
      (view === 'patient' ? '' :
        '<nav class="nav" aria-label="Main">' +
        '<a href="#build"' + (view === 'build' ? ' aria-current="page"' : '') + '>Build program</a>' +
        '<a href="#templates"' + (view === 'templates' ? ' aria-current="page"' : '') + '>Templates</a>' +
        '<a href="#settings"' + (view === 'settings' ? ' aria-current="page"' : '') + '>Settings</a>' +
        (CFG.username ? '<a href="#logout" class="nav-logout">Log out</a>' : '') + '</nav>');
  }

  /* ---------- build view ---------- */

  function renderBuild() {
    var main = $('#main');
    var chips = '<button class="chip" data-region="all" aria-pressed="' + (filter.region === 'all') + '">All</button>' +
      D.regions.map(function (r) {
        return '<button class="chip" data-region="' + r.id + '" aria-pressed="' + (filter.region === r.id) + '">' + esc(r.label) + '</button>';
      }).join('');
    var types = '<option value="all">All types</option>' + D.types.map(function (t) {
      return '<option value="' + t.id + '"' + (filter.type === t.id ? ' selected' : '') + '>' + t.label + '</option>';
    }).join('');

    main.innerHTML =
      '<div class="build">' +
      '<section class="panel library" aria-labelledby="lib-h">' +
      '<div class="row" style="margin-bottom:.6rem"><h2 id="lib-h" class="grow" style="margin:0">Exercise library</h2>' +
      '<button class="btn btn-sm" data-act="custom-new">+ Custom exercise</button></div>' +
      '<div class="lib-tools">' +
      '<div class="row"><input type="search" id="lib-q" class="grow" placeholder="Search exercises, e.g. “knee” or “band”" value="' + esc(filter.q) + '" aria-label="Search exercises" style="flex:1 1 220px">' +
      '<select id="lib-type" aria-label="Exercise type" style="width:auto;flex:0 0 auto">' + types + '</select></div>' +
      '<div class="chips" role="group" aria-label="Body region">' + chips + '</div>' +
      '<div class="lib-count" id="lib-count"></div></div>' +
      '<div class="grid" id="lib-grid"></div></section>' +
      '<aside class="panel program" id="program" aria-labelledby="pg-h">' +
      '<div class="program-head"><div class="row"><h2 id="pg-h" class="grow" style="margin:0">Program</h2>' +
      '<button class="btn btn-sm btn-ghost" data-act="new">New program</button></div></div>' +
      '<div class="program-fields">' +
      '<label class="field"><span>Program title</span><input type="text" id="pg-title" value="' + esc(draft.title) + '"></label>' +
      '<div class="row" style="align-items:start"><label class="field" style="flex:1 1 150px"><span>Patient name (optional)</span>' +
      '<input type="text" id="pg-patient" value="' + esc(draft.patient) + '" placeholder="First name is enough"></label>' +
      '<label class="field" style="flex:0 1 150px"><span>Date</span><input type="date" id="pg-date" value="' + esc(draft.date) + '"></label></div>' +
      '<label class="field"><span>Notes for the patient</span><textarea id="pg-notes" rows="2" placeholder="e.g. Use ice for 10 minutes after exercising.">' + esc(draft.notes) + '</textarea></label>' +
      '</div>' +
      '<ol class="program-list" id="pg-list"></ol>' +
      '<div class="program-actions">' +
      '<button class="btn btn-primary" data-act="handout">Open patient handout</button>' +
      '<div class="row"><button class="btn" data-act="share">Share link / QR</button><button class="btn" data-act="save-tpl">Save as template</button></div>' +
      '</div></aside></div>';

    var bar = document.createElement('div');
    bar.className = 'mobile-bar no-print';
    bar.innerHTML = '<span class="grow" id="mb-count"></span><button class="btn btn-sm" data-act="goto-program">View program</button>' +
      '<button class="btn btn-sm btn-primary" data-act="handout">Handout</button>';
    document.body.appendChild(bar);
    document.body.classList.add('has-mobile-bar');

    $('#lib-q').addEventListener('input', function (e) { filter.q = e.target.value; renderLibrary(); });
    $('#lib-type').addEventListener('change', function (e) { filter.type = e.target.value; renderLibrary(); });
    ['title', 'patient', 'date', 'notes'].forEach(function (k) {
      $('#pg-' + k).addEventListener('input', function (e) { draft[k] = e.target.value; saveDraft(); });
    });
    renderLibrary();
    renderProgram();
  }

  function matches(ex) {
    if (filter.region !== 'all' && ex.region !== filter.region) return false;
    if (filter.type !== 'all' && ex.type !== filter.type) return false;
    var q = filter.q.trim().toLowerCase();
    if (!q) return true;
    var hay = [ex.name, ex.area, ex.summary, ex.position, regionLabel(ex.region), typeLabel(ex.type)]
      .concat(ex.equipment || []).join(' ').toLowerCase();
    return q.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
  }

  function isAdded(id) { return draft.items.some(function (i) { return i.id === id; }); }

  function cardHTML(ex) {
    var added = isAdded(ex.id);
    return '<article class="card' + (added ? ' added' : '') + '" tabindex="0" data-id="' + esc(ex.id) + '" aria-label="' + esc(ex.name) + '">' +
      '<div class="card-fig" data-hover>' + figHTML(ex) + '</div>' +
      '<div class="card-body"><div class="card-title">' + esc(ex.name) + '</div>' +
      '<div class="card-meta">' + esc(ex.area || '') + (ex.position ? ' · ' + esc(ex.position) : '') + '</div>' +
      '<div class="card-foot"><div class="badges"><span class="badge badge-region" data-r="' + esc(ex.region) + '">' + esc(regionLabel(ex.region, true)) + '</span>' +
      '<span class="badge">' + esc(typeLabel(ex.type)) + '</span>' + (ex.custom ? '<span class="badge badge-custom">Custom</span>' : '') + '</div>' +
      '<button class="btn btn-sm' + (added ? '' : ' btn-primary') + '" data-act="toggle" data-id="' + esc(ex.id) + '" aria-label="' + (added ? 'Remove ' : 'Add ') + esc(ex.name) + '">' +
      (added ? '✓ Added' : '+ Add') + '</button></div></div></article>';
  }

  function renderLibrary() {
    var grid = $('#lib-grid');
    if (!grid) return;
    $$('.chip[data-region]').forEach(function (c) { c.setAttribute('aria-pressed', String(c.dataset.region === filter.region)); });
    var all = allExercises(), list = all.filter(matches);
    grid.innerHTML = list.length ? list.map(cardHTML).join('') :
      '<div class="empty" style="grid-column:1/-1">No exercises match. Try another search, or add a custom exercise.</div>';
    $('#lib-count').textContent = 'Showing ' + list.length + ' of ' + all.length + ' exercises. Hover over a picture to see the movement, or click a card for full instructions.';
  }

  function itemHTML(it, i, n) {
    var ex = findEx(it.id);
    var name = ex ? ex.name : 'Missing exercise';
    function inp(f, label, max) {
      return '<label>' + label + '<input type="number" inputmode="numeric" min="0" max="' + max + '" data-f="' + f + '" value="' + (it[f] || '') + '" placeholder="–"></label>';
    }
    return '<li class="item" data-idx="' + i + '">' +
      '<div class="item-head"><span class="item-num">' + (i + 1) + '</span>' +
      '<div class="item-thumb">' + (ex ? figHTML(ex) : '') + '</div>' +
      '<div class="item-name">' + esc(name) + '</div>' +
      '<div class="item-tools">' +
      '<button class="btn btn-ghost btn-icon" data-act="up" aria-label="Move up"' + (i === 0 ? ' disabled' : '') + '>' + ICON.up + '</button>' +
      '<button class="btn btn-ghost btn-icon" data-act="down" aria-label="Move down"' + (i === n - 1 ? ' disabled' : '') + '>' + ICON.down + '</button>' +
      '<button class="btn btn-ghost btn-icon btn-danger" data-act="remove" aria-label="Remove ' + esc(name) + '">' + ICON.x + '</button>' +
      '</div></div>' +
      '<div class="dose-grid">' + inp('sets', 'Sets', 20) + inp('reps', 'Reps', 200) + inp('hold', 'Hold (sec)', 600) + inp('perDay', 'Times/day', 24) + '</div>' +
      '<div class="item-extra"><label class="check"><input type="checkbox" data-f="sides"' + (it.sides ? ' checked' : '') + '> Each side</label>' +
      '<input type="text" data-f="note" value="' + esc(it.note || '') + '" placeholder="Note for this exercise (optional)" aria-label="Note for ' + esc(name) + '"></div>' +
      '</li>';
  }

  function renderProgram() {
    var list = $('#pg-list');
    if (!list) return;
    var n = draft.items.length;
    list.innerHTML = n ? draft.items.map(function (it, i) { return itemHTML(it, i, n); }).join('') :
      '<li class="empty">No exercises yet.<br>Click <strong>+ Add</strong> on any exercise in the library, or start from a <a href="#templates">template</a>.</li>';
    $$('[data-act="handout"], [data-act="share"], [data-act="save-tpl"]').forEach(function (b) { b.disabled = !n; });
    var mb = $('#mb-count');
    if (mb) mb.textContent = 'Program: ' + n + (n === 1 ? ' exercise' : ' exercises');
  }

  function addItem(id) {
    var ex = findEx(id);
    if (!ex || isAdded(id)) return;
    var d = ex.dose || {};
    draft.items.push({ id: id, sets: d.sets || 1, reps: d.reps || 0, hold: d.hold || 0, perDay: d.perDay || 1, sides: !!d.sides, note: '' });
    saveDraft();
  }
  function removeItem(id) {
    draft.items = draft.items.filter(function (i) { return i.id !== id; });
    saveDraft();
  }
  function toggleItem(id) {
    var adding = !isAdded(id);
    if (adding) addItem(id); else removeItem(id);
    refreshCard(id);
    renderProgram();
    var ex = findEx(id);
    toast((adding ? 'Added: ' : 'Removed: ') + (ex ? ex.name : ''));
  }
  function refreshCard(id) {
    var card = $('.card[data-id="' + CSS.escape(id) + '"]');
    if (card) {
      var ex = findEx(id);
      var tmp = document.createElement('div');
      tmp.innerHTML = cardHTML(ex);
      card.replaceWith(tmp.firstChild);
    }
  }

  /* ---------- exercise details ---------- */

  function detailBody(ex, dose) {
    var parts = doseParts(dose || ex.dose || {});
    return '<div class="detail"><div>' +
      '<div class="detail-fig" data-anim>' + figHTML(ex) + '</div>' +
      (hasPicture(ex) && reduceMotion ? framesHTML(ex).replace('class="frames"', 'class="frames" style="display:flex;margin-top:.5rem"') : '') +
      '</div><div>' +
      '<div class="badges" style="margin-bottom:.5rem"><span class="badge badge-region" data-r="' + esc(ex.region) + '">' + esc(regionLabel(ex.region)) + '</span>' +
      '<span class="badge">' + esc(typeLabel(ex.type)) + '</span>' + (ex.custom ? '<span class="badge badge-custom">Custom</span>' : '') + '</div>' +
      (ex.summary ? '<p>' + esc(ex.summary) + '</p>' : '') +
      (parts.length ? '<p class="dose-line">' + esc(parts.join(' · ')) + '</p>' : '') +
      '<p class="small muted">' + [ex.position ? 'Position: ' + esc(ex.position) : '', (ex.equipment || []).length ? 'Equipment: ' + esc(ex.equipment.join(', ')) : ''].filter(Boolean).join('<br>') + '</p>' +
      '</div></div>' +
      '<h3 style="margin-top:1rem">How to do it</h3><ol class="steps">' + (ex.steps || []).map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol>' +
      ((ex.tips || []).length ? '<div class="callout callout-tip"><strong>Tips:</strong> ' + ex.tips.map(esc).join(' ') + '</div>' : '') +
      (ex.caution ? '<div class="callout callout-warn"><strong>Take care:</strong> ' + esc(ex.caution) + '</div>' : '');
  }

  function showDetail(id) {
    var ex = findEx(id);
    if (!ex) return;
    var added = isAdded(id);
    openModal({
      title: esc(ex.name),
      body: detailBody(ex),
      foot: (ex.custom ? '<button class="btn btn-danger" data-do="delete">Delete</button><button class="btn" data-do="edit">Edit</button><span class="grow"></span>' : '') +
        '<button class="btn" data-close>Close</button>' +
        '<button class="btn ' + (added ? '' : 'btn-primary') + '" data-do="toggle">' + (added ? 'Remove from program' : '+ Add to program') + '</button>',
      onMount: function (m) {
        var f = m.querySelector('[data-anim]');
        if (f) animate(f, ex);
        m.querySelector('.modal-foot').addEventListener('click', function (e) {
          var b = e.target.closest('[data-do]');
          if (!b) return;
          if (b.dataset.do === 'toggle') { closeModal(); toggleItem(id); }
          if (b.dataset.do === 'edit') { closeModal(); customForm(ex); }
          if (b.dataset.do === 'delete') {
            confirmModal('Delete the custom exercise “' + esc(ex.name) + '”? It will also be removed from the current program.', 'Delete', true).then(function (ok) {
              if (!ok) return;
              custom = custom.filter(function (c) { return c.id !== id; });
              store.set('custom', custom);
              removeItem(id);
              renderLibrary(); renderProgram();
              toast('Custom exercise deleted');
            });
          }
        });
      }
    });
  }

  /* ---------- custom exercise form ---------- */

  function customForm(ex) {
    var e = ex || { region: filter.region !== 'all' ? filter.region : 'neck', type: 'stretch', dose: { sets: 1, reps: 10, hold: 0, perDay: 2 } };
    var d = e.dose || {};
    var regionOpts = D.regions.map(function (r) { return '<option value="' + r.id + '"' + (e.region === r.id ? ' selected' : '') + '>' + r.label + '</option>'; }).join('');
    var typeOpts = D.types.map(function (t) { return '<option value="' + t.id + '"' + (e.type === t.id ? ' selected' : '') + '>' + t.label + '</option>'; }).join('');
    function n(f, label) { return '<label class="field"><span>' + label + '</span><input type="number" min="0" name="' + f + '" value="' + (d[f] || '') + '"></label>'; }
    openModal({
      title: ex ? 'Edit custom exercise' : 'New custom exercise',
      body: '<p class="small muted">Custom exercises are shown with written instructions only, no drawing. They are saved in this browser and included in any patient link that uses them.</p>' +
        '<form id="cx-form" class="form-grid" novalidate>' +
        '<label class="field full"><span>Exercise name *</span><input type="text" name="name" required value="' + esc(e.name || '') + '" autofocus></label>' +
        '<label class="field"><span>Body region</span><select name="region">' + regionOpts + '</select></label>' +
        '<label class="field"><span>Type</span><select name="type">' + typeOpts + '</select></label>' +
        '<label class="field"><span>Position</span><input type="text" name="position" value="' + esc(e.position || '') + '" placeholder="e.g. Sitting"></label>' +
        '<label class="field"><span>Equipment</span><input type="text" name="equipment" value="' + esc((e.equipment || []).join(', ')) + '" placeholder="e.g. Towel, band"></label>' +
        '<label class="field full"><span>Short description</span><input type="text" name="summary" value="' + esc(e.summary || '') + '"></label>' +
        '<label class="field full"><span>Steps * (one step per line)</span><textarea name="steps" rows="5" required>' + esc((e.steps || []).join('\n')) + '</textarea></label>' +
        '<label class="field full"><span>Tips (optional)</span><input type="text" name="tips" value="' + esc((e.tips || []).join(' ')) + '"></label>' +
        '<label class="field full"><span>Take care / when to stop (optional)</span><input type="text" name="caution" value="' + esc(e.caution || '') + '"></label>' +
        '<div class="full"><div class="dose-row">' + n('sets', 'Sets') + n('reps', 'Reps') + n('hold', 'Hold (sec)') + n('perDay', 'Times/day') +
        '<label class="field check" style="margin-bottom:1.3rem"><input type="checkbox" name="sides"' + (d.sides ? ' checked' : '') + '> Each side</label></div></div>' +
        '</form><p class="small" id="cx-err" style="color:var(--danger)"></p>',
      foot: '<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-save>Save exercise</button>',
      onMount: function (m) {
        m.querySelector('[data-save]').addEventListener('click', function () {
          var f = m.querySelector('#cx-form');
          var name = f.name.value.trim();
          var steps = f.steps.value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
          if (!name || !steps.length) { m.querySelector('#cx-err').textContent = 'Please enter a name and at least one step.'; return; }
          var obj = {
            id: ex ? ex.id : uid('c-'), custom: true, name: name, region: f.region.value, type: f.type.value,
            area: '', position: f.position.value.trim(),
            equipment: f.equipment.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean),
            summary: f.summary.value.trim(), steps: steps,
            tips: f.tips.value.trim() ? [f.tips.value.trim()] : [], caution: f.caution.value.trim(),
            dose: { sets: num(f.sets.value, 0, 20), reps: num(f.reps.value, 0, 200), hold: num(f.hold.value, 0, 600), perDay: num(f.perDay.value, 0, 24), sides: f.sides.checked },
            fig: null
          };
          if (ex) custom = custom.map(function (c) { return c.id === ex.id ? obj : c; });
          else custom.push(obj);
          store.set('custom', custom);
          closeModal();
          renderLibrary(); renderProgram();
          toast(ex ? 'Exercise updated' : 'Custom exercise saved. Add it to the program from the library.');
        });
      }
    });
  }

  /* ---------- handout / share / templates from builder ---------- */

  function openHandout() {
    if (!draft.items.length) return;
    var w = window.open('', '_blank');
    encodeProgram(buildPayload()).then(function (code) {
      var url = linkFor(code);
      if (w) w.location.href = url; else location.href = url;
    });
  }

  function shareProgram() {
    if (!draft.items.length) return;
    encodeProgram(buildPayload()).then(function (code) {
      var url = linkFor(code);
      var phoneOk = canPhoneOpen();
      var note = phoneOk ? '' :
        '<div class="callout callout-warn">This link only works on <strong>this computer</strong>, because the app is running at <code>' + esc(location.host || 'a local file') + '</code>. ' +
        'To send links to patients’ phones, open the app through the network address shown in the server window (same Wi-Fi only), or put it online. See <em>Client_readme_file.md</em>. ' +
        'You can always print the handout instead.</div>';
      var subject = encodeURIComponent((draft.title || 'Your home exercise program'));
      var body = encodeURIComponent('Hello' + (draft.patient ? ' ' + draft.patient : '') + ',\n\nHere is your home exercise program:\n' + url + '\n\n' + (settings.therapist ? settings.therapist : ''));
      openModal({
        title: 'Share with your patient',
        body: note +
          '<p class="small muted">The whole program is stored inside this link. Nothing is uploaded, and the patient’s name stays in the link only.</p>' +
          '<div class="share-link" id="share-url">' + esc(url) + '</div>' +
          '<div class="row" style="margin:.75rem 0"><button class="btn btn-primary" data-copy>Copy link</button>' +
          '<a class="btn" href="mailto:?subject=' + subject + '&body=' + body + '">Email link</a>' +
          '<a class="btn" href="' + esc(url) + '" target="_blank" rel="noopener">Open handout</a></div>' +
          '<div class="qr" id="share-qr">' + (phoneOk ? '<span class="small muted">Making QR code…</span>' : '') + '</div>',
        foot: '<button class="btn" data-close>Done</button>',
        onMount: function (m) {
          m.querySelector('[data-copy]').addEventListener('click', function () {
            copyText(url).then(function () { toast('Link copied'); });
          });
          if (phoneOk) {
            qrSVG(url).then(function (svg) {
              var q = m.querySelector('#share-qr');
              if (q) q.innerHTML = svg + '<span class="small muted">Patient scans this with their phone camera.</span>';
            }).catch(function () {
              var q = m.querySelector('#share-qr');
              if (q) q.innerHTML = '<span class="small muted">QR code unavailable (no internet connection, or the program is too long). The link still works.</span>';
            });
          }
        }
      });
    });
  }

  function copyText(t) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t);
    return new Promise(function (resolve) {
      var ta = document.createElement('textarea');
      ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch (e) { /* ignore */ }
      ta.remove(); resolve();
    });
  }

  function saveTemplateDialog() {
    if (!draft.items.length) return;
    openModal({
      title: 'Save as template',
      body: '<p class="small muted">Saves the exercises, dosage, notes and title (not the patient’s name) so you can reuse this program.</p>' +
        '<label class="field"><span>Template name</span><input type="text" id="tpl-name" value="' + esc(draft.title) + '" autofocus></label>',
      foot: '<button class="btn" data-close>Cancel</button><button class="btn btn-primary" data-save>Save template</button>',
      onMount: function (m) {
        function save() {
          var name = m.querySelector('#tpl-name').value.trim() || draft.title || 'Untitled template';
          var existing = templates.filter(function (t) { return t.name.toLowerCase() === name.toLowerCase(); })[0];
          var tpl = { id: existing ? existing.id : uid('t-'), name: name, title: draft.title, notes: draft.notes,
            items: JSON.parse(JSON.stringify(draft.items)), updated: today() };
          templates = existing ? templates.map(function (t) { return t.id === existing.id ? tpl : t; }) : templates.concat(tpl);
          store.set('templates', templates);
          closeModal();
          toast(existing ? 'Template updated: ' + name : 'Template saved: ' + name);
        }
        m.querySelector('[data-save]').addEventListener('click', save);
        m.querySelector('#tpl-name').addEventListener('keydown', function (e) { if (e.key === 'Enter') save(); });
      }
    });
  }

  function newProgram() {
    var go = function () { draft = newDraft(); saveDraft(); renderBuild(); toast('Started a new program'); };
    if (!draft.items.length && !draft.patient && !draft.notes) return go();
    confirmModal('Start a new program? The current one will be cleared. Save it as a template first if you want to reuse it.', 'Start new', true)
      .then(function (ok) { if (ok) go(); });
  }

  /* ---------- templates view ---------- */

  var STARTERS = [
    { id: 's-neck', name: 'Neck & posture basics', title: 'Neck and posture exercises', notes: 'Move slowly and stay within a comfortable range.',
      items: ['neck-chin-tuck', 'neck-rotation', 'neck-side-bend', 'neck-levator-stretch', 'sh-scap-squeeze'] },
    { id: 's-back', name: 'Low back – gentle start', title: 'Low back exercises', notes: 'Keep moving through the day and avoid long periods of sitting.',
      items: ['back-pelvic-tilt', 'back-knee-to-chest', 'back-trunk-rotation', 'back-cat-camel', 'back-bridge'] },
    { id: 's-shoulder', name: 'Shoulder – early mobility', title: 'Shoulder mobility exercises', notes: '',
      items: ['sh-pendulum', 'sh-supine-flexion-stick', 'sh-wall-walk', 'sh-scap-squeeze', 'sh-cross-body'] },
    { id: 's-rotcuff', name: 'Shoulder – rotator cuff strength', title: 'Shoulder strengthening', notes: 'Use a light band. The last few repetitions should feel like work, not pain.',
      items: ['sh-er-band', 'sh-ir-band', 'sh-row-band', 'sh-abduction', 'sh-scap-squeeze'] },
    { id: 's-knee', name: 'Knee – after surgery (early)', title: 'Knee exercises', notes: 'Ice and elevate your leg after exercising if your knee is swollen.',
      items: ['leg-ankle-pumps', 'leg-quad-sets', 'leg-heel-slides', 'leg-slr', 'leg-short-arc-quad', 'leg-seated-knee-ext'] },
    { id: 's-hand', name: 'Hand & wrist stiffness', title: 'Hand and wrist exercises', notes: 'Warm water before exercising can ease stiffness.',
      items: ['hand-tendon-glides', 'hand-fist', 'hand-wrist-flex-ext', 'hand-finger-spread', 'hand-thumb-opposition'] },
    { id: 's-balance', name: 'Balance & leg strength', title: 'Balance and leg strength', notes: 'Always have a sturdy counter or chair within reach.',
      items: ['leg-sit-to-stand', 'leg-calf-raise', 'leg-mini-squat', 'leg-single-leg-balance'] }
  ];

  function starterAsTemplate(s) {
    return {
      id: s.id, name: s.name, title: s.title, notes: s.notes, starter: true,
      items: s.items.map(function (id) {
        var ex = findEx(id), d = (ex && ex.dose) || {};
        return { id: id, sets: d.sets || 1, reps: d.reps || 0, hold: d.hold || 0, perDay: d.perDay || 1, sides: !!d.sides, note: '' };
      })
    };
  }

  function tplRow(t) {
    var names = t.items.map(function (i) { var ex = findEx(i.id); return ex ? ex.name : null; }).filter(Boolean);
    return '<div class="tpl" data-tpl="' + esc(t.id) + '"><div class="tpl-info"><div class="tpl-name">' + esc(t.name) + '</div>' +
      '<div class="small muted">' + names.length + ' exercises: ' + esc(names.join(', ')) + '</div>' +
      (t.updated ? '<div class="small muted">Saved ' + esc(fmtDate(t.updated)) + '</div>' : '') + '</div>' +
      '<div class="row"><button class="btn btn-sm btn-primary" data-act="tpl-use" data-id="' + esc(t.id) + '">Use</button>' +
      (t.starter ? '' : '<button class="btn btn-sm btn-danger" data-act="tpl-del" data-id="' + esc(t.id) + '">Delete</button>') + '</div></div>';
  }

  function renderTemplates() {
    $('#main').innerHTML = '<div class="page">' +
      '<section class="panel"><div class="row" style="margin-bottom:.5rem"><h2 class="grow" style="margin:0">My templates</h2>' +
      '<button class="btn btn-sm" data-act="export">Export backup</button>' +
      '<label class="btn btn-sm">Import backup<input type="file" id="import-file" accept="application/json,.json" hidden></label></div>' +
      '<p class="small muted">Templates, custom exercises and settings are saved in this browser only. Use <strong>Export backup</strong> regularly, and to move them to another computer.</p>' +
      (templates.length ? templates.map(tplRow).join('') : '<div class="empty">No saved templates yet. Build a program and click <strong>Save as template</strong>.</div>') +
      '</section>' +
      '<section class="panel"><h2>Starter templates</h2><p class="small muted">Ready-made starting points. Review and adjust the exercises and dosage for each patient.</p>' +
      STARTERS.map(function (s) { return tplRow(starterAsTemplate(s)); }).join('') + '</section></div>';
    $('#import-file').addEventListener('change', importBackup);
  }

  function useTemplate(id) {
    var t = templates.filter(function (x) { return x.id === id; })[0];
    if (!t) { var s = STARTERS.filter(function (x) { return x.id === id; })[0]; if (s) t = starterAsTemplate(s); }
    if (!t) return;
    var go = function () {
      var items = t.items.filter(function (i) { return findEx(i.id); });
      var missing = t.items.length - items.length;
      draft = { title: t.title || t.name, patient: '', notes: t.notes || '', date: today(), items: JSON.parse(JSON.stringify(items)) };
      saveDraft();
      location.hash = '#build';
      toast('Loaded “' + t.name + '”' + (missing ? '. ' + missing + ' exercise(s) no longer exist and were skipped.' : ''));
    };
    if (!draft.items.length) return go();
    confirmModal('Replace the current program with “' + esc(t.name) + '”?', 'Replace').then(function (ok) { if (ok) go(); });
  }

  function exportBackup() {
    var data = { app: 'home-exercise-programs', version: 1, exported: new Date().toISOString(), settings: settings, templates: templates, custom: custom };
    var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'exercise-programs-backup-' + today() + '.json';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    toast('Backup downloaded');
  }

  function importBackup(e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    file.text().then(function (txt) {
      var data = JSON.parse(txt);
      if (!data || data.app !== 'home-exercise-programs') throw new Error('bad file');
      (data.custom || []).forEach(function (c) {
        custom = custom.filter(function (x) { return x.id !== c.id; }).concat(c);
      });
      (data.templates || []).forEach(function (t) {
        templates = templates.filter(function (x) { return x.id !== t.id; }).concat(t);
      });
      if (data.settings) settings = Object.assign({}, DEFAULT_SETTINGS, data.settings);
      store.set('custom', custom); store.set('templates', templates); store.set('settings', settings);
      applyTheme();
      renderTopbar('templates');
      renderTemplates();
      toast('Backup imported: ' + (data.templates || []).length + ' templates, ' + (data.custom || []).length + ' custom exercises');
    }).catch(function () { toast('That file is not a valid backup'); });
  }

  /* ---------- settings view ---------- */

  function renderSettings() {
    function f(k, label, type, ph) {
      return '<label class="field"><span>' + label + '</span><input type="' + (type || 'text') + '" name="' + k + '" value="' + esc(settings[k]) + '" placeholder="' + esc(ph || '') + '"></label>';
    }
    $('#main').innerHTML = '<div class="page"><section class="panel"><h2>Clinic details</h2>' +
      '<p class="small muted">These appear at the top of every patient handout.</p>' +
      '<form id="set-form" class="form-grid">' +
      f('clinic', 'Clinic name', 'text', 'e.g. Riverside Physical Therapy') + f('therapist', 'Therapist name', 'text', 'e.g. Alex Morgan, PT') +
      f('phone', 'Phone', 'tel', '') + f('contact', 'Email or website', 'text', '') +
      '<label class="field full"><span>Safety note printed at the bottom of each handout</span><textarea name="footer" rows="4">' + esc(settings.footer) + '</textarea></label>' +
      '<label class="field"><span>Appearance</span><select name="theme">' +
      ['auto', 'light', 'dark'].map(function (t) { return '<option value="' + t + '"' + (settings.theme === t ? ' selected' : '') + '>' + { auto: 'Match device', light: 'Light', dark: 'Dark' }[t] + '</option>'; }).join('') +
      '</select></label></form>' +
      '<div class="row"><button class="btn btn-primary" data-act="settings-save">Save settings</button><button class="btn" data-act="footer-reset">Reset safety note</button></div>' +
      '</section>' +
      '<section class="panel"><h2>About this app</h2><p class="small muted">' + D.exercises.length + ' built-in exercises with drawings, plus ' + custom.length + ' custom exercise(s). ' +
      'All data stays in this browser. Exercise descriptions are general guidance. Review them and adjust them for each patient.</p></section></div>';
  }

  function saveSettings() {
    var f = $('#set-form');
    ['clinic', 'therapist', 'phone', 'contact', 'footer', 'theme'].forEach(function (k) { settings[k] = f[k].value.trim(); });
    if (!settings.footer) settings.footer = DEFAULT_FOOTER;
    store.set('settings', settings);
    applyTheme();
    renderTopbar('settings');
    toast('Settings saved');
  }

  /* ---------- patient view ---------- */

  function renderPatient(code) {
    renderTopbar('patient');
    var main = $('#main');
    main.innerHTML = '<div class="handout"><div class="panel ho-head"><p class="muted">Loading your program…</p></div></div>';
    decodeProgram(code).then(function (p) {
      var c = p.c || [];
      var clinic = c[0] || '', therapist = c[1] || '', phone = c[2] || '', contact = c[3] || '', footer = c[4] || DEFAULT_FOOTER;
      var items = (p.i || []).map(function (a) {
        return { ex: findEx(a[0], p.x || []), dose: { sets: a[1], reps: a[2], hold: a[3], perDay: a[4], sides: !!a[5] }, note: a[6] };
      }).filter(function (x) { return x.ex; });
      document.title = (p.t || 'Home exercise program') + (clinic ? ' – ' + clinic : '');
      renderTopbar('patient');
      if (clinic) $('#topbar .brand-text > div').textContent = clinic;

      var doneKey = 'done.' + hashStr(code) + '.' + today();
      var done = store.get(doneKey, []);
      var isEditor = store.get('isEditor', false);

      main.innerHTML = '<div class="handout">' +
        '<section class="panel ho-head">' +
        ((clinic || therapist || phone || contact) ?
          '<div class="ho-clinic"><div><strong>' + esc(clinic) + '</strong>' + (therapist ? '<div>' + esc(therapist) + '</div>' : '') + '</div>' +
          '<div style="text-align:right">' + (phone ? '<a href="tel:' + esc(phone.replace(/[^\d+]/g, '')) + '">' + esc(phone) + '</a>' : '') +
          (contact ? '<div>' + esc(contact) + '</div>' : '') + '</div></div>' : '') +
        '<h1>' + esc(p.t || 'Home exercise program') + '</h1>' +
        '<div class="muted">' + [p.n ? 'For ' + esc(p.n) : '', p.d ? esc(fmtDate(p.d)) : ''].filter(Boolean).join(' · ') + '</div>' +
        (p.o ? '<div class="ho-notes">' + esc(p.o) + '</div>' : '') +
        '<div class="progress"><div class="row"><strong class="grow">Today</strong><span id="prog-text"></span></div>' +
        '<div class="progress-bar"><div id="prog-bar"></div></div></div>' +
        '<div class="ho-tools"><button class="btn btn-primary" data-act="print">Print or save as PDF</button>' +
        (isEditor ? '<a class="btn" href="#build">Back to program builder</a>' : '') + '</div>' +
        '</section>' +
        items.map(function (it, i) { return patientExHTML(it, i, done.indexOf(i) >= 0); }).join('') +
        '<footer class="panel ho-foot"><p><strong>Safety:</strong> ' + esc(footer) + '</p>' +
        '<div class="ho-qr print-only" id="ho-qr"></div></footer></div>';

      function updateProgress() {
        var n = items.length, k = done.length;
        $('#prog-text').textContent = k + ' of ' + n + ' done';
        $('#prog-bar').style.width = (n ? Math.round(k / n * 100) : 0) + '%';
      }
      updateProgress();

      $$('.ho-ex').forEach(function (sec) {
        var i = +sec.dataset.i;
        var fig = sec.querySelector('[data-anim]');
        if (fig) {
          animate(fig, items[i].ex);
          fig.addEventListener('click', function () {
            fig._paused = !fig._paused;
            var hint = fig.querySelector('.play-hint');
            if (hint) hint.textContent = fig._paused ? 'Tap to play' : 'Tap to pause';
          });
        }
        var cb = sec.querySelector('input[type="checkbox"]');
        cb.addEventListener('change', function () {
          done = done.filter(function (x) { return x !== i; });
          if (cb.checked) done.push(i);
          store.set(doneKey, done);
          sec.classList.toggle('done', cb.checked);
          updateProgress();
        });
      });

      if (canPhoneOpen()) {
        qrSVG(location.href).then(function (svg) {
          var q = $('#ho-qr');
          if (q) q.innerHTML = svg + '<span class="small">Scan with your phone camera to open this program, with moving pictures.</span>';
        }).catch(function () { /* QR is optional */ });
      }
    }).catch(function () {
      main.innerHTML = '<div class="handout"><section class="panel ho-head"><h1>This link could not be opened</h1>' +
        '<p>The program link looks incomplete. Please ask your therapist to send it again.</p></section></div>';
    });
  }

  function patientExHTML(it, i, isDone) {
    var ex = it.ex, parts = doseParts(it.dose);
    var hasFig = hasPicture(ex);
    return '<section class="panel ho-ex' + (isDone ? ' done' : '') + '" data-i="' + i + '">' +
      '<div class="ho-ex-head"><span class="ho-num">' + (i + 1) + '.</span><h2>' + esc(ex.name) + '</h2>' +
      '<span class="badge badge-region" data-r="' + esc(ex.region) + '">' + esc(regionLabel(ex.region, true)) + '</span></div>' +
      '<div class="ho-grid"' + (hasFig ? '' : ' style="grid-template-columns:minmax(0,1fr)"') + '>' +
      (hasFig ? '<div><div class="ho-fig" data-anim role="button" tabindex="0" aria-label="Pause or play the animation">' + figHTML(ex) +
        (reduceMotion ? '' : '<span class="play-hint">Tap to pause</span>') + '</div>' + framesHTML(ex) + '</div>' : '') +
      '<div>' +
      (parts.length ? '<div class="dose-chips">' + parts.map(function (s) { return '<span class="dose-chip">' + esc(s) + '</span>'; }).join('') + '</div>' : '') +
      (ex.summary ? '<p class="muted">' + esc(ex.summary) + '</p>' : '') +
      '<ol class="steps">' + (ex.steps || []).map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol>' +
      (it.note ? '<div class="ho-note"><strong>Note from your therapist:</strong> ' + esc(it.note) + '</div>' : '') +
      ((ex.tips || []).length ? '<div class="callout callout-tip"><strong>Tip:</strong> ' + ex.tips.map(esc).join(' ') + '</div>' : '') +
      (ex.caution ? '<div class="callout callout-warn"><strong>Take care:</strong> ' + esc(ex.caution) + '</div>' : '') +
      '<label class="done-toggle"><input type="checkbox"' + (isDone ? ' checked' : '') + '> Done today</label>' +
      '</div></div></section>';
  }

  /* ---------- events ---------- */

  document.addEventListener('click', function (e) {
    var chip = e.target.closest('.chip[data-region]');
    if (chip) { filter.region = chip.dataset.region; renderLibrary(); return; }

    var b = e.target.closest('[data-act]');
    if (b && !b.disabled) {
      var act = b.dataset.act;
      var li = b.closest('.item');
      var idx = li ? +li.dataset.idx : -1;
      switch (act) {
        case 'toggle': e.stopPropagation(); toggleItem(b.dataset.id); return;
        case 'custom-new': customForm(null); return;
        case 'new': newProgram(); return;
        case 'handout': openHandout(); return;
        case 'share': shareProgram(); return;
        case 'save-tpl': saveTemplateDialog(); return;
        case 'goto-program': $('#program').scrollIntoView({ behavior: 'smooth' }); return;
        case 'up':
        case 'down': {
          var j = act === 'up' ? idx - 1 : idx + 1;
          if (j < 0 || j >= draft.items.length) return;
          var tmp = draft.items[idx]; draft.items[idx] = draft.items[j]; draft.items[j] = tmp;
          saveDraft(); renderProgram();
          var btn = $('.item[data-idx="' + j + '"] [data-act="' + act + '"]');
          if (btn && !btn.disabled) btn.focus();
          return;
        }
        case 'remove': {
          var id = draft.items[idx].id;
          removeItem(id); refreshCard(id); renderProgram(); return;
        }
        case 'tpl-use': useTemplate(b.dataset.id); return;
        case 'tpl-del': {
          var t = templates.filter(function (x) { return x.id === b.dataset.id; })[0];
          confirmModal('Delete the template “' + esc(t.name) + '”?', 'Delete', true).then(function (ok) {
            if (!ok) return;
            templates = templates.filter(function (x) { return x.id !== t.id; });
            store.set('templates', templates); renderTemplates(); toast('Template deleted');
          });
          return;
        }
        case 'export': exportBackup(); return;
        case 'settings-save': saveSettings(); return;
        case 'footer-reset': $('#set-form').footer.value = DEFAULT_FOOTER; return;
        case 'print': window.print(); return;
      }
    }

    var card = e.target.closest('.card[data-id]');
    if (card && !e.target.closest('button')) showDetail(card.dataset.id);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var card = e.target.closest && e.target.closest('.card[data-id]');
    if (card && e.target === card) { e.preventDefault(); showDetail(card.dataset.id); }
    var fig = e.target.closest && e.target.closest('.ho-fig');
    if (fig && e.target === fig) { e.preventDefault(); fig.click(); }
  });

  document.addEventListener('input', function (e) {
    var li = e.target.closest && e.target.closest('.item');
    if (!li || !e.target.dataset.f) return;
    var it = draft.items[+li.dataset.idx], f = e.target.dataset.f;
    if (f === 'note') it.note = e.target.value;
    else if (f === 'sides') it.sides = e.target.checked;
    else it[f] = num(e.target.value, 0, +e.target.max || 999);
    saveDraft();
  });
  document.addEventListener('change', function (e) {
    var li = e.target.closest && e.target.closest('.item');
    if (li && e.target.dataset.f === 'sides') { draft.items[+li.dataset.idx].sides = e.target.checked; saveDraft(); }
  });

  // Animate library cards while hovered.
  document.addEventListener('mouseover', function (e) {
    var f = e.target.closest && e.target.closest('.card-fig[data-hover]');
    if (!f || f._hovering) return;
    var card = f.closest('.card'), ex = findEx(card.dataset.id);
    if (!ex || !hasPicture(ex)) return;
    f._hovering = true;
    animate(f, ex);
    f.addEventListener('mouseleave', function leave() {
      f.removeEventListener('mouseleave', leave);
      f._hovering = false;
      stopAnim(f);
    });
  });

  window.addEventListener('hashchange', route);
  applyTheme();
  route();
})();
