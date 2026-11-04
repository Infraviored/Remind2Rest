// Shared by all reminder pages: waits for pywebview, closes on Escape, and tells the window when the
// first view is built so it can appear complete (src/overlay.py keeps it hidden until then on Windows).
window.R2R = {
    api: new Promise(resolve => {
        if (window.pywebview && window.pywebview.api) resolve(window.pywebview.api);
        else window.addEventListener('pywebviewready', () => resolve(window.pywebview.api));
    }),
    _closing: false,
    _holds: [],
    // Wrap the data the first view needs: the window shows once these settle (at most READY_CAP ms).
    // Call it right after `await R2R.api`, before any other await.
    hold(promise) {
        R2R._holds.push(Promise.resolve(promise).catch(() => {}));
        return promise;
    },
    close() {
        if (R2R._closing) return Promise.resolve();
        R2R._closing = true;
        return R2R.api.then(api => api.close()).catch(() => {});
    },
    wait(ms) {
        return new Promise(r => setTimeout(r, ms));
    },
};

const READY_CAP = 1500;

R2R.api.then(async api => {
    // The page's own `await R2R.api` runs right after this callback and registers its holds.
    await R2R.wait(0);
    await Promise.race([Promise.all(R2R._holds), R2R.wait(READY_CAP)]);
    await R2R.wait(0);  // let the page render what the held data produced
    if (api.ready) api.ready().catch(() => {});
    autoClose(api);
});

// settings.auto_close > 0: the page closes itself after that many seconds without input (posture by
// default: when nobody is at the desk, a rating would mean nothing). Any key, click or mouse move starts
// the count again; a Later stops it until the window comes back. A bar at the bottom runs down meanwhile.
async function autoClose(api) {
    let snoozed = false;
    let timer = null;
    let bar = null;
    let seconds = 0;

    const stop = () => {
        clearTimeout(timer);
        timer = null;
        if (bar) {
            bar.style.transition = 'none';
            bar.style.transform = 'scaleX(0)';
        }
    };

    if (api && api.snooze) {
        const snooze = api.snooze.bind(api);
        api.snooze = (...args) => {
            snoozed = true;
            stop();
            return snooze(...args);
        };
    }

    const start = () => {
        if (R2R._closing || snoozed || !(seconds > 0)) return;
        stop();
        bar.style.transform = 'scaleX(1)';
        void bar.offsetWidth;  // apply the full bar before the transition runs it down
        bar.style.transition = `transform ${seconds}s linear`;
        bar.style.transform = 'scaleX(0)';
        timer = setTimeout(() => R2R.close(), seconds * 1000);
    };

    window.addEventListener('remind2rest:resume', () => {
        snoozed = false;
        start();
    });

    for (const type of ['keydown', 'pointerdown', 'pointermove', 'wheel']) {
        document.addEventListener(type, () => { if (timer) start(); }, {passive: true});
    }

    try {
        const {settings = {}} = await api.get_context();
        seconds = Number(settings.auto_close) || 0;
    } catch (e) {
        return;
    }
    if (!(seconds > 0)) return;

    bar = document.createElement('div');
    bar.className = 'r2r-autoclose';
    document.body.appendChild(bar);

    if (!snoozed) {
        start();
    }
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        e.preventDefault();
        R2R.close();
    }
});
