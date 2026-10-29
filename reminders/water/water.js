// Same glass outline for every size; the buttons scale it via CSS.
const OUTLINE = 'M14 10 L106 10 L96 146 Q95 152 89 152 L31 152 Q25 152 24 146 Z';
const FULL = 0.74;   // water level of a glass waiting to be drunk
const EMPTY = 0.04;

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

// Water surface between x=-40 and 160 so it still fills the glass when counter-rotated.
function wavePath(h, phase, amp) {
    const top = 152 - h * 142;
    let d = `M-40 ${top}`;
    for (let x = -40; x <= 160; x += 8) d += ` L${x} ${top + Math.sin(x / 14 + phase) * amp}`;
    return d + ' L160 220 L-40 220 Z';
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

(async () => {
    const api = await R2R.api;
    const status = document.getElementById('status');
    const fill = document.getElementById('fill');
    const row = document.getElementById('glasses');
    const actions = document.getElementById('actions');

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

    // --- three glasses; each drawing drifts and leans towards the cursor inside its fixed button ---
    const glasses = [...row.querySelectorAll('.glass')].map(button => {
        const ml = Number(button.dataset.ml);
        button.innerHTML = `<div class="lift"><div class="art">${glassSvg(ml)}</div></div>`
            + `<span class="label">${ml} ml</span>`;
        return {
            ml, button,
            art: button.querySelector('.art'),
            water: button.querySelector('.water'),
            wave: button.querySelector('.wave'),
            waveBack: button.querySelector('.wave-back'),
            pos: {x: 0, y: 0},
            level: 0,
            goal: FULL,
            phase: ml / 97,
        };
    });

    let cursor = null;
    addEventListener('pointermove', e => { cursor = {x: e.clientX, y: e.clientY}; });

    // Time-based easing, so the glasses move the same at any refresh rate.
    const ease = (dt, perSecond) => 1 - Math.exp(-dt * perSecond);
    let last = performance.now();
    const frame = t => {
        const dt = Math.min(0.1, (t - last) / 1000);
        last = t;
        const s = t / 900;
        for (const g of glasses) {
            // Target offset: a little towards the cursor, at most a few px, so the glass
            // never leaves its button.
            let tx = 0, ty = 0, lean = 0;
            if (cursor) {
                const r = g.button.getBoundingClientRect();
                const dx = cursor.x - (r.left + r.width / 2);
                const dy = cursor.y - (r.top + r.height / 2);
                tx = clamp(dx * 0.035, -18, 18);
                ty = clamp(dy * 0.03, -12, 12);
                lean = clamp(dx * 0.006, -5, 5);
            }
            const k = ease(dt, 5);
            const lagX = tx - g.pos.x;
            g.pos.x += lagX * k;
            g.pos.y += (ty - g.pos.y) * k;
            // Leaning towards the cursor plus a swing from the lag, like the single glass had.
            const tilt = clamp(lean + lagX * 0.6, -12, 12);
            g.art.style.transform = `translate(${g.pos.x}px, ${g.pos.y}px) rotate(${tilt}deg)`;
            g.water.setAttribute('transform', `rotate(${-tilt} 60 90)`);

            g.level += (g.goal - g.level) * ease(dt, g.goal === EMPTY ? 9 : 2.5);
            const slosh = Math.min(3, Math.abs(lagX) * 0.25);
            g.wave.setAttribute('d', wavePath(g.level, s + g.phase, 2.6 + slosh));
            g.waveBack.setAttribute('d', wavePath(g.level + 0.015, -s * 1.3 + 1 + g.phase, 3.2 + slosh));
        }
        requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);

    // --- actions: show the result briefly, then close ---
    let busy = false;
    async function drank(g) {
        if (busy) return;
        busy = true;
        row.classList.add('done');
        g.button.classList.add('chosen');
        g.goal = EMPTY;
        actions.classList.add('gone');
        const shown = R2R.wait(550);
        const title = document.getElementById('title');
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
    for (const g of glasses) g.button.addEventListener('click', () => drank(g));
    document.getElementById('later').addEventListener('click', () => api.snooze(5));
})();
