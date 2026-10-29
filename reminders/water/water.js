// Same glass outline for every size; CSS scales it.
const OUTLINE = 'M14 10 L106 10 L96 146 Q95 152 89 152 L31 152 Q25 152 24 146 Z';
const FULL = 0.74;   // water level of a glass waiting to be drunk
const EMPTY = 0.03;
const DRINK_MS = 420; // from drop to close: fly in, tip, drain

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

// Water surface between x=-60 and 180 so it still fills the glass when rotated.
function wavePath(h, phase, amp) {
    const top = 152 - h * 142;
    let d = `M-60 ${top}`;
    for (let x = -60; x <= 180; x += 8) d += ` L${x} ${top + Math.sin(x / 14 + phase) * amp}`;
    return d + ' L180 260 L-60 260 Z';
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const center = el => { const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; };

(async () => {
    const api = await R2R.api;
    const status = document.getElementById('status');
    const fill = document.getElementById('fill');
    const row = document.getElementById('glasses');
    const target = document.getElementById('target');
    const actions = document.getElementById('actions');
    const title = document.getElementById('title');

    let state = {today_ml: 0, goal_ml: 2000};
    try { state = await api.get_water_today(); } catch (e) { /* keep defaults */ }

    function render() {
        const today = Number(state.today_ml) || 0;
        const goal = Math.max(1, Number(state.goal_ml) || 2000);
        status.textContent = today === 0 ? `Nothing yet today. Goal: ${goal} ml.`
            : today >= goal ? `${today} ml today. Goal of ${goal} ml reached.`
            : `${today} of ${goal} ml today`;
        fill.style.width = `${Math.min(1, today / goal) * 100}%`;
    }
    render();

    // Each glass: offset from its home spot (spring-driven), glass tilt, and the water
    // surface angle as a damped spring pushed by the glass's horizontal acceleration.
    const glasses = [...row.querySelectorAll('.glass')].map(el => {
        const ml = Number(el.dataset.ml);
        el.innerHTML = `<div class="lift"><div class="art">${glassSvg(ml)}</div></div>`
            + `<span class="label">${ml} ml</span>`;
        return {
            ml, el, key: el.dataset.key,
            art: el.querySelector('.art'),
            water: el.querySelector('.water'),
            wave: el.querySelector('.wave'),
            waveBack: el.querySelector('.wave-back'),
            mode: 'rest',          // rest | held | back | drink
            off: {x: 0, y: 0}, vel: {x: 0, y: 0}, want: {x: 0, y: 0},
            tilt: 0, slosh: 0, sloshVel: 0,
            level: FULL, levelGoal: FULL,
            phase: ml / 97,
            home: null, grab: null,
        };
    });

    // --- picking up, carrying, dropping ---
    let held = null;
    let done = false;

    const overTarget = (x, y) => {
        const r = target.getBoundingClientRect();
        const c = {x: r.left + r.width / 2, y: r.top + r.height / 2};
        return Math.hypot(x - c.x, y - c.y) < r.width * 0.62;  // a little generous
    };

    for (const g of glasses) {
        g.el.addEventListener('pointerdown', e => {
            if (done || held || e.button !== 0) return;
            e.preventDefault();
            g.el.setPointerCapture(e.pointerId);
            const c = center(g.art);
            g.home = {x: c.x - g.off.x, y: c.y - g.off.y};
            g.grab = {x: e.clientX - c.x, y: e.clientY - c.y};
            g.mode = 'held';
            held = g;
            g.el.classList.add('held');
            document.body.classList.add('carrying');
        });
        g.el.addEventListener('pointermove', e => {
            if (held !== g) return;
            g.want = {x: e.clientX - g.grab.x - g.home.x, y: e.clientY - g.grab.y - g.home.y};
            target.classList.toggle('over', overTarget(e.clientX, e.clientY));
        });
        const release = e => {
            if (held !== g) return;
            held = null;
            g.el.classList.remove('held');
            document.body.classList.remove('carrying');
            target.classList.remove('over');
            if (e.type === 'pointerup' && overTarget(e.clientX, e.clientY)) drink(g);
            else { g.mode = 'back'; g.want = {x: 0, y: 0}; }
        };
        g.el.addEventListener('pointerup', release);
        g.el.addEventListener('pointercancel', release);
    }

    addEventListener('keydown', e => {
        const g = glasses.find(g => g.key === e.key);
        if (g && !held) drink(g);
    });

    async function drink(g) {
        if (done) return;
        done = true;
        const c = center(g.art);
        g.home = g.home || {x: c.x - g.off.x, y: c.y - g.off.y};
        const t = center(target);
        g.want = {x: t.x - g.home.x, y: t.y - g.home.y};
        g.mode = 'drink';
        g.levelGoal = EMPTY;
        g.el.classList.add('drinking');
        row.classList.add('done');
        actions.classList.add('gone');
        target.classList.add('over');
        const shown = R2R.wait(DRINK_MS);
        try {
            state = await api.log_water(g.ml);
            title.textContent = state.today_ml >= state.goal_ml ? 'Goal reached' : `+${g.ml} ml`;
            render();
        } catch (e) {
            title.textContent = 'Could not save';
        }
        await shown;
        api.close();
    }

    document.getElementById('later').addEventListener('click', () => api.snooze(5));

    // --- physics, in small fixed steps so it is stable at any frame rate ---
    const SPRING = {held: [900, 60], back: [220, 26], drink: [500, 45], rest: [220, 26]};
    function step(g, dt) {
        const [k, c] = SPRING[g.mode];
        const ax = k * (g.want.x - g.off.x) - c * g.vel.x;
        const ay = k * (g.want.y - g.off.y) - c * g.vel.y;
        g.vel.x += ax * dt; g.vel.y += ay * dt;
        g.off.x += g.vel.x * dt; g.off.y += g.vel.y * dt;

        // Glass leans with its speed; when drinking it tips over.
        const tiltGoal = g.mode === 'drink' ? -58 : clamp(g.vel.x * 0.012, -16, 16);
        g.tilt += (tiltGoal - g.tilt) * (1 - Math.exp(-dt * (g.mode === 'drink' ? 14 : 10)));

        // Surface angle (world frame, + = clockwise): underdamped spring driven by the acceleration.
        const push = g.mode === 'rest' ? 0 : ax * 0.5;  // accelerating right piles water up on the left
        g.sloshVel += (-130 * g.slosh - 4.5 * g.sloshVel + push) * dt;
        g.slosh = clamp(g.slosh + g.sloshVel * dt, -30, 30);

        g.level += (g.levelGoal - g.level) * (1 - Math.exp(-dt * 7));

        if (g.mode === 'back' && Math.hypot(g.off.x, g.off.y) < 0.5 && Math.hypot(g.vel.x, g.vel.y) < 5) {
            g.mode = 'rest'; g.off = {x: 0, y: 0}; g.vel = {x: 0, y: 0};
        }
    }

    let last = performance.now();
    const frame = t => {
        let dt = Math.min(0.1, (t - last) / 1000);
        last = t;
        const s = t / 900;
        for (const g of glasses) {
            for (let left = dt; left > 1e-6; left -= 1 / 240) step(g, Math.min(left, 1 / 240));
            const moved = g.mode !== 'rest';
            g.art.style.transform = moved
                ? `translate(${g.off.x}px, ${g.off.y}px) rotate(${g.tilt}deg)` : '';
            // Water rotated back by the glass tilt (stays level) plus the slosh.
            g.water.setAttribute('transform', `rotate(${(g.slosh - g.tilt).toFixed(2)} 60 90)`);
            const amp = Math.min(5, Math.abs(g.sloshVel) * 0.02);
            g.wave.setAttribute('d', wavePath(g.level, s + g.phase, 2.4 + amp));
            g.waveBack.setAttribute('d', wavePath(g.level + 0.015, -s * 1.3 + 1 + g.phase, 3 + amp));
        }
        requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
})();
