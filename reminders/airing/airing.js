(async () => {
    const api = await R2R.api;
    const {now} = await api.get_context();
    // Night sky outside before 7:00 and from 19:00 (local time of the context).
    const hour = now ? Number(now.slice(11, 13)) : new Date().getHours();
    document.body.classList.toggle('night', hour < 7 || hour >= 19);

    document.getElementById('done').addEventListener('click', () => api.close());
    document.getElementById('later').addEventListener('click', () => api.snooze(10));
})();
