// 4-7-8: breathe in 4 s, hold 7 s, breathe out 8 s; settings.cycles times, then close.
const PHASES = [
    {name: 'Breathe in', s: 4},
    {name: 'Hold', s: 7},
    {name: 'Breathe out', s: 8},
];
const CYCLE_S = PHASES.reduce((a, p) => a + p.s, 0);
const SMALL = 0.35;   // orb scale when the lungs are empty

const ease = t => 0.5 - Math.cos(Math.PI * t) / 2;

(async () => {
    const api = await R2R.api;
    const {settings = {}} = await api.get_context();
    const cycles = Math.max(1, Math.round(Number(settings.cycles) || 3));

    const orb = document.getElementById('orb');
    const arc = document.getElementById('arc');
    const phaseEl = document.getElementById('phase');
    const leftEl = document.getElementById('left');
    const cycleEl = document.getElementById('cycle');
    document.getElementById('skip').addEventListener('click', () => api.close());

    const start = performance.now();
    const tick = () => {
        const t = (performance.now() - start) / 1000;
        const cycle = Math.floor(t / CYCLE_S);
        if (cycle >= cycles) {
            api.close();
            return;
        }
        // Which phase, and how far into it (0..1).
        let inCycle = t - cycle * CYCLE_S, phase = 0;
        while (inCycle >= PHASES[phase].s) inCycle -= PHASES[phase++].s;
        const p = inCycle / PHASES[phase].s;

        const scale = phase === 0 ? SMALL + (1 - SMALL) * ease(p)
            : phase === 1 ? 1 - 0.015 * Math.sin(p * Math.PI * 3.5)   // a faint pulse while holding
            : 1 - (1 - SMALL) * ease(p);
        orb.style.transform = `scale(${scale})`;
        arc.style.strokeDashoffset = 1 - p;
        phaseEl.textContent = PHASES[phase].name;
        leftEl.textContent = Math.ceil(PHASES[phase].s - inCycle);
        cycleEl.textContent = `Breath ${cycle + 1} of ${cycles}`;
        requestAnimationFrame(tick);
    };
    tick();
})();
