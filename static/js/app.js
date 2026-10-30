// static/js/app.js

// Resolves once pywebview has injected the Python API (window.pywebview.api).
const bridge = new Promise(resolve => {
    if (window.pywebview && window.pywebview.api) resolve(window.pywebview.api);
    else window.addEventListener('pywebviewready', () => resolve(window.pywebview.api));
});
const call = (name, ...args) => bridge.then(api => api[name](...args));

// Two reminders of different types this close (minutes, around the cycle) are marked as a collision.
const COLLISION_MINUTES = 2;
// Pointer travel (px) below which pressing a marker counts as a click (remove), not a drag.
const DRAG_THRESHOLD = 4;

// Conference signals in the order of src/conference.py SIGNALS. winHint replaces hint on Windows;
// winHint null = the signal cannot be detected there.
const CONFERENCE_SIGNALS = [
    { key: 'screen_share', label: 'Screen share', icon: 'screen_share',
      hint: 'Screen sharing or a screencast (top bar extension, else PipeWire)', winHint: null },
    { key: 'microphone', label: 'Microphone', icon: 'mic',
      hint: 'An app records from the microphone (with "Only with a meeting app": while one of the meeting apps runs)' },
    { key: 'camera', label: 'Camera', icon: 'videocam', hint: 'An app uses the camera' },
    { key: 'processes', label: 'Meeting app', icon: 'apps', hint: 'One of the meeting apps runs' },
    { key: 'do_not_disturb', label: 'Do Not Disturb', icon: 'do_not_disturb_on', hint: "GNOME's Do Not Disturb is on",
      winHint: 'Windows notifications are switched off (best effort)' }
];

// distributeReminders() and circularDistance() come from static/js/distribute.js, loaded before this file.

new Vue({
    el: '#app',
    data: function() {
        return {
            // Filled from the reminder library (src/library.py) in mounted().
            config: { global_interval: 60 },
            modules: [],
            // 'windows' or 'linux', from the Api in mounted().
            platform: 'linux',
            serviceStatus: 'Unknown',
            isServiceRunning: false,
            isServiceEnabled: false,
            // Marker being dragged: { key, index, startX, moved }.
            drag: null,
            // Marker under the mouse or keyboard focus, for its minute label: { key, index }.
            hover: null,
            // Position of "now" in the cycle, in minutes (fractional), refreshed by a timer.
            now: 0,
            status: { show: false, success: false, message: '' },
            // Webhook editor: the saved URL is never shown, only replaced (it holds a secret id).
            webhookEditing: false,
            webhookDraft: '',
            // Result of "Send test", shown next to the button: { ok, text } or null; 'sending' while it runs.
            webhookResult: null,
            suppressClick: false,
            suppressLaneClick: false
        };
    },
    computed: {
        cycle() {
            return this.config.global_interval;
        },
        // CONFERENCE_SIGNALS for this platform: { key, label, hint, unavailable }.
        conferenceSignals() {
            const windows = this.platform === 'windows';
            return CONFERENCE_SIGNALS.map(s => {
                const unavailable = windows && s.winHint === null;
                let hint = s.hint;
                if (unavailable) {
                    hint = 'Not available on Windows';
                } else if (windows && s.winHint) {
                    hint = s.winHint;
                }
                return { key: s.key, label: s.label, icon: s.icon, hint, unavailable };
            });
        },
        // "https://host/…" for the saved webhook URL; the path holds the secret webhook id.
        webhookMasked() {
            const url = (this.config.conference && this.config.conference.webhook_url) || '';
            const match = url.match(/^([a-z][a-z0-9+.-]*:\/\/)(?:[^@\/]*@)?([^\/?#]*)/i);
            return match ? match[1] + match[2] + '/…' : (url ? '…' : '');
        },
        enabledModules() {
            return this.modules.filter(m => this.config[m.key].enabled);
        },
        // Axis labels: every 10 min for short cycles, every 15 (or 30 for very long ones) otherwise.
        ticks() {
            const step = this.cycle <= 60 ? 10 : this.cycle <= 240 ? 15 : 30;
            const ticks = [];
            for (let t = 0; t <= this.cycle; t += step) ticks.push(t);
            return ticks;
        },
        // Minute ranges where reminders of different types come within COLLISION_MINUTES of each other.
        collisions() {
            const all = this.enabledModules.flatMap(m => this.config[m.key].reminders.map(t => ({ key: m.key, t })));
            const ranges = [];
            for (const a of all) {
                if (all.some(b => b.key !== a.key && circularDistance(a.t, b.t, this.cycle) <= COLLISION_MINUTES)) {
                    ranges.push([Math.max(0, a.t - 1), Math.min(this.cycle, a.t + 1)]);
                }
            }
            ranges.sort((x, y) => x[0] - y[0]);
            const merged = [];
            for (const r of ranges) {
                const last = merged[merged.length - 1];
                if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
                else merged.push([...r]);
            }
            return merged;
        },
        // Enabled types whose times are not "every N min" over the cycle any more (edited by hand,
        // or "every" changed): Auto-arrange would change them.
        offPattern() {
            return this.enabledModules.filter(m => !this.matchesEvery(m.key)).map(m => m.key);
        }
    },
    methods: {
        saveConfig() {
            if (this.webhookEditing) this.applyWebhook();   // a typed but not applied URL is saved too
            call('save_config', this.config)
                .then(result => this.showStatus(result.status === 'success', result.message))
                .catch(error => this.showStatus(false, `Save failed: ${error.message || error}`));
        },
        toggleService() {
            call('toggle_service')
                .then(result => {
                    this.isServiceRunning = result.running;
                    this.serviceStatus = result.status;
                })
                .catch(error => alert(`Error toggling service: ${error.message || error}`));
        },
        toggleServiceEnabled() {
            call('toggle_service_enabled')
                .then(result => { this.isServiceEnabled = result.enabled; })
                .catch(error => alert(`Error toggling autostart: ${error.message || error}`));
        },
        testReminder(module) {
            call('test_reminder', module, this.config[module])
                .catch(error => alert(`Error triggering test reminder: ${error.message || error}`));
        },
        // Tests the URL being typed, else the saved one; the result stays next to the button.
        testWebhook() {
            const url = (this.webhookEditing && this.webhookDraft.trim()) || this.config.conference.webhook_url;
            this.webhookResult = 'sending';
            call('test_webhook', url)
                .then(result => {
                    const ok = result.status === 'success';
                    this.webhookResult = { ok, text: ok ? `Received · HTTP ${result.code}` : result.message };
                })
                .catch(error => { this.webhookResult = { ok: false, text: `Test failed: ${error.message || error}` }; });
        },
        editWebhook() {
            this.webhookDraft = '';
            this.webhookResult = null;
            this.webhookEditing = true;
            this.$nextTick(() => this.$refs.webhookInput && this.$refs.webhookInput.focus());
        },
        // Takes the typed URL; an empty field keeps the saved one.
        applyWebhook() {
            const url = this.webhookDraft.trim();
            if (url) this.config.conference.webhook_url = url;
            this.webhookDraft = '';
            this.webhookEditing = false;
        },
        cancelWebhook() {
            this.webhookDraft = '';
            this.webhookEditing = false;
        },
        removeWebhook() {
            this.config.conference.webhook_url = '';
            this.webhookDraft = '';
            this.webhookEditing = false;
            this.webhookResult = null;
        },
        // Conference name lists, edited as comma-separated text.
        listText(key) {
            return (this.config.conference[key] || []).join(', ');
        },
        setList(key, event) {
            this.config.conference[key] = event.target.value.split(',').map(s => s.trim()).filter(Boolean);
        },
        // Library labels look like "Duration (s)": the name before the brackets, the unit inside.
        fieldName(label) {
            return label.replace(/\s*\(.*\)$/, '');
        },
        fieldUnit(label) {
            const unit = label.match(/\((.*)\)$/);
            return unit ? unit[1] : '';
        },
        // Number inputs as wide as their value, so the unit sits right after it.
        fitWidth(value) {
            return { width: String(value === undefined ? '' : value).length + 0.6 + 'ch' };
        },
        // Card border and tint in the type's library color (hex + alpha).
        cardStyle(m) {
            return this.config[m.key].enabled ? { borderColor: m.color + '4d', backgroundColor: m.color + '0d' } : {};
        },

        // Spreads the enabled types over a cycle built from their "every" (static/js/distribute.js).
        autoArrange() {
            const types = this.enabledModules.map(m => ({ key: m.key, every: this.config[m.key].every }));
            const result = distributeReminders(types);
            if (!result.cycle) return;
            this.config.global_interval = result.cycle;
            this.modules.forEach(m => {
                if (result.reminders[m.key]) {
                    this.config[m.key].reminders = result.reminders[m.key];
                } else if (Array.isArray(this.config[m.key]?.reminders)) {
                    this.config[m.key].reminders = this.config[m.key].reminders.filter(t => t < result.cycle);
                }
            });
            const rounded = this.enabledModules
                .filter(m => result.every[m.key] !== this.config[m.key].every)
                .map(m => `${m.title} every ${result.every[m.key]} min`);
            this.showStatus(true, rounded.length
                ? `Arranged in a ${result.cycle} min cycle. Rounded to fit: ${rounded.join(', ')}.`
                : `Arranged in a ${result.cycle} min cycle.`);
        },
        // True if the type's times are exactly offset, offset + every, ... around the cycle.
        matchesEvery(key) {
            const every = this.config[key].every;
            const times = this.config[key].reminders;
            const count = this.cycle / every;
            if (!(every >= 1) || this.cycle % every !== 0 || times.length !== count) return false;
            const sorted = [...times].sort((a, b) => a - b);
            return sorted.every((t, i) => t === sorted[0] + i * every);
        },

        // Cycle length typed in by hand. Times that no longer fit in the cycle are dropped.
        setCycle(event) {
            const value = Math.round(Number(event.target.value));
            if (!(value >= 1 && value <= 1440)) {
                event.target.value = this.cycle;
                return;
            }
            this.config.global_interval = value;
            this.modules.forEach(m => {
                this.config[m.key].reminders = this.config[m.key].reminders.filter(t => t < value);
            });
        },

        // ---- Timeline editing ----
        percent(minute) {
            return (minute / this.cycle) * 100 + '%';
        },
        // Whole minute under the pointer on a lane, 0..cycle-1.
        minuteAt(event, lane) {
            const rect = lane.getBoundingClientRect();
            const minute = Math.round(((event.clientX - rect.left) / rect.width) * this.cycle);
            return Math.min(this.cycle - 1, Math.max(0, minute));
        },
        setTimes(key, times) {
            this.config[key].reminders = [...new Set(times)].sort((a, b) => a - b);
        },
        addAt(key, event) {
            if (this.suppressLaneClick) return;
            if (event.target !== event.currentTarget) return;
            this.setTimes(key, [...this.config[key].reminders, this.minuteAt(event, event.currentTarget)]);
        },
        remove(key, index) {
            this.suppressLaneClick = true;
            setTimeout(() => { this.suppressLaneClick = false; }, 100);
            this.setTimes(key, this.config[key].reminders.filter((_, i) => i !== index));
            this.hover = null;
        },
        clickMarker(key, index) {
            if (this.suppressClick) {
                this.suppressClick = false;
                return;
            }
            this.remove(key, index);
        },
        startDrag(key, index, event) {
            if (event.button !== 0) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            this.drag = { key, index, startX: event.clientX, moved: false, originMinute: this.config[key].reminders[index] };
        },
        moveDrag(event) {
            const d = this.drag;
            if (!d) return;
            if (!d.moved && Math.abs(event.clientX - d.startX) < DRAG_THRESHOLD) return;
            d.moved = true;
            const lane = event.currentTarget.parentElement;
            this.$set(this.config[d.key].reminders, d.index, this.minuteAt(event, lane));
        },
        endDrag() {
            const d = this.drag;
            if (!d) return;
            this.drag = null;
            if (d.moved) {
                this.suppressClick = true;
                this.suppressLaneClick = true;
                setTimeout(() => {
                    this.suppressClick = false;
                    this.suppressLaneClick = false;
                }, 100);
                this.setTimes(d.key, this.config[d.key].reminders);   // sort, merge duplicates
            }
        },
        cancelDrag() {
            const d = this.drag;
            if (!d) return;
            this.drag = null;
            this.suppressClick = true;
            this.suppressLaneClick = true;
            setTimeout(() => {
                this.suppressClick = false;
                this.suppressLaneClick = false;
            }, 100);
            if (d.moved) {
                this.$set(this.config[d.key].reminders, d.index, d.originMinute);
                this.setTimes(d.key, this.config[d.key].reminders);
            }
        },
        // Arrow keys move a focused marker by 1 min (Shift: 5), Delete/Backspace removes it.
        nudge(key, index, event) {
            const times = this.config[key].reminders;
            if (event.key === 'Delete' || event.key === 'Backspace') {
                this.remove(key, index);
                return;
            }
            const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
            if (!step) return;
            event.preventDefault();
            const delta = step * (event.shiftKey ? 5 : 1);
            const moved = ((times[index] + delta) % this.cycle + this.cycle) % this.cycle;
            if (times.includes(moved)) return;
            this.setTimes(key, times.map((t, i) => (i === index ? moved : t)));
            const newIndex = this.config[key].reminders.indexOf(moved);
            this.hover = { key, index: newIndex };
            this.$nextTick(() => {
                const marker = document.querySelector(`[data-marker="${key}-${newIndex}"]`);
                if (marker) marker.focus();
            });
        },
        showsLabel(key, index) {
            const target = this.drag || this.hover;
            return !!target && target.key === key && target.index === index;
        },
        updateNow() {
            const d = new Date();
            this.now = ((d.getHours() * 60 + d.getMinutes()) % this.cycle) + d.getSeconds() / 60;
        },

        showStatus(success, message) {
            this.status = { show: true, success, message };
            clearTimeout(this.statusTimer);
            this.statusTimer = setTimeout(() => { this.status.show = false; }, 4000);
        }
    },
    watch: {
        cycle() { this.updateNow(); }
    },
    mounted() {
        Promise.all([call('get_library'), call('get_config')])
            .then(([library, saved]) => {
                saved = saved || {};
                const types = Object.fromEntries(library.map(m => [m.key, { ...JSON.parse(JSON.stringify(m.defaults)), ...saved[m.key] }]));
                this.config = { ...this.config, ...saved, ...types };
                if (this.config.conference && this.config.conference.microphone_needs_app === undefined) {
                    this.$set(this.config.conference, 'microphone_needs_app', true);
                }
                this.modules = library;
                this.updateNow();
            })
            .catch(error => this.showStatus(false, `Could not load config: ${error.message || error}`));

        call('get_platform')
            .then(platform => { this.platform = platform; })
            .catch(() => {});

        call('service_info')
            .then(info => {
                this.serviceStatus = info.status;
                this.isServiceRunning = info.running;
                this.isServiceEnabled = info.enabled;
            })
            .catch(error => console.error('Error fetching service info:', error));

        setInterval(() => this.updateNow(), 15000);
    }
});
