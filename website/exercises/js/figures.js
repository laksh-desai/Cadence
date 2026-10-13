/*
 * Illustration renderer for exercises: a fully drawn older adult (about 62 years old,
 * silver hair, glasses, polo shirt, trousers, sneakers) built from rounded body shapes.
 *
 * A figure is { view, poses: [pose, pose, ...], props: [...], focus: [...] }.
 * Views:
 *   'side'  - body seen from the side, facing right (lying poses may face up/down)
 *   'front' - body seen from the front (also used rotated for side-lying / top views)
 *   'hand'  - forearm + hand seen from the thumb side, fingers curl downward
 *   'palm'  - palm facing the viewer, fingers up
 *   'forearm' - forearm and hand seen from above (rot: 0 = palm down, 180 = palm up)
 *
 * Angles are absolute, in degrees: 0 = pointing down, 90 = right, 180 = up, 270 = left.
 * Poses are interpolated numerically, so write angles continuously (use -20, not 340,
 * when a limb moves through 0).
 *
 * `focus` names body parts to outline in the accent colour (the area being worked):
 * legR/legL, thighR, shinR, footR, armR/armL, upperArmR, forearmR, torso, neck,
 * and for hand views: hand, wrist, fingers, thumb, forearm.
 */
(function (global) {
  'use strict';

  var L = { torso: 42, neck: 7, headR: 9, ua: 24, fa: 22, th: 34, sh: 33, ft: 11, shW: 12, hipW: 7 };
  var BODY_BOX = { w: 210, h: 158 };
  var HAND_BOX = { w: 130, h: 98 };
  var RAD = Math.PI / 180;
  var OLW = 1.1;   // outline width (each side)
  var LIGHT = [-0.45, -0.893]; // light comes from the upper left
  var HEAD_R = 9.2;

  // Body part thickness (radius) at each end.
  var W = {
    thigh: [6.6, 5.0], shin: [4.9, 3.5], shoe: [3.7, 3.0],
    upperArm: [4.4, 3.7], sleeve: [5.2, 4.8], forearm: [3.6, 2.8], hand: [3.0, 2.6],
    neck: [3.9, 3.7], pelvis: 8.6, chest: 8.8
  };
  // Radii used to rest the body on the floor.
  var GROUND_R = {
    pelvis: 8.6, chest: 9, shR: 5, shL: 5, elR: 3.8, elL: 3.8, haR: 3, haL: 3, hdR: 2.6, hdL: 2.6,
    knR: 5, knL: 5, anR: 3.6, anL: 3.6, toR: 3, toL: 3, heR: 3.7, heL: 3.7, head: HEAD_R
  };

  function dir(a) { return [Math.sin(a * RAD), Math.cos(a * RAD)]; }
  function step(p, a, len) { var d = dir(a); return [p[0] + d[0] * len, p[1] + d[1] * len]; }
  function opt(v, d) { return v == null ? d : v; }
  function r1(n) { return Math.round(n * 10) / 10; }
  function add(p, v, k) { return [p[0] + v[0] * k, p[1] + v[1] * k]; }
  function mix(a, b, u) { return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]; }
  function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]); }
  function unit(a, b, fallbackAngle) {
    var d = dist(a, b);
    return d > 0.01 ? [(b[0] - a[0]) / d, (b[1] - a[1]) / d] : dir(fallbackAngle || 0);
  }
  // Point at distance `len` from a, in the direction of b (negative goes backwards).
  function along(a, b, len, fallbackAngle) { return add(a, unit(a, b, fallbackAngle), len); }

  /* ---------- base poses ---------- */

  var P = {
    standSide: { view: 'side', torso: 180, neck: 180, armR: [0, 0], armL: [0, 0], legR: [0, 0, 90], legL: [0, 0, 90] },
    sitSide: { view: 'side', torso: 180, neck: 180, armR: [15, 60], armL: [15, 60], legR: [90, 0, 90], legL: [90, 0, 90] },
    standFront: { view: 'front', torso: 180, neck: 180, armR: [8, 4], armL: [-8, -4], legR: [3, 0, 90], legL: [-3, 0, -90] },
    sitFront: { view: 'front', torso: 180, neck: 180, armR: [6, -22], armL: [-6, 22], legR: [8, 0, 90, 0.18], legL: [-8, 0, -90, 0.18] },
    supine: { view: 'side', torso: 270, neck: 262, armR: [90, 90], armL: [90, 90], legR: [90, 90, 180], legL: [90, 90, 180] },
    hook: { view: 'side', torso: 270, neck: 262, armR: [90, 90], armL: [90, 90], legR: [150, 15, 90], legL: [150, 15, 90] },
    prone: { view: 'side', torso: 90, neck: 100, armR: [160, 11], armL: [160, 11], legR: [270, 270, 270], legL: [270, 270, 270] },
    quad: { view: 'side', torso: 106, neck: 100, armR: [0, 0], armL: [0, 0], legR: [0, 270, 270], legL: [0, 270, 270] },
    sideLying: { view: 'front', torso: 270, neck: 262, armR: [100, 100], armL: [200, 190], legR: [90, 90, 180], legL: [90, 90, 180] }
  };

  function pose(base, over) {
    var b = typeof base === 'string' ? P[base] : base;
    var o = {}, k;
    for (k in b) o[k] = b[k];
    for (k in over || {}) o[k] = over[k];
    return o;
  }

  /* ---------- interpolation ---------- */

  function lerp(a, b, u) {
    if (typeof a === 'number' && typeof b === 'number') return a + (b - a) * u;
    if (Array.isArray(a) && Array.isArray(b)) {
      var out = [];
      for (var i = 0; i < Math.max(a.length, b.length); i++) {
        out.push(a[i] == null ? b[i] : b[i] == null ? a[i] : lerp(a[i], b[i], u));
      }
      return out;
    }
    if (a && b && typeof a === 'object') {
      var o = {}, k;
      for (k in a) o[k] = k in b ? lerp(a[k], b[k], u) : a[k];
      for (k in b) if (!(k in a)) o[k] = b[k];
      return o;
    }
    if (a == null) return b;
    if (b == null) return a;
    return u < 0.5 ? a : b;
  }

  var ONE_KEYS = ['tScale', 'nScale', 'hScale'];
  var ZERO_KEYS = ['x', 'y', 'arch', 'turn', 'wrist', 'mcp', 'pip', 'dip', 'thumb', 'spread', 'bend', 'dev'];

  // Fill optional values so interpolation never jumps between a missing and a set value.
  function normalize(p) {
    var o = {}, k;
    for (k in p) o[k] = p[k];
    ZERO_KEYS.forEach(function (key) { if (o[key] == null) o[key] = 0; });
    if (o.torso != null) {
      ONE_KEYS.forEach(function (key) { if (o[key] == null) o[key] = 1; });
      if (o.neck == null) o.neck = o.torso;
      if (o.face == null) o.face = o.neck - 90;
    }
    return o;
  }

  function poseAt(fig, t) {
    var ps = fig.poses, n = ps.length;
    if (n === 1) return ps[0];
    t = Math.max(0, Math.min(n - 1, t));
    var i = Math.min(n - 2, Math.floor(t));
    return lerp(normalize(ps[i]), normalize(ps[i + 1]), t - i);
  }

  /* ---------- solvers ---------- */

  function solveBody(p, grounded) {
    var front = p.view === 'front';
    var J = {};
    var tor = p.torso;
    var nk = opt(p.neck, tor);
    J.pelvis = [opt(p.x, 0), opt(p.y, 0)];
    J.chest = step(J.pelvis, tor, L.torso * opt(p.tScale, 1));
    var perp = tor - 90;
    var sw = front ? L.shW : 0, hw = front ? L.hipW : 0;
    J.shR = step(J.chest, perp, sw);
    J.shL = step(J.chest, perp + 180, sw);
    J.hipR = step(J.pelvis, perp, hw);
    J.hipL = step(J.pelvis, perp + 180, hw);
    J.neckTop = step(J.chest, nk, L.neck * opt(p.nScale, 1));
    J.head = step(J.neckTop, nk, L.headR * opt(p.hScale, 1));
    ['R', 'L'].forEach(function (s) {
      var a = p['arm' + s] || [0, 0];
      J['el' + s] = step(J['sh' + s], a[0], L.ua * opt(a[2], 1));
      J['ha' + s] = step(J['el' + s], a[1], L.fa * opt(a[3], 1));
      J['hd' + s] = step(J['ha' + s], a[1], 6);
      var g = p['leg' + s] || [0, 0, 90];
      J['kn' + s] = step(J['hip' + s], g[0], L.th * opt(g[3], 1));
      J['an' + s] = step(J['kn' + s], g[1], L.sh * opt(g[4], 1));
      J['to' + s] = step(J['an' + s], g[2], L.ft * (front ? 0.55 : 1));
      J['he' + s] = step(J['an' + s], g[2], front ? 0 : -2.6);
    });
    if (grounded) {
      var maxY = -Infinity;
      for (var k in GROUND_R) if (J[k] && J[k][1] + GROUND_R[k] > maxY) maxY = J[k][1] + GROUND_R[k];
      var dy = -maxY - OLW;
      for (var j in J) J[j] = [J[j][0], J[j][1] + dy];
    }
    J._ = { front: front, tor: tor, nk: nk, perp: perp, face: opt(p.face, nk - 90), turn: p.turn || 0, arch: p.arch || 0 };
    return J;
  }

  function solveHand(p) {
    var J = {};
    J.elbow = [-50, 0];
    J.wrist = [0, 0];
    var pa = 90 - (p.wrist || 0);
    J.knuck = step(J.wrist, pa, 25);
    var a1 = pa - (p.mcp || 0), a2 = a1 - (p.pip || 0), a3 = a2 - (p.dip || 0);
    J.f1 = step(J.knuck, a1, 15);
    J.f2 = step(J.f1, a2, 10);
    J.f3 = step(J.f2, a3, 8);
    var th = p.thumb || 0;
    J.tb = step(J.wrist, pa, 7);
    var ta = pa - 30 - th * 45;
    J.t1 = step(J.tb, ta, 13);
    J.t2 = step(J.t1, ta - th * 50, 10);
    J._ = { pa: pa, a1: a1 };
    return J;
  }

  function solvePalm(p) {
    var J = {};
    var spread = p.spread || 0, bend = p.bend || 0, th = p.thumb || 0;
    J.wrist = [0, 0];
    J.forearm = [0, 40];
    var xs = [-10.5, -3.5, 3.5, 10.5], lens = [19, 25, 28, 25], sp = [1.5, 0.5, -0.5, -1.5];
    for (var i = 0; i < 4; i++) {
      var base = [xs[i], -31];
      J['fb' + i] = base;
      J['ft' + i] = step(base, 180 + sp[i] * spread, lens[i] * (1 - bend * 0.62));
    }
    J.tb = [12, -6];
    var ta = 128 + th * 95;
    J.t1 = step(J.tb, ta, 14);
    J.t2 = step(J.t1, ta + th * 25, 11);
    J._ = { dev: p.dev || 0 };
    return J;
  }

  function solveForearm(p) {
    return { elbow: [-55, 0], wrist: [0, 0], _: { rot: p.rot || 0 } };
  }

  function solve(fig, p) {
    var v = p.view || fig.view;
    if (v === 'forearm') return solveForearm(p);
    if (v === 'hand') return solveHand(p);
    if (v === 'palm') return solvePalm(p);
    return solveBody(p, fig.floor !== false);
  }

  /* ---------- painter ---------- */

  function Box() { this.x0 = Infinity; this.y0 = Infinity; this.x1 = -Infinity; this.y1 = -Infinity; }
  Box.prototype.add = function (pt, r) {
    r = (r || 0) + OLW;
    if (pt[0] - r < this.x0) this.x0 = pt[0] - r;
    if (pt[0] + r > this.x1) this.x1 = pt[0] + r;
    if (pt[1] - r < this.y0) this.y0 = pt[1] - r;
    if (pt[1] + r > this.y1) this.y1 = pt[1] + r;
  };

  function capsuleD(a, b, ra, rb) {
    var len = dist(a, b);
    if (len < 0.05) return circleD(a, Math.max(ra, rb));
    var nx = -(b[1] - a[1]) / len, ny = (b[0] - a[0]) / len;
    return 'M' + r1(a[0] + nx * ra) + ' ' + r1(a[1] + ny * ra) +
      'L' + r1(b[0] + nx * rb) + ' ' + r1(b[1] + ny * rb) +
      'A' + r1(rb) + ' ' + r1(rb) + ' 0 0 0 ' + r1(b[0] - nx * rb) + ' ' + r1(b[1] - ny * rb) +
      'L' + r1(a[0] - nx * ra) + ' ' + r1(a[1] - ny * ra) +
      'A' + r1(ra) + ' ' + r1(ra) + ' 0 0 0 ' + r1(a[0] + nx * ra) + ' ' + r1(a[1] + ny * ra) + 'Z';
  }
  function circleD(c, r) {
    return 'M' + r1(c[0] - r) + ' ' + r1(c[1]) + 'a' + r1(r) + ' ' + r1(r) + ' 0 1 0 ' + r1(2 * r) + ' 0' +
      'a' + r1(r) + ' ' + r1(r) + ' 0 1 0 ' + r1(-2 * r) + ' 0Z';
  }
  function polyD(pts) {
    return 'M' + pts.map(function (p) { return r1(p[0]) + ' ' + r1(p[1]); }).join('L') + 'Z';
  }

  // A group is drawn as: all outlines first, then all fills (each with a shading overlay).
  // Overlapping shapes in the same group therefore merge into one outlined silhouette.
  function Group(painter, cls) { this.p = painter; this.cls = cls || ''; this.shapes = []; }
  Group.prototype.shape = function (d, fill, focus, round, geo) {
    this.shapes.push({ d: d, fill: fill, focus: !!focus, round: round || 0, geo: geo });
    return this;
  };
  Group.prototype.cap = function (a, b, ra, rb, fill, focus) {
    this.p.box.add(a, ra); this.p.box.add(b, rb);
    return this.shape(capsuleD(a, b, ra, rb), fill, focus, 0, { k: 'cap', a: a, b: b, ra: ra, rb: rb });
  };
  Group.prototype.circle = function (c, r, fill, focus) {
    this.p.box.add(c, r);
    return this.shape(circleD(c, r), fill, focus, 0, { k: 'circle', c: c, r: r });
  };
  Group.prototype.poly = function (pts, fill, focus, round) {
    var self = this;
    pts.forEach(function (q) { self.p.box.add(q, (round || 0) / 2); });
    return this.shape(polyD(pts), fill, focus, round, { k: 'poly', pts: pts, round: round || 0 });
  };
  Group.prototype.end = function () {
    var ol = '', fl = '', p = this.p;
    this.shapes.forEach(function (s) {
      var w = s.round + OLW * 2 + (s.focus ? 1.8 : 0);
      ol += '<path d="' + s.d + '" class="o o-' + s.fill.replace('c-', '') + (s.focus ? ' of' : '') + '" style="stroke-width:' + r1(w) + '"/>';
      fl += '<path d="' + s.d + '" class="' + s.fill + '"' + (s.round ? ' style="stroke-width:' + s.round + '"' : '') + '/>';
      var g = p.shade(s.geo);
      if (g) fl += '<path d="' + s.d + '" fill="url(#' + g + ')" class="shade"' + (s.round ? ' style="stroke:url(#' + g + ');stroke-width:' + s.round + '"' : '') + '/>';
    });
    p.out.push('<g' + (this.cls ? ' class="' + this.cls + '"' : '') + '>' + ol + fl + '</g>');
  };

  var renderCount = 0;
  function Painter(box) { this.out = []; this.defs = []; this.box = box; this.uid = 'h' + (++renderCount).toString(36); this.n = 0; }
  var STOPS_LIN = '<stop offset="0" stop-color="#fff" stop-opacity=".30"/><stop offset=".32" stop-color="#fff" stop-opacity=".07"/>' +
    '<stop offset=".58" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".27"/>';
  var STOPS_RAD = '<stop offset="0" stop-color="#fff" stop-opacity=".32"/><stop offset=".42" stop-color="#fff" stop-opacity="0"/>' +
    '<stop offset=".72" stop-color="#000" stop-opacity=".05"/><stop offset="1" stop-color="#000" stop-opacity=".26"/>';
  // Light-to-shadow gradient across a shape, so limbs look round.
  Painter.prototype.shade = function (geo) {
    if (!geo) return null;
    var id = this.uid + '_' + (this.n++);
    if (geo.k === 'circle' || (geo.k === 'cap' && dist(geo.a, geo.b) < 0.5)) {
      var c = geo.c || geo.a, r = geo.r || Math.max(geo.ra, geo.rb);
      var hc = add(c, LIGHT, r * 0.45);
      this.defs.push('<radialGradient id="' + id + '" gradientUnits="userSpaceOnUse" cx="' + r1(hc[0]) + '" cy="' + r1(hc[1]) + '" r="' + r1(r * 1.45) + '">' + STOPS_RAD + '</radialGradient>');
      return id;
    }
    var center, n, R;
    if (geo.k === 'cap') {
      center = mix(geo.a, geo.b, 0.5);
      var d = unit(geo.a, geo.b);
      n = [-d[1], d[0]];
      if (n[0] * LIGHT[0] + n[1] * LIGHT[1] < 0) n = [-n[0], -n[1]];
      R = (geo.ra + geo.rb) / 2;
    } else {
      center = [0, 0];
      geo.pts.forEach(function (q) { center[0] += q[0] / geo.pts.length; center[1] += q[1] / geo.pts.length; });
      n = LIGHT; R = 1;
      geo.pts.forEach(function (q) { R = Math.max(R, Math.abs((q[0] - center[0]) * n[0] + (q[1] - center[1]) * n[1])); });
      R += geo.round / 2;
    }
    var p1 = add(center, n, R), p2 = add(center, n, -R);
    this.defs.push('<linearGradient id="' + id + '" gradientUnits="userSpaceOnUse" x1="' + r1(p1[0]) + '" y1="' + r1(p1[1]) + '" x2="' + r1(p2[0]) + '" y2="' + r1(p2[1]) + '">' + STOPS_LIN + '</linearGradient>');
    return id;
  };
  Painter.prototype.group = function (cls) { return new Group(this, cls); };
  Painter.prototype.raw = function (s) { this.out.push(s); };
  Painter.prototype.line = function (a, b, cls, w) {
    this.box.add(a, w / 2); this.box.add(b, w / 2);
    this.out.push('<line x1="' + r1(a[0]) + '" y1="' + r1(a[1]) + '" x2="' + r1(b[0]) + '" y2="' + r1(b[1]) + '" class="' + cls + '" style="stroke-width:' + w + '"/>');
  };
  Painter.prototype.dot = function (c, r, cls) {
    this.out.push('<circle cx="' + r1(c[0]) + '" cy="' + r1(c[1]) + '" r="' + r1(r) + '" class="' + cls + '"/>');
  };
  Painter.prototype.path = function (d, cls, w) {
    this.out.push('<path d="' + d + '" class="' + cls + '"' + (w ? ' style="stroke-width:' + w + '"' : '') + '/>');
  };

  /* ---------- the person ---------- */

  function has(focus, names) {
    for (var i = 0; i < names.length; i++) if (focus.indexOf(names[i]) >= 0) return true;
    return false;
  }

  function drawLeg(pt, J, s, far, focus) {
    var g = pt.group(far ? 'far' : '');
    var all = has(focus, ['leg' + s]);
    g.cap(J['hip' + s], J['kn' + s], W.thigh[0], W.thigh[1], 'c-pants', all || has(focus, ['thigh' + s]));
    g.cap(J['kn' + s], J['an' + s], W.shin[0], W.shin[1], 'c-pants', all || has(focus, ['shin' + s]));
    g.cap(J['he' + s], J['to' + s], W.shoe[0], W.shoe[1], 'c-shoe', all || has(focus, ['foot' + s]));
    // sole: on the side of the shoe facing away from the knee
    var sd = unit(J['he' + s], J['to' + s], 90), sn = [-sd[1], sd[0]];
    var shin = unit(J['kn' + s], J['an' + s]);
    if (sn[0] * shin[0] + sn[1] * shin[1] < 0) sn = [-sn[0], -sn[1]];
    if (dist(J['he' + s], J['to' + s]) > 3) {
      g.cap(add(J['he' + s], sn, W.shoe[0] - 1.1), add(J['to' + s], sn, W.shoe[1] - 1.1), 1.3, 1.1, 'c-sole', false);
    }
    g.end();
  }

  function drawArm(pt, J, s, far, focus) {
    var g = pt.group(far ? 'far' : '');
    var all = has(focus, ['arm' + s]);
    var sh = J['sh' + s], el = J['el' + s], ha = J['ha' + s], hd = J['hd' + s];
    var fu = all || has(focus, ['upperArm' + s]), ff = all || has(focus, ['forearm' + s]);
    g.cap(sh, el, W.upperArm[0], W.upperArm[1], 'c-skin', fu);
    g.cap(sh, mix(sh, el, 0.5), W.sleeve[0], W.sleeve[1], 'c-shirt', fu);
    g.cap(el, ha, W.forearm[0], W.forearm[1], 'c-skin', ff);
    g.cap(ha, hd, W.hand[0], W.hand[1], 'c-skin', ff);
    g.end();
  }

  function drawTorsoSide(pt, J, focus) {
    var m = J._, ft = has(focus, ['torso']);
    var P0 = J.pelvis, C = J.chest;
    var midStraight = mix(P0, C, 0.5);
    var ctrl = step(midStraight, m.perp, m.arch * 2);
    var M = [0.25 * P0[0] + 0.5 * ctrl[0] + 0.25 * C[0], 0.25 * P0[1] + 0.5 * ctrl[1] + 0.25 * C[1]];
    var Ci = along(C, P0, 3.5);
    var front = dir(m.perp);
    var g = pt.group();
    g.cap(add(P0, front, 0.8), mix(P0, M, 0.5), W.pelvis - 0.6, W.pelvis, 'c-pants', ft);
    g.cap(mix(P0, M, 0.4), M, 8.8, 9.4, 'c-shirt', ft);
    g.cap(M, Ci, 9.4, W.chest, 'c-shirt', ft);
    g.circle(add(mix(P0, M, 0.75), front, 2.2), 8.6, 'c-shirt', ft); // a little tummy
    g.end();
    // belt line
    var b0 = add(mix(P0, M, 0.42), front, 8.6), b1 = add(mix(P0, M, 0.42), front, -8.4);
    pt.line(b0, b1, 'd-belt', 1.6);
  }

  function drawTorsoFront(pt, J, focus) {
    var m = J._, ft = has(focus, ['torso']);
    var side = dir(m.perp), up = dir(m.tor);
    var g = pt.group();
    var wL = add(mix(J.hipL, J.shL, 0.28), side, -1.8), wR = add(mix(J.hipR, J.shR, 0.28), side, 1.8);
    // trousers
    g.poly([add(mix(J.hipL, J.shL, 0.32), side, -1.4), add(mix(J.hipR, J.shR, 0.32), side, 1.4),
      add(add(J.hipR, side, 5.5), up, -2), add(add(J.hipL, side, -5.5), up, -2)], 'c-pants', ft, 4);
    // shirt
    g.poly([add(J.shL, side, -3), add(J.shR, side, 3), wR, wL], 'c-shirt', ft, 5);
    g.circle(add(J.shR, up, -1.2), 4.6, 'c-shirt', ft);
    g.circle(add(J.shL, up, -1.2), 4.6, 'c-shirt', ft);
    g.end();
    // collar
    var c = add(J.chest, up, -0.5);
    pt.path('M' + r1(c[0] - side[0] * 3.6 + up[0] * 2) + ' ' + r1(c[1] - side[1] * 3.6 + up[1] * 2) +
      'L' + r1(c[0] - up[0] * 3) + ' ' + r1(c[1] - up[1] * 3) +
      'L' + r1(c[0] + side[0] * 3.6 + up[0] * 2) + ' ' + r1(c[1] + side[1] * 3.6 + up[1] * 2), 'd-collar', 1.3);
  }

  function drawNeck(pt, J, focus) {
    var g = pt.group();
    g.cap(along(J.chest, J.neckTop, -2, J._.nk), along(J.neckTop, J.head, 2.5, J._.nk), W.neck[0], W.neck[1], 'c-skin', has(focus, ['neck']));
    g.end();
  }

  // Point on a circle around the head, in head-local axes: theta 0 = forward, 90 = up, 180 = back.
  function headPt(H, f, u, r, theta) {
    var c = Math.cos(theta * RAD), s = Math.sin(theta * RAD);
    return [H[0] + (f[0] * c + u[0] * s) * r, H[1] + (f[1] * c + u[1] * s) * r];
  }
  // Hair shape: outer edge follows the skull, inner edge is the hairline.
  function hairPoly(H, f, u, from, to, outerR, innerR) {
    var pts = [], n = 18, i, t;
    for (i = 0; i <= n; i++) { t = from + (to - from) * i / n; pts.push(headPt(H, f, u, outerR, t)); }
    for (i = n; i >= 0; i--) { t = from + (to - from) * i / n; pts.push(headPt(H, f, u, innerR(t), t)); }
    return pts;
  }

  function drawHeadSide(pt, J, focus) {
    var m = J._, H = J.head, f = dir(m.face), u = dir(m.nk);
    var g = pt.group();
    g.circle(H, HEAD_R, 'c-skin');
    g.circle(add(add(H, f, 9.0), u, -0.6), 1.9, 'c-skin');          // nose
    // silver hair: thin on top, fuller at the back and sides
    g.poly(hairPoly(H, f, u, 62, 222, HEAD_R + 0.7, function (t) {
      var top = Math.max(0, Math.sin(t * RAD));
      return HEAD_R - 3.6 + top * 2.0 - (t > 150 ? (t - 150) / 72 * 1.5 : 0);
    }), 'c-hair');
    g.end();
    var ear = add(add(H, f, -3.6), u, -0.9);
    pt.path(capsuleD(add(ear, u, 1.0), add(ear, u, -1.1), 1.7, 1.3), 'c-skin d-ear');
    pt.path('M' + r1(ear[0] + f[0] * 0.5 + u[0] * 0.9) + ' ' + r1(ear[1] + f[1] * 0.5 + u[1] * 0.9) + 'Q' + r1(ear[0] - f[0] * 0.6) + ' ' + r1(ear[1] - f[1] * 0.6) + ' ' +
      r1(ear[0] + f[0] * 0.4 - u[0] * 0.9) + ' ' + r1(ear[1] + f[1] * 0.4 - u[1] * 0.9), 'd-crease', 0.6);
    var eye = add(add(H, f, 5.4), u, 1.3);
    pt.dot(eye, 0.95, 'd-eye');
    pt.line(add(add(H, f, 3.9), u, 3.5), add(add(H, f, 6.9), u, 3.2), 'd-brow', 1.4);
    // glasses: lens + arm to the ear
    pt.path(capsuleD(add(add(H, f, 6.6), u, 2.1), add(add(H, f, 6.6), u, 0.5), 1.5, 1.5), 'd-glasses', 0.8);
    pt.line(add(add(H, f, 5.1), u, 1.9), add(add(ear, f, 1.2), u, 0.9), 'd-glasses', 0.7);
    pt.line(add(add(H, f, 6.2), u, -4.0), add(add(H, f, 7.9), u, -3.6), 'd-mouth', 1.0);
    // age lines: smile line and a forehead line
    var s0 = add(add(H, f, 6.9), u, -1.0), s1 = add(add(H, f, 5.7), u, -3.4), sc = add(add(H, f, 5.9), u, -1.9);
    pt.path('M' + r1(s0[0]) + ' ' + r1(s0[1]) + 'Q' + r1(sc[0]) + ' ' + r1(sc[1]) + ' ' + r1(s1[0]) + ' ' + r1(s1[1]), 'd-crease', 0.6);
    pt.line(add(add(H, f, 4.6), u, 5.3), add(add(H, f, 6.8), u, 4.8), 'd-crease', 0.5);
    [118, 146, 174, 200].forEach(function (t) {
      pt.line(headPt(H, f, u, HEAD_R - 0.9, t), headPt(H, f, u, HEAD_R - 3.0, t + 9), 'd-hairline', 0.5);
    });
  }

  function drawHeadFront(pt, J, focus) {
    var m = J._, H = J.head, u = dir(m.nk), sd = dir(m.nk - 90);
    var turn = m.turn, sh = turn * 4;
    var f = [-sd[0], -sd[1]]; // for headPt: theta 0 = viewer's left ... we use sd as "right"
    var g = pt.group();
    g.circle(add(add(H, sd, 9 - turn * 2.5), u, 0.2), 2.3, 'c-skin');
    g.circle(add(add(H, sd, -9 - turn * 2.5), u, 0.2), 2.3, 'c-skin');
    g.circle(H, HEAD_R, 'c-skin');
    // hair at the sides, thinning on top
    g.poly(hairPoly(H, sd, u, -14, 194, HEAD_R + 0.7, function (t) {
      var top = Math.max(0, Math.sin(t * RAD));
      return HEAD_R - 3.4 + top * 2.3;
    }), 'c-hair');
    g.end();
    void f;
    [-1, 1].forEach(function (k) {
      var e = add(add(H, u, 0.9), sd, k * 3.4 + sh);
      pt.dot(e, 0.95, 'd-eye');
      pt.path(circleD(e, 2.4), 'd-glasses', 0.8);
      var b = add(add(H, u, 3.9), sd, k * 3.4 + sh);
      pt.line(add(b, sd, -1.5), add(b, sd, 1.5), 'd-brow', 1.2);
    });
    var br = add(add(H, u, 1.1), sd, sh);
    pt.line(add(br, sd, -1), add(br, sd, 1), 'd-glasses', 0.8);
    var n0 = add(add(H, u, -0.6), sd, sh * 1.2), n1 = add(add(H, u, -2.6), sd, sh * 1.2 + 0.7);
    pt.line(n0, n1, 'd-nose', 1.0);
    var mo = add(add(H, u, -5), sd, sh * 1.1);
    pt.path('M' + r1(mo[0] - sd[0] * 2.2) + ' ' + r1(mo[1] - sd[1] * 2.2) + 'Q' + r1(mo[0] - u[0] * 1.1) + ' ' + r1(mo[1] - u[1] * 1.1) + ' ' +
      r1(mo[0] + sd[0] * 2.2) + ' ' + r1(mo[1] + sd[1] * 2.2), 'd-mouth', 1.0);
    [-1, 1].forEach(function (k) {
      var a0 = add(add(H, u, -1.6), sd, k * 3.1 + sh), a1 = add(add(H, u, -5.2), sd, k * 3.6 + sh);
      pt.line(a0, a1, 'd-crease', 0.55);
      var hs = headPt(H, sd, u, HEAD_R - 0.8, k > 0 ? 20 : 160), he = headPt(H, sd, u, HEAD_R - 2.6, k > 0 ? 36 : 144);
      pt.line(hs, he, 'd-hairline', 0.5);
    });
    pt.line(add(add(H, u, 5.6), sd, -2.2 + sh), add(add(H, u, 5.6), sd, 2.2 + sh), 'd-crease', 0.5);
  }

  function drawBody(pt, J, focus) {
    var m = J._;
    if (m.front) {
      drawLeg(pt, J, 'L', false, focus);
      drawLeg(pt, J, 'R', false, focus);
      drawNeck(pt, J, focus);
      drawTorsoFront(pt, J, focus);
      drawHeadFront(pt, J, focus);
      drawArm(pt, J, 'L', false, focus);
      drawArm(pt, J, 'R', false, focus);
    } else {
      drawLeg(pt, J, 'L', true, focus);
      drawArm(pt, J, 'L', true, focus);
      drawNeck(pt, J, focus);
      drawTorsoSide(pt, J, focus);
      drawHeadSide(pt, J, focus);
      drawLeg(pt, J, 'R', false, focus);
      drawArm(pt, J, 'R', false, focus);
    }
  }

  /* ---------- hands ---------- */

  function drawHand(pt, J, focus) {
    var fh = has(focus, ['hand']), fw = has(focus, ['wrist']), ff = has(focus, ['fingers']);
    var g = pt.group();
    g.cap(J.elbow, J.wrist, 7.2, 5.6, 'c-skin', has(focus, ['forearm']));
    g.cap(J.elbow, along(J.elbow, J.wrist, 14), 8.4, 8.0, 'c-shirt');
    g.cap(J.wrist, J.knuck, 5.4, 4.8, 'c-skin', fh || fw);
    g.cap(along(J.wrist, J.knuck, 3), along(J.tb, J.t1, 5), 4.9, 3.6, 'c-skin', fh || fw); // base of the thumb
    g.end();
    // fingers behind (suggests the other fingers)
    var back = [-1.4, -1.8];
    var gb = pt.group('far');
    gb.cap(add(J.knuck, back, 1), add(J.f1, back, 1), 3.0, 2.7, 'c-skin', ff);
    gb.cap(add(J.f1, back, 1), add(J.f2, back, 1), 2.7, 2.4, 'c-skin', ff);
    gb.cap(add(J.f2, back, 1), add(J.f3, back, 1), 2.4, 2.1, 'c-skin', ff);
    gb.end();
    var gf = pt.group();
    gf.cap(J.knuck, J.f1, 3.1, 2.8, 'c-skin', ff);
    gf.cap(J.f1, J.f2, 2.8, 2.5, 'c-skin', ff);
    gf.cap(J.f2, J.f3, 2.5, 2.2, 'c-skin', ff);
    gf.end();
    var gt = pt.group();
    var ft = has(focus, ['thumb']);
    gt.cap(J.tb, J.t1, 3.4, 3.0, 'c-skin', ft);
    gt.cap(J.t1, J.t2, 3.0, 2.6, 'c-skin', ft);
    gt.end();
    // knuckle crease + nail
    pt.dot(J.f3, 1.0, 'd-nail');
  }

  function drawPalm(pt, J, focus) {
    var fh = has(focus, ['hand', 'wrist']), ff = has(focus, ['fingers']), ft = has(focus, ['thumb']);
    var g0 = pt.group();
    g0.cap([0, 4], J.forearm, 8.0, 9.0, 'c-skin', has(focus, ['forearm']));
    g0.cap([0, 30], [0, 46], 10, 10, 'c-shirt');
    g0.end();
    var inner = new Painter(pt.box);
    var g = inner.group();
    g.poly([[-13.5, -31], [13.5, -31], [13, -2], [-12, -2]], 'c-skin', fh, 7);
    for (var i = 0; i < 4; i++) {
      var b = J['fb' + i], tip = J['ft' + i];
      g.cap([b[0], b[1] + 2], tip, 3.2, 2.7, 'c-skin', ff);
    }
    g.end();
    var gt = inner.group();
    gt.cap(J.tb, J.t1, 4.2, 3.4, 'c-skin', ft);
    gt.cap(J.t1, J.t2, 3.4, 2.8, 'c-skin', ft);
    gt.end();
    inner.path('M-7 -12Q0 -8 8 -14', 'd-crease', 0.9);
    inner.path('M-9 -20Q0 -17 10 -22', 'd-crease', 0.9);
    pt.box.add([-18, -62]); pt.box.add([30, 6]);
    pt.raw('<g transform="rotate(' + r1(-J._.dev) + ')">' + inner.out.join('') + '</g>');
  }

  // Forearm and hand seen from above. rot: 0 = palm down, 180 = palm up.
  function drawForearm(pt, J, focus) {
    var rot = J._.rot, c = Math.cos(rot * RAD), w = Math.abs(c);
    var palmUp = c < 0, skin = palmUp ? 'c-palm' : 'c-skin';
    var h = 2.6 + 8.4 * w;          // half-width of the hand as seen from above
    var ts = -c;                    // thumb side: negative = top of the picture (palm down)
    var g0 = pt.group();
    g0.cap(J.elbow, J.wrist, 7.4, 5.4 + 0.6 * w, skin, has(focus, ['forearm']));
    g0.cap(J.elbow, [-42, 0], 9, 8.6, 'c-shirt');
    g0.end();
    var g = pt.group();
    g.poly([[1, -h * 0.85], [21, -h], [21, h], [1, h * 0.85]], skin, has(focus, ['hand']), 5);
    var ys = [0.74, 0.25, -0.25, -0.74], lens = [13, 14.5, 13.5, 11];
    function fy(i) { return ys[i] * h * ts; }   // index finger next to the thumb
    for (var i = 0; i < 4; i++) g.cap([21, fy(i)], [21 + lens[i], fy(i) * 1.08], 2.9, 2.4, skin, has(focus, ['fingers']));
    g.end();
    var gt = pt.group();
    gt.cap([5, ts * h * 0.8], [12, ts * (h + 2.6)], 3.5, 3.0, skin, has(focus, ['thumb']));
    gt.cap([12, ts * (h + 2.6)], [19, ts * (h + 4.2)], 3.0, 2.6, skin, has(focus, ['thumb']));
    gt.end();
    if (c > 0.35) {          // back of the hand: knuckles and nails
      for (var k = 0; k < 4; k++) {
        pt.dot([21 + lens[k] - 1.2, fy(k) * 1.08], 1.15, 'd-nail');
        pt.dot([21.5, fy(k)], 0.7, 'd-knuckle');
      }
    } else if (c < -0.35) {  // palm: creases
      pt.path('M4 ' + r1(-h * 0.5) + 'Q11 ' + r1(-h * 0.1) + ' 18 ' + r1(-h * 0.45), 'd-crease', 0.8);
      pt.path('M5 ' + r1(h * 0.3) + 'Q12 ' + r1(h * 0.05) + ' 19 ' + r1(h * 0.35), 'd-crease', 0.8);
    }
    pt.box.add([-58, -20]); pt.box.add([40, 20]);
  }

  function drawFloorShadow(pt, J) {
    var x0 = Infinity, x1 = -Infinity;
    ['toR', 'toL', 'heR', 'heL', 'knR', 'knL', 'pelvis', 'chest', 'head', 'hdR', 'hdL', 'haR', 'haL'].forEach(function (k) {
      if (J[k] && J[k][1] > -12) { x0 = Math.min(x0, J[k][0]); x1 = Math.max(x1, J[k][0]); }
    });
    if (x0 === Infinity) return;
    var id = pt.uid + '_sh';
    pt.defs.push('<radialGradient id="' + id + '"><stop offset="0" stop-color="#000" stop-opacity=".22"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>');
    pt.out.push('<ellipse cx="' + r1((x0 + x1) / 2) + '" cy="0.6" rx="' + r1((x1 - x0) / 2 + 10) + '" ry="3.6" fill="url(#' + id + ')"/>');
  }

  /* ---------- props ---------- */

  function anchorPt(spec, J, J0) {
    if (Array.isArray(spec)) return spec;
    if (typeof spec === 'string') return J[spec];
    var src = spec.fixed === false ? J : J0;
    var b = src[spec.j];
    return [b[0] + (spec.dx || 0), b[1] + (spec.dy || 0)];
  }

  function jointsExtent(J) {
    var b = new Box();
    for (var k in J) if (k !== '_') b.add(J[k]);
    return b;
  }

  function rect(pt, x, y, w, h, cls, rx) {
    pt.box.add([x, y]); pt.box.add([x + w, y + h]);
    pt.raw('<rect x="' + r1(x) + '" y="' + r1(y) + '" width="' + r1(w) + '" height="' + r1(h) + '" rx="' + (rx == null ? 1.5 : rx) + '" class="' + cls + '"/>');
  }

  function drawProps(pt, fig, J, J0, layer) {
    (fig.props || []).forEach(function (pr) {
      var back = pr.t === 'chair' || pr.t === 'wall' || pr.t === 'table' || pr.t === 'roll' || pr.t === 'block';
      if ((layer === 'back') !== back) return;
      var a, b, x, y, w;
      switch (pr.t) {
        case 'chair': {
          x = J0.pelvis[0] + (pr.dx || 0); y = J0.pelvis[1] + W.pelvis + 0.5;
          if (fig.view === 'front') {
            rect(pt, x - 18, y - 46, 36, 44, 'p-wood p-back', 3);
            pt.line([x - 17, y + 3], [x - 17, 0], 'p-leg', 3);
            pt.line([x + 17, y + 3], [x + 17, 0], 'p-leg', 3);
            rect(pt, x - 22, y, 44, 4.5, 'p-wood', 2);
          } else {
            var s = pr.flip ? -1 : 1;
            pt.line([x - 14 * s, y + 3], [x - 14 * s, 0], 'p-leg', 3);
            pt.line([x + 13 * s, y + 3], [x + 13 * s, 0], 'p-leg', 3);
            pt.line([x - 15 * s, y + 2], [x - 19 * s, y - 40], 'p-leg', 3.6);
            rect(pt, Math.min(x - 17 * s, x + 16 * s), y, 33, 4.5, 'p-wood', 2);
          }
          break;
        }
        case 'wall': {
          var ext = jointsExtent(J0);
          x = pr.side === 'back' ? ext.x0 - (pr.gap || 4) - 6 : ext.x1 + (pr.gap || 4);
          rect(pt, x, -(pr.h || 150), 6, pr.h || 150, 'p-wall', 0);
          break;
        }
        case 'table': {
          a = anchorPt(pr.at, J0, J0);
          y = a[1] + (pr.dy == null ? 5 : pr.dy); w = pr.w || 54;
          x = a[0] + (pr.dx || 0);
          if (fig.floor !== false && fig.view !== 'hand') {
            pt.line([x - w / 2 + 5, y + 3], [x - w / 2 + 5, 0], 'p-leg', 3);
            pt.line([x + w / 2 - 5, y + 3], [x + w / 2 - 5, 0], 'p-leg', 3);
          }
          rect(pt, x - w / 2, y, w, fig.view === 'hand' ? 20 : 5, 'p-wood', 2);
          break;
        }
        case 'roll': {
          a = anchorPt(pr.at, J0, J0); var rr = pr.r || 6;
          var c = [a[0] + (pr.dx || 0), -rr - OLW];
          pt.box.add(c, rr);
          pt.path(circleD(c, rr), 'p-towel', 1.5);
          pt.path(circleD(c, rr * 0.45), 'p-towel-in', 1);
          break;
        }
        case 'block': {
          a = anchorPt(pr.at, J0, J0); w = pr.w || 8; var bh = pr.h || 8;
          rect(pt, a[0] - w / 2, a[1] - bh / 2, w, bh, 'p-wood', 1.5);
          break;
        }
        case 'band': {
          a = anchorPt(pr.from, J, J0); b = anchorPt(pr.to, J, J0);
          pt.line(a, b, 'p-band', 2.4);
          if (typeof pr.to === 'object' && !Array.isArray(pr.to) && pr.to.fixed !== false) {
            pt.box.add(b, 3);
            pt.path(circleD(b, 2.6), 'p-anchor', 1);
          }
          break;
        }
        case 'towel': {
          a = anchorPt(pr.from, J, J0); b = anchorPt(pr.to, J, J0);
          pt.line(a, b, 'p-strap', 3.2);
          break;
        }
        case 'weight': {
          a = anchorPt(pr.at, J, J0);
          rect(pt, a[0] - 5, a[1] - 3.5, 10, 7, 'p-weight', 2);
          break;
        }
        case 'arrow': {
          // Movement cue, fixed in place: starts near a joint of the first pose.
          a = anchorPt({ j: pr.at, dx: pr.dx, dy: pr.dy }, J0, J0);
          b = step(a, pr.angle, pr.len || 10);
          var ad = dir(pr.angle), an = [-ad[1], ad[0]];
          var tip = add(b, ad, 2.2);
          pt.line(a, b, 'p-arrow', 2);
          pt.box.add(tip, 3);
          pt.raw('<path d="' + polyD([tip, add(add(b, ad, -1.6), an, 3), add(add(b, ad, -1.6), an, -3)]) + '" class="p-arrowhead"/>');
          break;
        }
        case 'orbit': {
          // Circular movement cue (e.g. ankle circles, forearm turning).
          a = anchorPt({ j: pr.at, dx: pr.dx, dy: pr.dy }, J0, J0);
          var rx = pr.rx || 8, ry = pr.ry || 8, d0 = '', th, q;
          for (th = 25; th <= 320; th += 15) {
            q = [a[0] + rx * Math.cos(th * RAD), a[1] + ry * Math.sin(th * RAD)];
            d0 += (d0 ? 'L' : 'M') + r1(q[0]) + ' ' + r1(q[1]);
            pt.box.add(q, 2);
          }
          pt.path(d0, 'p-orbit', 1.6);
          var te = 320 * RAD, tp = [a[0] + rx * Math.cos(te), a[1] + ry * Math.sin(te)];
          var tg = [-rx * Math.sin(te), ry * Math.cos(te)], tl = Math.hypot(tg[0], tg[1]);
          tg = [tg[0] / tl, tg[1] / tl];
          var tn = [-tg[1], tg[0]];
          pt.raw('<path d="' + polyD([add(tp, tg, 2.6), add(tp, tn, 2.4), add(tp, tn, -2.4)]) + '" class="p-arrowhead"/>');
          break;
        }
        case 'ball': {
          a = anchorPt(pr.at, J, J0);
          pt.box.add(a, pr.r || 7);
          pt.path(circleD(a, pr.r || 7), 'p-ball', 1.4);
          break;
        }
      }
    });
  }

  /* ---------- frame & viewbox ---------- */

  function drawFrame(fig, p, J0, box) {
    var pt = new Painter(box);
    var J = solve(fig, p);
    var focus = fig.focus || [];
    var v = p.view || fig.view;
    drawProps(pt, fig, J, J0, 'back');
    if ((v === 'side' || v === 'front') && fig.floor !== false) drawFloorShadow(pt, J);
    if (v === 'forearm') drawForearm(pt, J, focus);
    else if (v === 'hand') drawHand(pt, J, focus);
    else if (v === 'palm') drawPalm(pt, J, focus);
    else drawBody(pt, J, focus);
    drawProps(pt, fig, J, J0, 'front');
    return pt;
  }

  var cache = typeof WeakMap !== 'undefined' ? new WeakMap() : null;

  function viewBox(fig) {
    if (cache && cache.has(fig)) return cache.get(fig);
    var box = new Box();
    var J0 = solve(fig, normalize(fig.poses[0]));
    var n = fig.poses.length, steps = Math.max(1, (n - 1) * 6);
    for (var i = 0; i <= steps; i++) drawFrame(fig, poseAt(fig, (i / steps) * (n - 1)), J0, box);
    var hand = fig.view === 'hand' || fig.view === 'palm' || fig.view === 'forearm';
    var base = hand ? HAND_BOX : BODY_BOX;
    var w = Math.max(base.w, box.x1 - box.x0 + 16);
    var h = Math.max(base.h, box.y1 - box.y0 + 16);
    if (w / h > base.w / base.h) h = w * base.h / base.w; else w = h * base.w / base.h;
    var cx = (box.x0 + box.x1) / 2;
    var y0, floorY = null;
    if (!hand && fig.floor !== false) {
      floorY = 0;
      y0 = 12 - h; // floor sits 12 units above the bottom edge
    } else {
      y0 = (box.y0 + box.y1) / 2 - h / 2;
    }
    var vb = { x: cx - w / 2, y: y0, w: w, h: h, floorY: floorY, J0: J0 };
    if (cache) cache.set(fig, vb);
    return vb;
  }

  /**
   * Render a figure to an SVG string.
   * t: frame position from 0 to poses.length - 1 (fractional values interpolate).
   */
  function render(fig, t, label) {
    if (!fig || !fig.poses || !fig.poses.length) return '';
    var vb = viewBox(fig);
    var pt = drawFrame(fig, poseAt(fig, t || 0), vb.J0, new Box());
    var body = (pt.defs.length ? '<defs>' + pt.defs.join('') + '</defs>' : '') + pt.out.join('');
    var floor = vb.floorY == null ? '' :
      '<rect x="' + r1(vb.x) + '" y="0" width="' + r1(vb.w) + '" height="12" class="f-ground"/>' +
      '<line x1="' + r1(vb.x) + '" y1="0" x2="' + r1(vb.x + vb.w) + '" y2="0" class="f-floor"/>';
    return '<svg class="fig" viewBox="' + [vb.x, vb.y, vb.w, vb.h].map(r1).join(' ') +
      '" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="' + (label || 'Exercise illustration').replace(/"/g, '&quot;') + '">' +
      floor + body + '</svg>';
  }

  function frameCount(fig) { return fig && fig.poses ? fig.poses.length : 0; }

  global.HEPFig = { render: render, pose: pose, base: P, frameCount: frameCount };
})(window);
