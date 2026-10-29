// The sequence; each move gets settings.move_duration seconds, then the next starts on its own.
const MOVES = [
    {cls: 'neck', name: 'Neck rolls', how: 'Slowly circle your head, a few times each way.'},
    {cls: 'shrug', name: 'Shoulder shrugs', how: 'Pull your shoulders up to your ears, hold, let them drop.'},
    {cls: 'reach', name: 'Reach up', how: 'Stand up and stretch both arms to the ceiling.'},
    {cls: 'side', name: 'Side bends', how: 'Arms up, lean gently to one side, then the other.'},
];

(async () => {
    const api = await R2R.api;
    const {settings = {}} = await api.get_context();
    const perMove = Math.max(3, Number(settings.move_duration) || 20) * 1000;

    const figure = document.getElementById('figure');
    const name = document.getElementById('name');
    const how = document.getElementById('how');
    const count = document.getElementById('count');
    const steps = document.getElementById('steps');
    steps.style.setProperty('--n', MOVES.length);
    const items = MOVES.map(m => {
        const li = document.createElement('li');
        li.textContent = m.name;
        steps.appendChild(li);
        return li;
    });

    let closed = false;
    let rafId = null;
    const close = () => {
        if (closed) return;
        closed = true;
        if (rafId !== null) cancelAnimationFrame(rafId);
        R2R.close();
    };

    document.getElementById('done').addEventListener('click', close);

    let current = -1;
    const start = performance.now();
    const tick = () => {
        if (closed || R2R._closing) return;
        const elapsed = performance.now() - start;
        const i = Math.floor(elapsed / perMove);
        if (i >= MOVES.length) {
            close();
            return;
        }
        if (i !== current) {
            current = i;
            figure.setAttribute('class', MOVES[i].cls);
            name.textContent = MOVES[i].name;
            how.textContent = MOVES[i].how;
            items.forEach((li, j) => li.className = j < i ? 'past' : j === i ? 'now' : '');
        }
        const inMove = elapsed - i * perMove;
        count.textContent = Math.ceil((perMove - inMove) / 1000);
        items[i].style.setProperty('--p', `${(inMove / perMove) * 100}%`);
        rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
})();
