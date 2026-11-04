// Same glass outline for every size; CSS sets the height.
const OUTLINE = 'M14 10 L106 10 L96 146 Q95 152 89 152 L31 152 Q25 152 24 146 Z';
const FULL = 0.74;      // water level of a glass waiting to be drunk
const EMPTY = 0.0;
const POUR_MS = 650;    // stream running, glass emptying, carafe rising
const CLOSE_AFTER = 250; // after the pour, then close
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
    ...curve(50, lerp2([36, 146], [46, 10])),
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
        <path d="M28 24 L23.5 90" stroke="rgba(255,255,255,0.35)" stroke-width="4" stroke-linecap="round"/>
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

const glassTop = level => 152 - level * 142;

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
            tilt: 0, slosh: 0, sloshVel: 0,
            surface: new Surface(14, 106, 16, {speed: 110, rest: 6, damping: 2.4, limit: 6}),
            level: FULL, phase: ml / 97,
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
            g.k = r.width / 120;
        }
        const r = carafe.getBoundingClientRect();
        const s = r.height / 360;
        geo = {
            s, top: r.top, left: r.left,
            open: {x: r.left + CARAFE.openX * s, y: r.top + CARAFE.openY * s},
            surfaceY: f => r.top + carafeY(f) * s,
        };
    }
    measure();
    addEventListener('resize', measure);

    // The pouring rim (top right corner of the glass) relative to the glass centre.
    const lipAt = (g, tilt) => rot({x: 46 * g.k, y: -70 * g.k}, tilt);
    const lip = g => {
        const o = lipAt(g, g.tilt);
        return {x: g.home.x + g.off.x + o.x, y: g.home.y + g.off.y + o.y};
    };
    // Offset that puts the rim just above the opening at full pour tilt.
    const pourOffset = g => {
        const o = lipAt(g, POUR_TILT);
        return {x: geo.open.x - 6 * geo.s - o.x - g.home.x, y: geo.open.y - 14 * geo.s - o.y - g.home.y};
    };
    // 0 at the shelf, 1 where the glass would pour: tilt follows it.
    const approach = g => {
        const x0 = g.home.x + 40, x1 = g.home.x + pourOffset(g).x;
        return clamp((g.home.x + g.off.x - x0) / Math.max(1, x1 - x0), 0, 1);
    };
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
        pour = {g, start: performance.now(), fromMl: shownMl, toMl: shownMl + g.ml, level: g.level};
        let saved = true;
        try {
            state = await api.log_water(g.ml);
        } catch (e) {
            saved = false;
        }
        await R2R.wait(Math.max(0, pour.start + POUR_MS - performance.now()));
        title.textContent = !saved ? 'Could not save'
            : state.today_ml >= state.goal_ml ? 'Goal reached' : `+${g.ml} ml`;
        if (saved) showAmount(state.today_ml);
        await R2R.wait(CLOSE_AFTER);
        api.close();
    }

    document.getElementById('later').addEventListener('click', () => {
        actions.classList.add('gone');
        if (held) letGo(held);
        for (const g of glasses) {
            if (g.mode !== 'rest') {
                g.mode = 'rest';
                g.off = {x: 0, y: 0};
                g.vel = {x: 0, y: 0};
                g.tilt = 0;
                g.slosh = 0;
                g.sloshVel = 0;
            }
        }
        animating = false;
        api.snooze();
    });

    window.addEventListener('remind2rest:resume', async () => {
        try {
            state = await api.get_water_today();
            shownMl = Number(state.today_ml) || 0;
            showAmount(shownMl);
            if (shownMl >= goal()) title.textContent = 'Goal reached';
        } catch (e) {}
        actions.classList.remove('gone');
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

        // Surface angle (world frame, + = clockwise): underdamped spring driven by the acceleration.
        const push = g.mode === 'rest' ? 0 : ax * 0.16;  // accelerating right piles water up on the left
        g.sloshVel += (-160 * g.slosh - 16 * g.sloshVel + push) * dt;  // well damped: settles in ~0.4 s
        g.slosh = clamp(g.slosh + g.sloshVel * dt, -9, 9);
        // The same push makes ripples on top: water runs up the trailing wall and back.
        if (push) g.surface.push(x => (x - 60) / 46 * push * 0.8, dt);
        g.surface.step(dt);

        if (g.mode === 'back' && Math.hypot(g.off.x, g.off.y) < 0.5 && Math.hypot(g.vel.x, g.vel.y) < 5) {
            g.mode = 'rest'; g.off = {x: 0, y: 0}; g.vel = {x: 0, y: 0}; g.tilt = 0;
        }
        if (g.mode === 'held' && g.tilt > 62 && nearOpening(g)) startPour(g);
        if (g.mode === 'fly' && Math.hypot(g.want.x - g.off.x, g.want.y - g.off.y) < 30 * geo.s) startPour(g);
    }

    let carafeLevel = 0;
    const carafeSurface = new Surface(22, 178, 32, {speed: 160, rest: 3, damping: 2.2, limit: 9});
    let last = performance.now();
    const frame = t => {
        const dt = Math.min(0.1, (t - last) / 1000);
        last = t;
        const s = t / 900;

        // Pour progress drives the glass level, the carafe amount and the stream.
        let streamOn = false;
        let impact = null;   // where the stream lands on the carafe surface (viewBox x) and how hard
        if (pour) {
            const e = t - pour.start;
            const p = clamp((e - 60) / (POUR_MS - 60), 0, 1);
            pour.g.level = pour.level + (EMPTY - pour.level) * p;
            shownMl = pour.fromMl + (pour.toMl - pour.fromMl) * smooth(clamp((e - 120) / (POUR_MS - 120), 0, 1));
            if (e < POUR_MS + CLOSE_AFTER) showAmount(shownMl);
            const head = clamp(e / 140, 0, 1);
            const tail = clamp((e - POUR_MS + 80) / 200, 0, 1);
            streamOn = head > tail;
            if (streamOn) {
                const a = lip(pour.g);
                const fillF = shownMl / goal();
                const end = {x: geo.open.x + Math.sin(t / 60) * 1.5, y: geo.surfaceY(fillF) + 4};
                const d = `M${a.x} ${a.y} Q${a.x + 10 * geo.s} ${a.y + 10 * geo.s} ${end.x} ${Math.max(end.y, a.y + 10)}`;
                const w = (3.5 + pour.g.ml / 140) * geo.s * (1 - 0.6 * tail);
                for (const [path, width] of [[stream, w], [streamCore, w * 0.35]]) {
                    path.setAttribute('d', d);
                    path.setAttribute('stroke-width', width);
                    path.setAttribute('stroke-dasharray', `${head - tail} 2`);
                    path.setAttribute('stroke-dashoffset', `${-tail}`);
                }
                if (head >= 1) impact = {x: (end.x - geo.left) / geo.s, force: IMPACT * w / geo.s};
            }
        }
        if (!streamOn) { stream.removeAttribute('d'); streamCore.removeAttribute('d'); }

        for (const g of glasses) {
            for (let left = dt; left > 1e-6; left -= 1 / 240) step(g, Math.min(left, 1 / 240));
            g.art.style.transform = g.mode === 'rest' ? ''
                : `translate(${g.off.x}px, ${g.off.y}px) rotate(${g.tilt}deg)`;
            // Water rotated back by the glass tilt (stays level) plus the slosh.
            g.water.setAttribute('transform', `rotate(${(g.slosh - g.tilt).toFixed(2)} 60 90)`);
            g.wave.setAttribute('d', g.surface.path(glassTop(g.level), -60, 180, 260,
                {extra: x => Math.sin(x / 14 + s + g.phase) * 0.6}));
            g.waveBack.setAttribute('d', g.surface.path(glassTop(g.level + 0.012), -60, 180, 260,
                {mirror: true, scale: 0.7, extra: x => Math.sin(x / 14 - s * 1.3 + 1 + g.phase) * 0.8}));
        }

        // Carafe: eases to today's amount; where the stream lands it pushes the surface down, and
        // the dent runs out as rings that bounce off the walls.
        const f = Math.min(CARAFE_MAX_FILL, shownMl / goal());
        carafeLevel += (f - carafeLevel) * (1 - Math.exp(-dt * (pour ? 14 : 3)));
        for (let left = dt; left > 1e-6; left -= 1 / 240) {
            const h = Math.min(left, 1 / 240);
            if (impact) carafeSurface.poke(impact.x, impact.force * h, 2);
            carafeSurface.step(h);
        }
        const y = carafeY(carafeLevel);
        carafeWater.setAttribute('d', carafeSurface.path(y, -10, 210, 370,
            {extra: x => Math.sin(x / 18 + s * 1.1) * 0.5}));
        carafeBack.setAttribute('d', carafeSurface.path(y - 1.5, -10, 210, 370,
            {mirror: true, scale: 0.6, extra: x => Math.sin(x / 18 - s * 1.4 + 2) * 0.7}));

        if (animating) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
})();
