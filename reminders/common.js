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
});

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        e.preventDefault();
        R2R.close();
    }
});
