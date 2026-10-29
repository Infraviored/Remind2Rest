const WORDS = ['Slumped', 'Slouching', 'Okay', 'Good', 'Upright'];
const NS = 'http://www.w3.org/2000/svg';

(async () => {
    const api = await R2R.api;
    const {settings = {}} = await api.get_context();
    const wait = Math.max(0, Number(settings.wait_duration) || 0);

    const scale = document.getElementById('scale');
    scale.style.setProperty('--wait', `${wait}s`);
    const keys = WORDS.map((word, i) => {
        const b = document.createElement('button');
        b.className = 'key';
        b.innerHTML = `<span class="n">${i + 1}</span><span class="w">${word}</span>`;
        b.addEventListener('click', () => rate(i + 1));
        scale.appendChild(b);
        return b;
    });

    // Buttons and keys stay dead for wait_duration seconds; the subtitle counts down.
    const sub = document.getElementById('sub');
    let armed = false, done = false;
    const armAt = performance.now() + wait * 1000;
    const countdown = () => {
        const left = Math.ceil((armAt - performance.now()) / 1000);
        if (left > 0) {
            sub.textContent = `Check how you are sitting. The buttons unlock in ${left} s.`;
            setTimeout(countdown, 200);
        } else if (!done) {
            armed = true;
            scale.classList.add('armed');
            sub.textContent = 'Click a rating or press 1 to 5.';
        }
    };
    countdown();

    async function rate(n) {
        if (!armed || done) return;
        done = true;
        keys[n - 1].classList.add('chosen');
        scale.classList.add('done');
        document.getElementById('title').textContent = `Saved: ${n}, ${WORDS[n - 1].toLowerCase()}`;
        sub.textContent = n >= 4 ? 'Keep it that way.' : 'Roll your shoulders back and sit tall.';
        // The filled button shows for half a second (saving runs meanwhile), then the page closes.
        try {
            await Promise.all([api.save_rating(n), R2R.wait(500)]);
        } catch (e) {
            console.error('Failed to save rating:', e);
            await R2R.wait(500);
        } finally {
            api.close();
        }
    }

    addEventListener('keydown', e => {
        if (/^[1-5]$/.test(e.key)) rate(Number(e.key));
    });

    let ratings = [];
    try { ratings = await api.get_ratings(14) || []; } catch (e) { ratings = []; }
    const draw = () => drawChart(document.getElementById('chart'), ratings);
    draw();
    addEventListener('resize', draw);
})();

function parseTime(s) {
    // "YYYY-MM-DD HH:MM:SS" as local time
    return new Date(s.replace(' ', 'T'));
}

function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    parent && parent.appendChild(e);
    return e;
}

function drawChart(box, ratings) {
    box.innerHTML = '';
    const pts = ratings
        .map(r => ({t: parseTime(r.time), v: Number(r.rating)}))
        .filter(p => !isNaN(p.t) && p.v >= 1 && p.v <= 5);
    if (!pts.length) {
        box.innerHTML = '<div class="empty">No ratings yet. Your first one starts the chart.</div>';
        return;
    }

    const W = box.clientWidth, H = box.clientHeight;
    const fs = Math.max(11, Math.min(18, W / 90));
    const pad = {l: fs * 2.2, r: fs, t: fs * 0.8, b: fs * 2.4};
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;

    // 14 day columns ending today
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const DAY = 86400000, start = today.getTime() - 13 * DAY;
    const x = t => pad.l + ((t - start) / (14 * DAY)) * iw;
    const y = v => pad.t + (1 - (v - 1) / 4) * ih;

    const svg = el('svg', {viewBox: `0 0 ${W} ${H}`}, box);
    const defs = el('defs', {}, svg);
    const grad = el('linearGradient', {id: 'area', x1: 0, y1: 0, x2: 0, y2: 1}, defs);
    el('stop', {offset: 0, 'stop-color': '#38bdf8', 'stop-opacity': 0.22}, grad);
    el('stop', {offset: 1, 'stop-color': '#38bdf8', 'stop-opacity': 0}, grad);

    // grid: rating levels and day columns
    for (let v = 1; v <= 5; v++) {
        el('line', {x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: 'rgba(148,163,184,0.13)'}, svg);
        el('text', {x: pad.l - fs * 0.9, y: y(v) + fs * 0.35, 'font-size': fs, 'text-anchor': 'end'}, svg).textContent = v;
    }
    for (let d = 0; d < 14; d++) {
        const day = new Date(start + d * DAY);
        const cx = x(start + (d + 0.5) * DAY);
        if (d % 2 === 1) {
            el('rect', {x: x(start + d * DAY), y: pad.t, width: iw / 14, height: ih, fill: 'rgba(255,255,255,0.018)'}, svg);
        }
        const label = d === 13 ? 'Today' : day.toLocaleDateString(undefined, {weekday: 'short'});
        el('text', {x: cx, y: H - fs * 1.15, 'font-size': fs, 'text-anchor': 'middle',
            'font-weight': d === 13 ? 700 : 400}, svg).textContent = label;
        el('text', {x: cx, y: H - fs * 0.05, 'font-size': fs * 0.8, 'text-anchor': 'middle', opacity: 0.6}, svg)
            .textContent = day.getDate();
    }

    // daily means, then a moving average over neighbouring rated days as the trend
    const days = new Map();
    for (const p of pts) {
        const d = Math.floor((p.t - start) / DAY);
        if (d < 0 || d > 13) continue;
        (days.get(d) || days.set(d, []).get(d)).push(p.v);
    }
    const means = [...days].sort((a, b) => a[0] - b[0])
        .map(([d, vs]) => ({d, v: vs.reduce((a, b) => a + b, 0) / vs.length}));
    const trend = means.map((m, i) => {
        const near = means.slice(Math.max(0, i - 1), i + 2);
        return {x: x(start + (m.d + 0.5) * DAY), y: y(near.reduce((a, o) => a + o.v, 0) / near.length)};
    });

    if (trend.length > 1) {
        const path = smooth(trend);
        el('path', {d: `${path} L${trend.at(-1).x},${pad.t + ih} L${trend[0].x},${pad.t + ih} Z`, fill: 'url(#area)'}, svg);
        el('path', {d: path, fill: 'none', stroke: '#38bdf8', 'stroke-width': Math.max(2.5, fs / 4),
            'stroke-linecap': 'round', style: 'filter: drop-shadow(0 0 8px rgba(56,189,248,0.6))'}, svg);
    }

    // single ratings at their exact time
    for (const p of pts) {
        if (p.t < start) continue;
        el('circle', {cx: x(p.t.getTime()), cy: y(p.v), r: Math.max(3.5, fs / 3),
            fill: '#2dd4bf', 'fill-opacity': 0.55, stroke: '#121316', 'stroke-width': 1.5}, svg);
    }
    for (const t of trend) {
        el('circle', {cx: t.x, cy: t.y, r: Math.max(3, fs / 3.6), fill: '#121316', stroke: '#38bdf8', 'stroke-width': 2}, svg);
    }
}

// Catmull-Rom spline through the points, as cubic Béziers
function smooth(p) {
    let d = `M${p[0].x},${p[0].y}`;
    for (let i = 0; i < p.length - 1; i++) {
        const a = p[i - 1] || p[i], b = p[i], c = p[i + 1], e = p[i + 2] || c;
        d += ` C${b.x + (c.x - a.x) / 6},${b.y + (c.y - a.y) / 6} ${c.x - (e.x - b.x) / 6},${c.y - (e.y - b.y) / 6} ${c.x},${c.y}`;
    }
    return d;
}
