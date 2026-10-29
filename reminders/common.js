// Shared by all reminder pages: waits for pywebview and closes on Escape.
window.R2R = {
    api: new Promise(resolve => {
        if (window.pywebview && window.pywebview.api) resolve(window.pywebview.api);
        else window.addEventListener('pywebviewready', () => resolve(window.pywebview.api));
    }),
    _closing: false,
    close() {
        if (R2R._closing) return Promise.resolve();
        R2R._closing = true;
        return R2R.api.then(api => api.close()).catch(() => {});
    },
    wait(ms) {
        return new Promise(r => setTimeout(r, ms));
    },
};

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        e.preventDefault();
        R2R.close();
    }
});
