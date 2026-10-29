// static/js/distribute.js
// Spreads reminder types over one cycle so they fire as far apart from each other as possible.
// Used by the settings page's Auto-arrange button (app.js); pure function, no DOM, so node tests load it too.

// Longest cycle we build from the LCM of the "every" values. Beyond that (e.g. every 35 and 45 min,
// LCM 315) the timeline would be unreadable, so the cycle is the largest "every" and every other
// "every" is rounded to the nearest divisor of it (ties round down, so a reminder rather comes too
// often than too rarely).
const MAX_CYCLE = 240;

const gcd = (a, b) => (b === 0 ? a : gcd(b, a % b));
const lcm = (a, b) => (a / gcd(a, b)) * b;

function nearestDivisor(n, target) {
    let best = 1;
    for (let d = 1; d <= n; d++) {
        if (n % d === 0 && Math.abs(d - target) < Math.abs(best - target)) best = d;
    }
    return best;
}

// Distance between two minutes on a circle of `cycle` minutes (59 and 1 are 2 apart in a 60 min cycle).
function circularDistance(a, b, cycle) {
    const d = Math.abs(a - b) % cycle;
    return Math.min(d, cycle - d);
}

// types: [{ key, every }] of the enabled types, in library order.
// Returns { cycle, every: { key: effective every }, reminders: { key: [minutes within the cycle] } }.
function distributeReminders(types) {
    const wanted = types.map(t => ({ key: t.key, every: Math.max(1, Math.round(Number(t.every) || 1)) }));
    if (wanted.length === 0) return { cycle: null, every: {}, reminders: {} };

    let cycle = wanted.map(t => t.every).reduce(lcm);
    if (cycle > MAX_CYCLE) {
        cycle = Math.min(MAX_CYCLE, Math.max(...wanted.map(t => t.every)));
        wanted.forEach(t => { t.every = nearestDivisor(cycle, t.every); });
    }

    // Most frequent first; sort is stable, so equal "every" keeps library order.
    const order = [...wanted].sort((a, b) => a.every - b.every);
    const placed = [];
    const reminders = {};
    for (const t of order) {
        let bestOffset = 0;
        let bestGap = -1;
        for (let offset = 0; offset < t.every; offset++) {
            let gap = Infinity;
            for (let time = offset; time < cycle; time += t.every) {
                for (const other of placed) gap = Math.min(gap, circularDistance(time, other, cycle));
            }
            if (gap > bestGap) { bestGap = gap; bestOffset = offset; }  // strict ">": ties keep the smallest offset
        }
        const times = [];
        for (let time = bestOffset; time < cycle; time += t.every) times.push(time);
        reminders[t.key] = times;
        placed.push(...times);
    }

    return { cycle, every: Object.fromEntries(wanted.map(t => [t.key, t.every])), reminders };
}

if (typeof module !== 'undefined') module.exports = { distributeReminders, MAX_CYCLE };
