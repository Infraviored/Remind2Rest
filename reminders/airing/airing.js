(async () => {
    const api = await R2R.api;
    const {now} = await api.get_context();
    // Night sky outside before 7:00 and from 19:00 (local time of the context).
    const updateSky = (isoTime) => {
        const hour = isoTime ? Number(isoTime.slice(11, 13)) : new Date().getHours();
        document.body.classList.toggle('night', hour < 7 || hour >= 19);
    };
    updateSky(now);

    let snoozed = false;
    window.addEventListener('remind2rest:resume', () => {
        snoozed = false;
        updateSky();
    });

    document.getElementById('done').addEventListener('click', () => R2R.close());
    document.getElementById('later').addEventListener('click', () => {
        if (snoozed || R2R._closing) return;
        snoozed = true;
        api.snooze(10);
    });
})();
