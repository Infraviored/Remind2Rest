// Same glass outline for every size; CSS sets the height. The rim (y 19) leaves little room above
// the water, so a hard jerk sloshes over. The walls are the lines (14,10)-(24,146), cut at y 19.
const OUTLINE = 'M14.66 19 L105.34 19 L96 146 Q95 152 89 152 L31 152 Q25 152 24 146 Z';
const RIM_Y = 19;
const FULL = 0.74;      // water level of a glass waiting to be drunk
const FLOW = [0.06, 0.65]; // s after the pour starts: water runs over the rim (the glass empties)
const DRIPS = [0.07, 0.19, 0.36]; // s after the flow ends: last drops from the rim
const CLOSE_AFTER = 250; // after the last water landed, then close
const GRAVITY = 2400;   // per carafe viewBox unit (x geo.s = px/s^2)
// Share of the glass poured after fraction x of the flow time: strongest early, runs out thin.
const poured = x => 1 - (1 - x) ** 3 * (1 + 3 * x);
const flowRate = x => 12 * x * (1 - x) ** 2 / (16 / 9);   // its slope, 1 at the peak
const POUR_TILT = 104;  // degrees, glass rim pointing down into the carafe
const MAX_CARRY_TILT = 86;
const IMPACT = 120;    // push of the stream on the carafe surface, per viewBox unit of stream width
// Carafe geometry in its viewBox (0 0 200 360): opening at the top, water between EMPTY_Y and FULL_Y.
const CARAFE = {openX: 100, openY: 12, neckHalf: 56, emptyY: 342, fullY: 72};

// --- volumes: both vessels are solids of revolution; profiles = inner outline, [radius, y] from the bottom up ---
const curve = (n, f) => Array.from({length: n + 1}, (_, i) => f(i / n));
const lerp2 = (a, b) => t => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
const quad = (a, b, c) => t => [0, 1].map(i => (1 - t) ** 2 * a[i] + 2 * (1 - t) * t * b[i] + t * t * c[i]);
const cubic = (a, b, c, d) => t => [0, 1].map(i =>
    (1 - t) ** 3 * a[i] + 3 * (1 - t) ** 2 * t * b[i] + 3 * (1 - t) * t * t * c[i] + t ** 3 * d[i]);
// Carafe clip path (centre x=100): flat bottom r=56, rounded corner, body r=78, shoulders, wide neck r=56.
const CARAFE_PROFILE = [
    ...curve(200, quad([56, 342], [78, 342], [78, 320])),
    ...curve(50, lerp2([78, 320], [78, 102])),
    ...curve(200, cubic([78, 102], [78, 76], [56, 66], [56, 44])),
    ...curve(20, lerp2([56, 44], [56, 14])),
];
// Glass clip path (centre x=60): bottom r=29, rounded corner, then a frustum up to r=46 at the rim.
const GLASS_PROFILE = [
    ...curve(100, quad([29, 152], [35, 152], [36, 146])),
    ...curve(50, lerp2([36, 146], [45.34, RIM_Y])),
];
// Cumulative volume from the bottom: sum of conical frustums pi*h*(r0^2 + r0*r1 + r1^2)/3.
function volumeTable(profile) {
    const ys = [profile[0][1]], vs = [0];
    for (let i = 1; i < profile.length; i++) {
        const [r0, y0] = profile[i - 1], [r1, y1] = profile[i];
        if (y1 >= y0) continue;
        ys.push(y1);
        vs.push(vs.at(-1) + Math.PI * (y0 - y1) * (r0 * r0 + r0 * r1 + r1 * r1) / 3);
    }
    const volumeBelow = y => {   // volume between the bottom and height y
        if (y >= ys[0]) return 0;
        for (let i = 1; i < ys.length; i++) {
            if (ys[i] <= y) return vs[i - 1] + (vs[i] - vs[i - 1]) * (ys[i - 1] - y) / (ys[i - 1] - ys[i]);
        }
        return vs.at(-1);
    };
    const heightOf = v => {      // inverse: the y where the volume below is v
        if (v <= 0) return ys[0];
        for (let i = 1; i < vs.length; i++) {
            if (vs[i] >= v) return ys[i - 1] - (ys[i - 1] - ys[i]) * (v - vs[i - 1]) / (vs[i] - vs[i - 1]);
        }
        return ys.at(-1);
    };
    return {volumeBelow, heightOf};
}
const CARAFE_VOL = volumeTable(CARAFE_PROFILE);
const GLASS_VOL = volumeTable(GLASS_PROFILE);
const CARAFE_GOAL_VOL = CARAFE_VOL.volumeBelow(CARAFE.fullY);        // the goal mark
const CARAFE_MAX_FILL = CARAFE_VOL.volumeBelow(24) / CARAFE_GOAL_VOL; // above the goal it fills the neck
const GLASS_WATER_VOL = GLASS_VOL.volumeBelow(152 - FULL * 142);      // a full glass = its nominal ml
// Carafe y (viewBox) for a fraction of the goal, by volume.
const carafeY = f => CARAFE_VOL.heightOf(clamp(f, 0, CARAFE_MAX_FILL) * CARAFE_GOAL_VOL);

function glassSvg(id) {
    return `
    <svg viewBox="0 0 120 160" aria-hidden="true">
        <defs>
            <clipPath id="inside-${id}"><path d="${OUTLINE}"/></clipPath>
            <linearGradient id="fill-${id}" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#38bdf8" stop-opacity="0.85"/>
                <stop offset="1" stop-color="#818cf8" stop-opacity="0.75"/>
            </linearGradient>
        </defs>
        <g clip-path="url(#inside-${id})">
            <rect x="0" y="0" width="120" height="160" fill="rgba(255,255,255,0.04)"/>
            <g class="water">
                <path class="wave-back" fill="#38bdf8" fill-opacity="0.35"/>
                <path class="wave" fill="url(#fill-${id})"/>
            </g>
        </g>
        <path d="${OUTLINE}" fill="none" stroke="rgba(226,232,255,0.75)" stroke-width="3" stroke-linejoin="round"/>
        <path d="M27.3 32 L23.5 90" stroke="rgba(255,255,255,0.35)" stroke-width="4" stroke-linecap="round"/>
    </svg>`;
}

// A water surface as a row of columns between x0 and x1 (viewBox units, + = down). Each column is
// pulled towards its neighbours, so a push travels sideways as a ripple and bounces off the walls
// (the end columns mirror themselves); a weak pull to rest and damping let it die out. A few dozen
// columns at 240 steps/s: a few thousand additions per second, nothing next to drawing the page.
class Surface {
    constructor(x0, x1, n, {speed, rest, damping, limit}) {
        this.x0 = x0; this.dx = (x1 - x0) / (n - 1); this.n = n;
        this.h = new Float32Array(n); this.v = new Float32Array(n);
        this.spread = (speed / this.dx) ** 2;
        this.rest = rest; this.damping = damping; this.limit = limit;
    }
    // Velocity added around x, spread over `radius` columns with a soft edge. Water keeps its
    // volume: what is pushed down there rises everywhere else (the mean is taken out again).
    poke(x, dv, radius = 1) {
        const c = Math.round((x - this.x0) / this.dx);
        let total = 0;
        for (let i = c - radius; i <= c + radius; i++) {
            if (i < 0 || i >= this.n) continue;
            const a = dv * (1 - Math.abs(i - c) / (radius + 1));
            this.v[i] += a;
            total += a;
        }
        for (let i = 0; i < this.n; i++) this.v[i] -= total / this.n;
    }
    // Force per column from f(x), e.g. the sideways acceleration of a carried glass.
    push(f, dt) {
        for (let i = 0; i < this.n; i++) this.v[i] += f(this.x0 + i * this.dx) * dt;
    }
    step(dt) {
        const {h, v, n} = this;
        for (let i = 0; i < n; i++) {
            const l = h[i > 0 ? i - 1 : 0], r = h[i < n - 1 ? i + 1 : n - 1];
            v[i] += (this.spread * (l + r - 2 * h[i]) - this.rest * h[i] - this.damping * v[i]) * dt;
        }
        for (let i = 0; i < n; i++) h[i] = clamp(h[i] + v[i] * dt, -this.limit, this.limit);
    }
    // Ripple height at x (between columns: linear).
    heightAt(x) {
        const f = clamp((x - this.x0) / this.dx, 0, this.n - 1), i = Math.min(this.n - 2, Math.floor(f));
        return this.h[i] + (this.h[i + 1] - this.h[i]) * (f - i);
    }
    // Closed SVG path: the surface at height y (+ ripples, + extra(x) for a calm idle swell, a
    // mirrored copy for the back layer), flat beyond the columns out to xl/xr, down to `bottom`.
    path(y, xl, xr, bottom, {extra = () => 0, mirror = false, scale = 1} = {}) {
        const {h, n, x0, dx} = this;
        const pt = i => {
            const x = x0 + i * dx;
            return [x, y + scale * h[mirror ? n - 1 - i : i] + extra(x)];
        };
        let [px, py] = pt(0);
        let d = `M${xl} ${py.toFixed(2)} L${px.toFixed(1)} ${py.toFixed(2)}`;
        for (let i = 1; i < n; i++) {   // through the midpoints, with the columns as control points: smooth
            const [qx, qy] = pt(i);
            d += ` Q${px.toFixed(1)} ${py.toFixed(2)} ${((px + qx) / 2).toFixed(1)} ${((py + qy) / 2).toFixed(2)}`;
            [px, py] = [qx, qy];
        }
        return d + ` L${px.toFixed(1)} ${py.toFixed(2)} L${xr} ${py.toFixed(2)} L${xr} ${bottom} L${xl} ${bottom} Z`;
    }
}

// Water sloshing in a glass, as its standing waves (modes 1, 3, 5: the ones a sideways push
// excites). Mode n has n half waves across the water; its frequency follows from water waves
// (w^2 = g k tanh(k depth)), and the small ones die out faster (viscosity). A sideways
// acceleration a wants the surface tilted by a/g; a jerk goes ~80 % into mode 1, so the water
// swings from wall to wall two or three times (~3 Hz in a 200 ml glass) and settles within a second.
// Units: the glass viewBox; `widthMm` is the real rim width, which sets g in viewBox units.
class Slosh {
    constructor(widthMm) {
        this.g = 9810 / (widthMm / 92);   // 92 = rim width in the viewBox
        this.a = [0, 0, 0]; this.v = [0, 0, 0];
    }
    reset() { this.a.fill(0); this.v.fill(0); }
    // accX/accY: acceleration of the glass (viewBox units/s^2, y down); L, depth: of the water.
    step(dt, accX, accY, L, depth) {
        const g = Math.max(0.3 * this.g, this.g - accY);   // lifted fast, the water weighs more
        for (let i = 0; i < 3; i++) {
            const n = 2 * i + 1, k = n * Math.PI / L;
            const w2 = g * k * Math.tanh(k * depth), w = Math.sqrt(w2);
            // The tilt a/g as a sum of modes: wall height (L/2)(a/g), share 8/(n pi)^2.
            // 0.4: a hand smooths a mouse jerk; the pointer alone would shake it at several g.
            const target = -0.4 * (accX / g) * (L / 2) * 8 / (n * Math.PI) ** 2;
            this.v[i] += (w2 * (target - this.a[i]) - 2 * 0.15 * n * w * this.v[i]) * dt;
            this.a[i] += this.v[i] * dt;
        }
        const max = L / 2 * Math.tan(40 * Math.PI / 180);
        this.a[0] = clamp(this.a[0], -max, max);
    }
    // Height (+ = down) at x of water between the walls wl..wr: the modes, plus the second-order
    // part that makes the crest climbing a wall sharp and the trough flat.
    height(x, wl, wr) {
        const L = wr - wl, xi = clamp((x - wl) / L, 0, 1), [a1, a3, a5] = this.a;
        return a1 * Math.cos(Math.PI * xi) + a3 * Math.cos(3 * Math.PI * xi) + a5 * Math.cos(5 * Math.PI * xi)
            - 0.5 * (Math.PI / L) * a1 * a1 * Math.cos(2 * Math.PI * xi);
    }
    // How fast the water climbs the wall (viewBox units/s, + = up): side -1 left, +1 right.
    climb(side) {
        const [v1, v3, v5] = this.v;
        return side < 0 ? -(v1 + v3 + v5) : v1 + v3 + v5;
    }
    // The surface tilt of mode 1 (deg, + = clockwise: left side up), for what runs over the rim.
    angle(L) { return Math.atan(-this.a[0] / (L / 2)) * 180 / Math.PI; }
    // Closed SVG path like Surface.path: the sloshing surface at height y between the walls.
    path(y, wl, wr, xl, xr, bottom, {extra = () => 0, scale = 1} = {}) {
        const n = 16, pt = i => {
            const x = wl + (wr - wl) * i / n;
            return [x, y + scale * this.height(x, wl, wr) + extra(x)];
        };
        let [px, py] = pt(0);
        let d = `M${xl} ${py.toFixed(2)} L${px.toFixed(1)} ${py.toFixed(2)}`;
        for (let i = 1; i <= n; i++) {
            const [qx, qy] = pt(i);
            d += ` Q${px.toFixed(1)} ${py.toFixed(2)} ${((px + qx) / 2).toFixed(1)} ${((py + qy) / 2).toFixed(2)}`;
            [px, py] = [qx, qy];
        }
        return d + ` L${px.toFixed(1)} ${py.toFixed(2)} L${xr} ${py.toFixed(2)} L${xr} ${bottom} L${xl} ${bottom} Z`;
    }
}

const glassTop = level => 152 - level * 142;

// --- the water in a tilted glass keeps its amount (2D area of the glass outline below the surface) ---
// Glass inside as a polygon (glass viewBox), the rounded bottom corners sampled.
const GLASS_POLY = [[14.66, RIM_Y], [105.34, RIM_Y], [96, 146], [95.5, 150], [93, 151.6], [89, 152],
                    [31, 152], [27, 151.6], [24.5, 150], [24, 146]];
const RIM = [GLASS_POLY[0], GLASS_POLY[1]];
// The water group is rotated by `angle` (deg) about (60, 90); its surface is the line y = top in that
// frame. A glass point lies under water when, turned back by -angle, its y is below `top`.
function waterFrame(angle) {
    const a = -angle * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    return ([x, y]) => [60 + (x - 60) * c - (y - 90) * s, 90 + (x - 60) * s + (y - 90) * c];
}
function areaBelow(pts, top) {   // pts already in the water frame; clip to y >= top, shoelace
    const out = [];
    for (let i = 0; i < pts.length; i++) {
        const p = pts[i], q = pts[(i + 1) % pts.length];
        const pin = p[1] >= top, qin = q[1] >= top;
        if (pin) out.push(p);
        if (pin !== qin) {
            const t = (top - p[1]) / (q[1] - p[1]);
            out.push([p[0] + (q[0] - p[0]) * t, top]);
        }
    }
    let a = 0;
    for (let i = 0; i < out.length; i++) {
        const p = out[i], q = out[(i + 1) % out.length];
        a += p[0] * q[1] - q[0] * p[1];
    }
    return Math.abs(a) / 2;
}
// Surface height (water frame) for `area` at `angle`, and how much fits before it runs over the rim.
function tiltedWater(area, angle) {
    const f = waterFrame(angle);
    const pts = GLASS_POLY.map(f);
    const rim = RIM.map(f);
    const spillTop = Math.max(rim[0][1], rim[1][1]);   // the lower rim corner: water can rise to it
    const capacity = areaBelow(pts, spillTop);
    let lo = Math.min(...pts.map(p => p[1])) - 1, hi = Math.max(...pts.map(p => p[1]));
    for (let i = 0; i < 22; i++) {
        const mid = (lo + hi) / 2;
        if (areaBelow(pts, mid) > area) lo = mid; else hi = mid;
    }
    return {top: (lo + hi) / 2, capacity, spillCorner: rim[0][1] > rim[1][1] ? 0 : 1};
}
// Where the water line y = top meets the glass walls (water frame): [left x, right x].
function wallsAt(angle, top) {
    const pts = GLASS_POLY.map(waterFrame(angle));
    let wl = Infinity, wr = -Infinity;
    for (let i = 0; i < pts.length; i++) {
        const p = pts[i], q = pts[(i + 1) % pts.length];
        if ((p[1] - top) * (q[1] - top) > 0 || p[1] === q[1]) continue;
        const x = p[0] + (q[0] - p[0]) * (top - p[1]) / (q[1] - p[1]);
        wl = Math.min(wl, x); wr = Math.max(wr, x);
    }
    return wr - wl > 1 ? [wl, wr] : [55, 65];
}
const FULL_AREA = areaBelow(GLASS_POLY, glassTop(FULL));
const SPILL_DROP_AREA = 22;   // glass area that leaves as one falling drop

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const smooth = t => t * t * (3 - 2 * t);
const rot = (p, deg) => {
    const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    return {x: p.x * c - p.y * s, y: p.x * s + p.y * c};
};

(async () => {
    const api = await R2R.api;
    const title = document.getElementById('title');
    const amount = document.getElementById('amount');
    const shelf = document.getElementById('glasses');
    const actions = document.getElementById('actions');
    const carafe = document.getElementById('carafe');
    const carafeWater = document.getElementById('carafeWater');
    const carafeBack = document.getElementById('carafeBack');
    const stream = document.getElementById('stream');
    const streamCore = document.getElementById('streamCore');

    let state = {today_ml: 0, goal_ml: 2000};
    try { state = await R2R.hold(api.get_water_today()); } catch (e) { /* keep defaults */ }
    const goal = () => Math.max(1, Number(state.goal_ml) || 2000);
    let shownMl = Number(state.today_ml) || 0;   // what the carafe shows; animates during a pour
    if (shownMl >= goal()) title.textContent = 'Goal reached';

    const showAmount = ml => {
        amount.innerHTML = `${Math.round(ml)} <span>/ ${goal()} ml</span>`;
    };
    showAmount(shownMl);

    // Subtle quarter marks on the carafe, labelled in ml.
    const ticks = document.getElementById('ticks');
    for (const q of [0.25, 0.5, 0.75, 1]) {
        const y = carafeY(q);
        ticks.insertAdjacentHTML('beforeend',
            `<line x1="160" x2="174" y1="${y}" y2="${y}"/>`
            + `<text x="188" y="${y + 4}">${Math.round(goal() * q)}</text>`);
    }

    // --- geometry (screen px), measured while nothing is moved ---
    let geo = null;
    const glasses = [...shelf.querySelectorAll('.glass')].map(el => {
        const ml = Number(el.dataset.ml);
        el.innerHTML = `<div class="art">${glassSvg(ml)}</div><span class="label">${ml} ml</span>`;
        return {
            ml, el, key: el.dataset.key,
            art: el.querySelector('.art'),
            water: el.querySelector('.water'),
            wave: el.querySelector('.wave'),
            waveBack: el.querySelector('.wave-back'),
            mode: 'rest',          // rest | held | back | fly | pour
            off: {x: 0, y: 0}, vel: {x: 0, y: 0}, want: {x: 0, y: 0},
            tilt: 0,
            slosh: new Slosh(75 * Math.cbrt(ml / 200)),   // a 200 ml glass is ~75 mm wide at the rim
            L: 86, depth: 100,                            // water width and depth (viewBox), per frame
            spray: [0, 0],                                // spray drops due at the left / right wall
            area: FULL_AREA, spilled: 0, phase: ml / 97,
            home: null, k: 1, grab: null,
        };
    });
    // True to scale by volume: carafe (to the goal mark) : glass water = goal : ml.
    // The carafe keeps its CSS size; the glasses are sized from it.
    function sizeGlasses() {
        const carafeH = carafe.getBoundingClientRect().height;
        for (const g of glasses) {
            const linear = Math.cbrt(g.ml / goal() * CARAFE_GOAL_VOL / GLASS_WATER_VOL);
            g.el.style.setProperty('--h', `${carafeH / 360 * 160 * linear}px`);
        }
    }
    function measure() {
        sizeGlasses();
        for (const g of glasses) {
            if (g.mode !== 'rest') continue;
            const r = g.art.getBoundingClientRect();
            g.home = {x: r.left + r.width / 2, y: r.top + r.height / 2};
            g.k = Math.max(0.1, r.width / 120);
        }
        const r = carafe.getBoundingClientRect();
        const s = Math.max(0.1, r.height / 360);
        geo = {
            s, top: r.top, left: r.left, floor: r.bottom,
            open: {x: r.left + CARAFE.openX * s, y: r.top + CARAFE.openY * s},
            surfaceY: f => r.top + carafeY(f) * s,
        };
    }
    measure();
    addEventListener('resize', measure);

    // The pouring rim (top right corner of the glass) relative to the glass centre.
    const lipAt = (g, tilt) => rot({x: (RIM[1][0] - 60) * g.k, y: (RIM_Y - 80) * g.k}, tilt);
    const lip = g => {
        const o = lipAt(g, g.tilt);
        return {x: g.home.x + g.off.x + o.x, y: g.home.y + g.off.y + o.y};
    };
    // Offset that puts the rim just above the opening at full pour tilt.
    const pourOffset = g => {
        const o = lipAt(g, POUR_TILT);
        return {x: geo.open.x - 6 * geo.s - o.x - g.home.x, y: geo.open.y - 14 * geo.s - o.y - g.home.y};
    };
    // 1 where the glass would pour, 0 from TIP_RANGE away (carafe units): it tips only right at the
    // opening, as a hand would, and stays upright while carried across.
    const TIP_NEAR = 30, TIP_RANGE = 150;
    const approach = g => {
        const p = pourOffset(g);
        const d = Math.hypot(g.off.x - p.x, g.off.y - p.y) / Math.max(0.1, geo.s);
        return clamp(1 - (d - TIP_NEAR) / TIP_RANGE, 0, 1);
    };
    // A point of the glass (its viewBox) on the screen, as the glass is now.
    const glassPoint = (g, [x, y]) => {
        const o = rot({x: (x - 60) * g.k, y: (y - 80) * g.k}, g.tilt);
        return {x: g.home.x + g.off.x + o.x, y: g.home.y + g.off.y + o.y};
    };

    // Spilt water: drops that fall from the rim and vanish at the table. Not counted.
    const dropLayer = document.getElementById('drops');
    const drops = [];
    // A splash drop starts inside the carafe and just falls back into its water. A drop with a
    // `life` (s) is spray inside a glass: it vanishes when it is back down at the water.
    function makeDrop(x, y, vx, vy, r, splash = false, life = 0) {
        if (drops.length >= 50) return;
        const el = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        el.setAttribute('r', r.toFixed(1));
        dropLayer.appendChild(el);
        drops.push({el, x, y, vx, vy, r, inside: splash, splash, life});
    }
    // Water that runs up a glass wall fast is thrown off it as spray, and falls back in.
    // At the wall the surface is screen-aligned: the water frame is the glass turned back by its tilt.
    const SPRAY_FROM = 180;   // climb speed (glass viewBox units/s) where spray starts
    function spray(g, dt, level, wl, wr) {
        for (const side of [-1, 1]) {
            const up = g.slosh.climb(side);
            const i = side < 0 ? 0 : 1;
            g.spray[i] = up > SPRAY_FROM ? g.spray[i] + dt * Math.min(50, (up - SPRAY_FROM) * 0.25) : 0;
            for (; g.spray[i] >= 1; g.spray[i]--) {
                const x = side < 0 ? wl + 2.5 : wr - 2.5, y = level.top + g.slosh.height(x, wl, wr) - 1;
                const base = rot({x: 0, y: 10}, g.tilt);
                const px = g.home.x + g.off.x + (x - 60 + base.x) * g.k;
                const py = g.home.y + g.off.y + (y - 90 + base.y) * g.k;
                const vy = -Math.min(up, 500) * (0.35 + Math.random() * 0.4) * g.k;
                const vx = -side * (15 + Math.random() * 55) * g.k;
                makeDrop(px, py, g.vel.x + vx, g.vel.y + vy, (0.7 + Math.random() * 1.0) * g.k,
                         false, 2 * -vy / Math.max(1, GRAVITY * geo.s));
            }
        }
    }
    function spillDrop(g, corner) {
        const p = glassPoint(g, RIM[corner]);
        const out = rot({x: corner ? 60 : -60, y: -30}, g.tilt);   // over the rim, away from the glass
        makeDrop(p.x, p.y, g.vel.x + out.x * g.k + (Math.random() - 0.5) * 40,
                 g.vel.y + out.y * g.k + (Math.random() - 0.5) * 40, (1.4 + Math.random() * 1.4) * g.k);
    }
    // Falls; through the opening into the carafe it ends at the water, otherwise at the table.
    function moveDrops(dt) {
        const water = geo.surfaceY(carafeLevel);
        for (let i = drops.length - 1; i >= 0; i--) {
            const d = drops[i];
            if (d.life && (d.life -= dt) <= 0) { d.el.remove(); drops.splice(i, 1); continue; }
            const above = d.y < geo.open.y;
            d.vy += GRAVITY * geo.s * dt;
            d.x += d.vx * dt; d.y += d.vy * dt;
            if (!d.life && above && d.y >= geo.open.y && Math.abs(d.x - geo.open.x) < CARAFE.neckHalf * geo.s) d.inside = true;
            const at = (d.x - geo.left) / Math.max(0.1, geo.s);
            if (d.inside ? d.vy > 0 && d.y > water + carafeSurface.heightAt(at) * geo.s : d.y > geo.floor) {
                if (d.inside && !d.splash) landed(d, at);
                d.el.remove(); drops.splice(i, 1); continue;
            }
            d.el.setAttribute('cx', d.x.toFixed(1));
            d.el.setAttribute('cy', d.y.toFixed(1));
        }
    }
    // A drop fell into the carafe water: a small dent, two tiny splashes, two bubbles.
    function landed(d, at) {
        carafeSurface.poke(at, d.r / Math.max(0.1, geo.s) * 14, 1);
        for (let k = 0; k < 2; k++) {
            splash(at, 0.45);
            bubble(at + (Math.random() - 0.5) * 4, 3 + Math.random() * 6, 0.7 + Math.random() * 0.8);
        }
    }

    // --- in the carafe: splashes, bubbles and foam where the water lands (viewBox units) ---
    const surfaceAt = x => carafeY(carafeLevel) + carafeSurface.heightAt(x);
    function splash(at, strength) {
        makeDrop(geo.left + at * geo.s, geo.top + (surfaceAt(at) - 1.5) * geo.s,
                 (Math.random() - 0.5) * 260 * strength * geo.s,
                 -(120 + Math.random() * 320) * strength * geo.s,
                 (1.0 + Math.random() * 1.4) * geo.s * Math.sqrt(strength), true);
    }
    const bubbleLayer = document.getElementById('bubbles');
    const foam = document.getElementById('foam');
    const bubbles = [];
    let foamAmount = 0, foamX = CARAFE.openX;
    function bubble(x, depth, r) {
        if (bubbles.length >= 36) return;
        const el = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        el.setAttribute('r', r.toFixed(2));
        bubbleLayer.appendChild(el);
        const y = Math.min(surfaceAt(x) + depth, CARAFE.emptyY - r - 2);
        bubbles.push({el, x, y, r, vy: -10, phase: Math.random() * 6, pop: 0});
    }
    // Bubbles rise faster the bigger they are, sway a little and pop at the surface.
    function moveBubbles(dt, s) {
        for (let i = bubbles.length - 1; i >= 0; i--) {
            const b = bubbles[i];
            if (b.pop) {
                b.pop += dt;
                if (b.pop > 0.09) { b.el.remove(); bubbles.splice(i, 1); continue; }
                b.el.setAttribute('r', (b.r * (1 + b.pop * 9)).toFixed(2));
                b.el.setAttribute('opacity', (1 - b.pop / 0.09).toFixed(2));
                continue;
            }
            b.vy = Math.max(-(30 + b.r * 22), b.vy - 140 * dt);
            b.y += b.vy * dt;
            const x = b.x + Math.sin(s * 9 + b.phase + b.y / 7) * b.r * 0.6;
            if (b.y - b.r <= surfaceAt(x)) { b.pop = 1e-3; b.y = surfaceAt(x) + b.r * 0.3; }
            b.el.setAttribute('cx', x.toFixed(1));
            b.el.setAttribute('cy', b.y.toFixed(1));
        }
    }
    // Where the stream lands: splashes and bubbles at a rate that follows its strength, and foam
    // that builds up there and, once the stream stops, spreads out and fades.
    let spawnSplash = 0, spawnBubble = 0;
    function churn(impact, dt) {
        if (impact) {
            const strength = clamp(impact.force / (IMPACT * 8), 0.3, 1.2);
            foamX = impact.x;
            foamAmount += (1 - foamAmount) * (1 - Math.exp(-dt * 6));
            for (spawnSplash += dt * 28 * strength; spawnSplash >= 1; spawnSplash--) splash(impact.x, strength);
            for (spawnBubble += dt * 40 * strength; spawnBubble >= 1; spawnBubble--) {
                bubble(impact.x + (Math.random() - 0.5) * 10, 6 + Math.random() * 45 * strength,
                       0.8 + Math.random() * 2.4);
            }
        } else {
            foamAmount *= Math.exp(-dt * 2.4);
        }
        if (foamAmount < 0.02) { foam.setAttribute('opacity', '0'); return; }
        const half = 12 + 26 * (1 - foamAmount);
        let d = '';
        for (let x = Math.max(23, foamX - half); x <= Math.min(177, foamX + half); x += 3) {
            d += `${d ? ' L' : 'M'}${x.toFixed(1)} ${(surfaceAt(x) - 0.4).toFixed(2)}`;
        }
        foam.setAttribute('d', d);
        foam.setAttribute('opacity', (foamAmount * 0.8).toFixed(2));
    }
    const nearOpening = (g, factor = 1) => {
        const p = lip(g);
        return Math.abs(p.x - geo.open.x) < (CARAFE.neckHalf + 18) * geo.s * factor
            && p.y > geo.open.y - 90 * geo.s * factor && p.y < geo.open.y + 30 * geo.s;
    };

    // --- pick up, carry, pour ---
    let held = null;
    let committed = false;
    let pour = null;   // {g, start, fromMl, toMl}

    for (const g of glasses) {
        g.el.addEventListener('pointerdown', e => {
            if (committed || held || e.button !== 0) return;
            e.preventDefault();
            g.el.setPointerCapture(e.pointerId);
            g.grab = {x: e.clientX - (g.home.x + g.off.x), y: e.clientY - (g.home.y + g.off.y)};
            g.mode = 'held';
            held = g;
            g.el.classList.add('held');
            document.body.classList.add('carrying');
        });
        g.el.addEventListener('pointermove', e => {
            if (held !== g) return;
            g.want = {x: e.clientX - g.grab.x - g.home.x, y: e.clientY - g.grab.y - g.home.y};
        });
        const release = e => {
            if (held !== g) return;
            letGo(g);
            if (e.type === 'pointerup' && !committed && nearOpening(g, 1.6)) startPour(g);
            else if (!committed) { g.mode = 'back'; g.want = {x: 0, y: 0}; }
        };
        g.el.addEventListener('pointerup', release);
        g.el.addEventListener('pointercancel', release);
    }
    function letGo(g) {
        held = null;
        g.el.classList.remove('held');
        document.body.classList.remove('carrying');
    }

    addEventListener('keydown', e => {
        const g = glasses.find(g => g.key === e.key);
        if (!g || committed || held) return;
        committed = true;
        g.mode = 'fly';
        document.body.classList.add('pouring');
        g.el.classList.add('pouring');
        shelf.classList.add('done');
        actions.classList.add('gone');
    });

    async function startPour(g) {
        committed = true;
        document.body.classList.add('pouring');
        if (held === g) letGo(g);
        g.mode = 'pour';
        g.el.classList.add('pouring');
        shelf.classList.add('done');
        actions.classList.add('gone');
        let landedAll;
        pour = {g, start: performance.now(), fromMl: shownMl, toMl: shownMl + g.ml, area: g.area,
                drips: [...DRIPS], finished: new Promise(r => { landedAll = r; })};
        pour.finish = landedAll;
        const savePromise = api.log_water(g.ml).then(res => ({saved: true, state: res}))
            .catch(() => ({saved: false, state: null}));
        await Promise.race([pour.finished, R2R.wait(4000)]);
        const {saved, state: newState} = await Promise.race([savePromise, R2R.wait(1500)])
            || {saved: false, state: null};
        if (saved && newState) {
            state = newState;
            title.textContent = state.today_ml >= state.goal_ml ? 'Goal reached' : `+${g.ml} ml`;
            showAmount(state.today_ml);
            await R2R.wait(CLOSE_AFTER);
        } else {
            title.textContent = 'Could not save';
            await R2R.wait(1500);
        }
        R2R.close();
    }

    let snoozed = false;
    document.getElementById('later').addEventListener('click', () => {
        if (snoozed || committed || R2R._closing) return;
        snoozed = true;
        actions.classList.add('gone');
        if (held) letGo(held);
        for (const g of glasses) {
            if (g.mode !== 'rest') {
                g.mode = 'rest';
                g.off = {x: 0, y: 0};
                g.vel = {x: 0, y: 0};
                g.tilt = 0;
                g.slosh.reset();
            }
        }
        animating = false;
        api.snooze();
    });

    window.addEventListener('remind2rest:resume', async () => {
        snoozed = false;
        committed = false;
        pour = null;
        try {
            state = await api.get_water_today();
            shownMl = Number(state.today_ml) || 0;
            showAmount(shownMl);
            if (shownMl >= goal()) title.textContent = 'Goal reached';
        } catch (e) {}
        actions.classList.remove('gone');
        shelf.classList.remove('done');
        for (const g of glasses) {
            g.area = FULL_AREA;
            g.spilled = 0;
            g.mode = 'rest';
            g.off = {x: 0, y: 0};
            g.vel = {x: 0, y: 0};
            g.tilt = 0;
            g.slosh.reset();
            g.el.classList.remove('held', 'pouring');
            delete g._restCache;
        }
        measure();
        if (!animating) {
            animating = true;
            last = performance.now();
            requestAnimationFrame(frame);
        }
    });

    // --- physics, in small fixed steps so it is stable at any frame rate ---
    let animating = true;
    const SPRING = {held: [900, 60], back: [220, 26], fly: [260, 32], pour: [260, 32], rest: [220, 26]};
    function step(g, dt) {
        if (g.mode === 'fly' || g.mode === 'pour') g.want = pourOffset(g);
        const [k, c] = SPRING[g.mode];
        const ax = k * (g.want.x - g.off.x) - c * g.vel.x;
        const ay = k * (g.want.y - g.off.y) - c * g.vel.y;
        g.vel.x += ax * dt; g.vel.y += ay * dt;
        g.off.x += g.vel.x * dt; g.off.y += g.vel.y * dt;

        // Tilt: carried, it tips further the closer it gets to the carafe; pouring, all the way.
        let tiltGoal = 0, rate = 10;
        if (g.mode === 'held') tiltGoal = MAX_CARRY_TILT * smooth(approach(g)) + clamp(g.vel.x * 0.006, -7, 7);
        else if (g.mode === 'back') tiltGoal = MAX_CARRY_TILT * smooth(approach(g));
        else if (g.mode === 'fly') { tiltGoal = MAX_CARRY_TILT * smooth(approach(g)); rate = 14; }
        else if (g.mode === 'pour') { tiltGoal = POUR_TILT; rate = 9; }
        g.tilt += (tiltGoal - g.tilt) * (1 - Math.exp(-dt * rate));

        // The water feels the glass's acceleration (screen px -> glass viewBox units).
        g.slosh.step(dt, ax / g.k, ay / g.k, g.L, g.depth);

        if (g.mode === 'back' && Math.hypot(g.off.x, g.off.y) < 0.5 && Math.hypot(g.vel.x, g.vel.y) < 5) {
            g.mode = 'rest'; g.off = {x: 0, y: 0}; g.vel = {x: 0, y: 0}; g.tilt = 0;
        }
        if (g.mode === 'held' && g.tilt > 62 && nearOpening(g)) startPour(g);
        if (g.mode === 'fly' && Math.hypot(g.want.x - g.off.x, g.want.y - g.off.y) < 30 * geo.s) startPour(g);
    }

    let carafeLevel = 0;
    const carafeSurface = new Surface(22, 178, 32, {speed: 160, rest: 3, damping: 2.2, limit: 9});
    // The stream: water leaves the rim at each moment tau of the flow with its own speed and then
    // falls freely, so the stream is a parabola. Same flow, more speed: it gets thinner as it falls.
    // When the flow ends, its end lets go of the rim and falls after it; then a few drops drip.
    // Returns where it hits the carafe water (viewBox x) and how hard, or null.
    const STREAM_SAMPLES = 22;
    function drawStream(es) {
        const g = pour.g, [fs, fe] = FLOW;
        const share = tau => clamp((tau - fs) / (fe - fs), 0, 1);
        g.area = pour.area * (1 - poured(share(es)));   // whatever was spilt, the glass counts as full
        const G = GRAVITY * geo.s;
        const a = lip(g);
        const dir = rot({x: 0, y: -1}, g.tilt);   // over the rim, along the glass wall
        const fall = Math.max(4 * geo.s, geo.surfaceY(carafeLevel) - a.y);
        // Faster while much flows; capped so that it lands well inside the carafe.
        const vMax = 30 * geo.s /Math.max(0.02, Math.abs(dir.x) * Math.sqrt(2 * fall / G));
        const speedOf = q => Math.min(vMax, (70 + 150 * Math.sqrt(q)) * geo.s);
        const landAge = v => (-dir.y * v + Math.sqrt((dir.y * v) ** 2 + 2 * G * fall)) / G;
        const parcel = tau => {
            const q = tau < fs || tau > fe ? 0 : flowRate(share(tau));
            const v = speedOf(q);
            return {q, v, land: landAge(v)};
        };

        // The carafe gets what has landed by now.
        const arrived = poured(share(es - parcel(es - landAge(speedOf(0.5))).land));
        shownMl = pour.fromMl + (pour.toMl - pour.fromMl) * arrived;
        if (!pour.done) showAmount(shownMl);

        // Parcels in the air: left the rim between tauLo (lowest) and tauHi (at the rim).
        const tauHi = Math.min(es, fe);
        let tauLo = Math.max(fs, es - parcel(es - landAge(speedOf(0.5))).land);
        tauLo = Math.max(fs, es - parcel(tauLo).land);
        let impact = null;
        if (tauHi - tauLo > 0.004) {
            const wBase = (3.5 + g.ml / 140) * geo.s * 1.3;
            const left = [], right = [], shineL = [], shineR = [];
            let tip = null;
            for (let i = 0; i <= STREAM_SAMPLES; i++) {
                const tau = tauHi - (tauHi - tauLo) * i / STREAM_SAMPLES;
                const p = parcel(tau);
                const age = Math.min(es - tau, p.land);
                const vx = dir.x * p.v, vy = dir.y * p.v + G * age;
                const speed = Math.hypot(vx, vy) || 1;
                const nx = -vy / speed, ny = vx / speed;   // across the stream, to its left
                const thin = Math.max(0.32, Math.sqrt(p.v / speed));
                const tremble = 1 + 0.12 * Math.sin(tau * 70) + 0.06 * Math.sin(tau * 131 + 2);
                const hw = Math.max(0.5, 0.5 * wBase * Math.sqrt(p.q) * thin * tremble);
                const sway = Math.sin(tau * 43 + 1) * age * 9 * geo.s;
                const x = a.x + dir.x * p.v * age + nx * sway;
                const y = a.y + dir.y * p.v * age + G * age * age / 2 + ny * sway;
                left.push([x + nx * hw, y + ny * hw]);
                right.push([x - nx * hw, y - ny * hw]);
                shineL.push([x + nx * hw * 0.55, y + ny * hw * 0.55]);
                shineR.push([x + nx * hw * 0.15, y + ny * hw * 0.15]);
                tip = {x, y, hw, ux: vx / speed, uy: vy / speed, reached: es - tau >= p.land, q: p.q};
            }
            const outline = (l, r, cap) => {
                const pts = n => n.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(' L');
                return `M${pts(l)} Q${(tip.x + tip.ux * cap).toFixed(1)} ${(tip.y + tip.uy * cap).toFixed(1)} `
                    + `${pts(r.reverse())}Z`;
            };
            stream.setAttribute('d', outline(left, right, tip.hw * 1.6));
            streamCore.setAttribute('d', outline(shineL, shineR, tip.hw * 0.4));
            if (tip.reached && tip.q > 0.02) {
                impact = {x: (tip.x - geo.left) / geo.s, force: IMPACT * wBase * Math.sqrt(tip.q) / geo.s};
            }
        } else {
            stream.removeAttribute('d'); streamCore.removeAttribute('d');
        }

        // The last drops from the rim, after the flow.
        while (pour.drips.length && es >= fe + pour.drips[0]) {
            pour.drips.shift();
            makeDrop(a.x, a.y, dir.x * 30 * geo.s + (Math.random() - 0.5) * 10,
                     dir.y * 30 * geo.s, (1.7 + Math.random() * 0.9) * g.k);
        }
        if (!pour.done && !pour.drips.length && es > fe + 0.05 && tauHi - tauLo <= 0.004 && !drops.length) {
            pour.done = true;
            pour.finish();
        }
        return impact;
    }

    let last = performance.now();
    const frame = t => {
        const dt = Math.min(0.1, (t - last) / 1000);
        last = t;
        const s = t / 900;

        // Pour progress drives the glass level, the carafe amount and the stream.
        let impact = null;   // where the stream lands on the carafe surface (viewBox x) and how hard
        if (pour) impact = drawStream((t - pour.start) / 1000);
        else { stream.removeAttribute('d'); streamCore.removeAttribute('d'); }

        for (const g of glasses) {
            for (let left = dt; left > 1e-6; left -= 1 / 240) step(g, Math.min(left, 1 / 240));
            g.art.style.transform = g.mode === 'rest' ? ''
                : `translate(${g.off.x}px, ${g.off.y}px) rotate(${g.tilt}deg)`;
            // Water rotated back by the glass tilt: level, with the slosh drawn on top.
            g.water.setAttribute('transform', `rotate(${(-g.tilt).toFixed(2)} 60 90)`);
            // Same amount of water at any angle; sloshing or tipped too far, the excess runs out as drops.
            let level, wl, wr, w;
            if (g.mode === 'rest' && Math.abs(g.tilt) < 0.01 && Math.abs(g.slosh.a[0]) < 0.01 && g._restCache && g._restCache.area === g.area) {
                ({level, wl, wr, w} = g._restCache);
            } else {
                level = tiltedWater(g.area, -g.tilt);
                [wl, wr] = wallsAt(-g.tilt, level.top);
                g.L = wr - wl; g.depth = Math.max(5, g.area / g.L);
                w = tiltedWater(g.area, g.slosh.angle(g.L) - g.tilt);
                if (g.mode === 'rest' && Math.abs(g.tilt) < 0.01 && Math.abs(g.slosh.a[0]) < 0.01) {
                    g._restCache = {area: g.area, level, wl, wr, w};
                }
            }
            if ((g.mode === 'held' || g.mode === 'back') && g.area > w.capacity) {
                g.spilled += g.area - w.capacity;
                g.area = w.capacity;
            }
            for (; g.spilled >= SPILL_DROP_AREA; g.spilled -= SPILL_DROP_AREA) spillDrop(g, w.spillCorner);
            if (g.mode === 'held' || g.mode === 'back') spray(g, dt, level, wl, wr);
            g.wave.setAttribute('d', g.slosh.path(level.top, wl, wr, -60, 180, 260,
                {extra: x => Math.sin(x / 14 + s + g.phase) * 0.5}));
            g.waveBack.setAttribute('d', g.slosh.path(level.top - 1.7, wl, wr, -60, 180, 260,
                {scale: 0.85, extra: x => Math.sin(x / 14 - s * 1.3 + 1 + g.phase) * 0.7}));
        }

        moveDrops(dt);

        // Carafe: eases to today's amount; where the stream lands it pushes the surface down, and
        // the dent runs out as rings that bounce off the walls.
        const f = Math.min(CARAFE_MAX_FILL, shownMl / goal());
        carafeLevel += (f - carafeLevel) * (1 - Math.exp(-dt * (pour ? 14 : 3)));
        for (let left = dt; left > 1e-6; left -= 1 / 240) {
            const h = Math.min(left, 1 / 240);
            if (impact) carafeSurface.poke(impact.x, impact.force * h, 2);
            carafeSurface.step(h);
        }
        churn(impact, dt);
        moveBubbles(dt, s);
        const y = carafeY(carafeLevel);
        carafeWater.setAttribute('d', carafeSurface.path(y, -10, 210, 370,
            {extra: x => Math.sin(x / 18 + s * 1.1) * 0.5}));
        carafeBack.setAttribute('d', carafeSurface.path(y - 1.5, -10, 210, 370,
            {mirror: true, scale: 0.6, extra: x => Math.sin(x / 18 - s * 1.4 + 2) * 0.7}));

        if (animating) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
})();
