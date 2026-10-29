// Same glass outline for every size; CSS sets the height.
const OUTLINE = 'M14 10 L106 10 L96 146 Q95 152 89 152 L31 152 Q25 152 24 146 Z';
const FULL = 0.74;      // water level of a glass waiting to be drunk
const EMPTY = 0.0;
const POUR_MS = 650;    // stream running, glass emptying, carafe rising
const CLOSE_AFTER = 250; // after the pour, then close
const POUR_TILT = 104;  // degrees, glass rim pointing down into the carafe
const MAX_CARRY_TILT = 86;
// Carafe geometry in its viewBox (0 0 200 360): opening at the top, water between EMPTY_Y and FULL_Y.
const CARAFE = {openX: 100, openY: 12, neckHalf: 20, emptyY: 342, fullY: 128};

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

// Glass water surface between x=-60 and 180 so it still fills the glass when rotated.
function wavePath(h, phase, amp) {
    const top = 152 - h * 142;
    let d = `M-60 ${top}`;
    for (let x = -60; x <= 180; x += 8) d += ` L${x} ${top + Math.sin(x / 14 + phase) * amp}`;
    return d + ' L180 260 L-60 260 Z';
}

function carafePath(y, phase, amp) {
    let d = `M-10 ${y}`;
    for (let x = -10; x <= 210; x += 10) d += ` L${x} ${y + Math.sin(x / 18 + phase) * amp}`;
    return d + ' L210 370 L-10 370 Z';
}

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
    try { state = await api.get_water_today(); } catch (e) { /* keep defaults */ }
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
        const y = CARAFE.emptyY - q * (CARAFE.emptyY - CARAFE.fullY);
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
            level: FULL, phase: ml / 97,
            home: null, k: 1, grab: null,
        };
    });
    function measure() {
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
            surfaceY: f => r.top + (CARAFE.emptyY - f * (CARAFE.emptyY - CARAFE.fullY)) * s,
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
        return Math.hypot(p.x - geo.open.x, p.y - (geo.open.y - 20 * geo.s)) < 55 * geo.s * factor;
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

    document.getElementById('later').addEventListener('click', () => api.snooze(5));

    // --- physics, in small fixed steps so it is stable at any frame rate ---
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
        if (g.mode === 'held') tiltGoal = MAX_CARRY_TILT * smooth(approach(g)) + clamp(g.vel.x * 0.01, -12, 12);
        else if (g.mode === 'back') tiltGoal = MAX_CARRY_TILT * smooth(approach(g));
        else if (g.mode === 'fly') { tiltGoal = MAX_CARRY_TILT * smooth(approach(g)); rate = 14; }
        else if (g.mode === 'pour') { tiltGoal = POUR_TILT; rate = 9; }
        g.tilt += (tiltGoal - g.tilt) * (1 - Math.exp(-dt * rate));

        // Surface angle (world frame, + = clockwise): underdamped spring driven by the acceleration.
        const push = g.mode === 'rest' ? 0 : ax * 0.5;  // accelerating right piles water up on the left
        g.sloshVel += (-130 * g.slosh - 4.5 * g.sloshVel + push) * dt;
        g.slosh = clamp(g.slosh + g.sloshVel * dt, -30, 30);

        if (g.mode === 'back' && Math.hypot(g.off.x, g.off.y) < 0.5 && Math.hypot(g.vel.x, g.vel.y) < 5) {
            g.mode = 'rest'; g.off = {x: 0, y: 0}; g.vel = {x: 0, y: 0}; g.tilt = 0;
        }
        if (g.mode === 'held' && g.tilt > 62 && nearOpening(g)) startPour(g);
        if (g.mode === 'fly' && Math.hypot(g.want.x - g.off.x, g.want.y - g.off.y) < 30 * geo.s) startPour(g);
    }

    let carafeLevel = 0, wobble = 0;
    let last = performance.now();
    const frame = t => {
        const dt = Math.min(0.1, (t - last) / 1000);
        last = t;
        const s = t / 900;

        // Pour progress drives the glass level, the carafe amount and the stream.
        let streamOn = false;
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
                const fillF = Math.min(1, shownMl / goal());
                const end = {x: geo.open.x + Math.sin(t / 60) * 1.5, y: geo.surfaceY(fillF) + 4};
                const d = `M${a.x} ${a.y} Q${a.x + 10 * geo.s} ${a.y + 10 * geo.s} ${end.x} ${Math.max(end.y, a.y + 10)}`;
                const w = (3.5 + pour.g.ml / 140) * geo.s * (1 - 0.6 * tail);
                for (const [path, width] of [[stream, w], [streamCore, w * 0.35]]) {
                    path.setAttribute('d', d);
                    path.setAttribute('stroke-width', width);
                    path.setAttribute('stroke-dasharray', `${head - tail} 2`);
                    path.setAttribute('stroke-dashoffset', `${-tail}`);
                }
            }
        }
        if (!streamOn) { stream.removeAttribute('d'); streamCore.removeAttribute('d'); }

        for (const g of glasses) {
            for (let left = dt; left > 1e-6; left -= 1 / 240) step(g, Math.min(left, 1 / 240));
            g.art.style.transform = g.mode === 'rest' ? ''
                : `translate(${g.off.x}px, ${g.off.y}px) rotate(${g.tilt}deg)`;
            // Water rotated back by the glass tilt (stays level) plus the slosh.
            g.water.setAttribute('transform', `rotate(${(g.slosh - g.tilt).toFixed(2)} 60 90)`);
            const amp = Math.min(5, Math.abs(g.sloshVel) * 0.02);
            g.wave.setAttribute('d', wavePath(g.level, s + g.phase, 2.4 + amp));
            g.waveBack.setAttribute('d', wavePath(g.level + 0.015, -s * 1.3 + 1 + g.phase, 3 + amp));
        }

        // Carafe: eases to today's amount; the stream stirs the surface.
        const f = Math.min(1, shownMl / goal());
        carafeLevel += (f - carafeLevel) * (1 - Math.exp(-dt * (pour ? 14 : 3)));
        wobble += ((streamOn ? 5 : 0) - wobble) * (1 - Math.exp(-dt * (streamOn ? 12 : 2.5)));
        const y = CARAFE.emptyY - carafeLevel * (CARAFE.emptyY - CARAFE.fullY);
        carafeWater.setAttribute('d', carafePath(y, s * 1.4, 1.6 + wobble));
        carafeBack.setAttribute('d', carafePath(y - 2, -s * 1.8 + 2, 2.2 + wobble * 1.2));

        requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
})();
