(async () => {
    const api = await R2R.api;
    const glass = document.getElementById('glass');
    const water = document.getElementById('water');
    const wave = document.getElementById('wave');
    const waveBack = document.getElementById('waveBack');
    const status = document.getElementById('status');
    const row = document.getElementById('glasses');
    const actions = document.getElementById('actions');

    let state = {today: 0, goal: 8};
    try { state = await api.get_water_today(); } catch (e) { /* keep defaults */ }

    function render(newOne) {
        const {today, goal} = state;
        status.textContent = today === 0 ? 'No glasses yet today.'
            : today >= goal ? `${today} glasses today. Goal of ${goal} reached.`
            : `${today} of ${goal} glasses today.`;
        row.innerHTML = '';
        for (let i = 0; i < Math.max(goal, today); i++) {
            const g = document.createElement('i');
            if (i < today) g.className = 'full';
            if (newOne && i === today - 1) g.classList.add('new');
            row.appendChild(g);
        }
    }
    render(false);

    // --- glass follows the cursor (lerp), water level eases to today/goal ---
    const size = () => glass.getBoundingClientRect();
    let target = {x: innerWidth / 2, y: innerHeight * 0.36};
    let pos = {...target};
    addEventListener('pointermove', e => { target = {x: e.clientX, y: e.clientY}; });

    const levelOf = () => 0.12 + 0.78 * Math.min(1, state.today / Math.max(1, state.goal));
    let level = 0;
    // Water surface between x=-40 and 160 so it still fills the glass when counter-rotated.
    const wavePath = (h, phase, amp) => {
        const top = 152 - h * 142;
        let d = `M-40 ${top}`;
        for (let x = -40; x <= 160; x += 8) d += ` L${x} ${top + Math.sin(x / 14 + phase) * amp}`;
        return d + ' L160 220 L-40 220 Z';
    };

    // Time-based easing, so the glass moves the same at any refresh rate.
    const ease = (dt, perSecond) => 1 - Math.exp(-dt * perSecond);
    let last = performance.now();
    const frame = t => {
        const dt = Math.min(0.1, (t - last) / 1000);
        last = t;
        const k = ease(dt, 5);
        pos.x += (target.x - pos.x) * k;
        pos.y += (target.y - pos.y) * k;
        const r = size();
        const tilt = Math.max(-12, Math.min(12, (target.x - pos.x) * 0.05));
        glass.style.transform = `translate(${pos.x - r.width / 2}px, ${pos.y - r.height / 2}px) rotate(${tilt}deg)`;
        water.setAttribute('transform', `rotate(${-tilt} 60 90)`);

        level += (levelOf() - level) * ease(dt, 2.5);
        const s = t / 900;
        wave.setAttribute('d', wavePath(level, s, 2.6));
        waveBack.setAttribute('d', wavePath(level + 0.015, -s * 1.3 + 1, 3.2));
        requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);

    // --- actions ---
    let busy = false;
    async function drank() {
        if (busy) return;
        busy = true;
        actions.classList.add('gone');
        state = await api.log_water();
        document.getElementById('title').textContent = state.today >= state.goal ? 'Goal reached' : 'Nice, one more';
        render(true);
        await R2R.wait(2600);
        api.close();
    }
    glass.addEventListener('click', drank);
    document.getElementById('drank').addEventListener('click', drank);
    document.getElementById('later').addEventListener('click', () => api.snooze(5));
})();
