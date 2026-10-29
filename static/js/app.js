// static/js/app.js

// Resolves once pywebview has injected the Python API (window.pywebview.api).
const bridge = new Promise(resolve => {
    if (window.pywebview && window.pywebview.api) resolve(window.pywebview.api);
    else window.addEventListener('pywebviewready', () => resolve(window.pywebview.api));
});
const call = (name, ...args) => bridge.then(api => api[name](...args));

new Vue({
    el: '#app',
    data: function() {
        return {
            // Filled from the reminder library (src/library.py) in mounted().
            config: { global_interval: 60 },
            modules: [],
            serviceStatus: 'Unknown',
            isServiceRunning: false,
            isServiceEnabled: false,
            // Last result of distributeReminders(), drawn by the timeline preview.
            schedule: { cycle: null, every: {}, reminders: {} },
            saveStatus: { show: false, success: false, message: '' }
        };
    },
    computed: {
        // Enabled types that have computed times, in library order, for the timeline preview.
        scheduledModules() {
            return this.modules.filter(m => this.config[m.key].enabled && this.schedule.reminders[m.key]);
        }
    },
    methods: {
        saveConfig() {
            call('save_config', this.config)
                .then(result => this.showSaveStatus(result.status === 'success', result.message))
                .catch(error => this.showSaveStatus(false, `Save failed: ${error.message || error}`));
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
        // Card border and tint in the type's library color (hex + alpha).
        cardStyle(m) {
            return this.config[m.key].enabled ? { borderColor: m.color + '4d', backgroundColor: m.color + '0d' } : {};
        },
        toggleModule(module, event) {
            this.config[module].enabled = event.target.checked;
            this.redistribute();
        },
        // Spreads the enabled types over the cycle (static/js/distribute.js) and writes the result
        // into the daemon's config: global_interval and config[type].reminders.
        redistribute() {
            const enabled = this.modules.filter(m => this.config[m.key].enabled);
            // While a field is being typed in (empty, 0), keep the last schedule.
            if (enabled.some(m => !(this.config[m.key].every >= 1))) return;
            const result = distributeReminders(enabled.map(m => ({ key: m.key, every: this.config[m.key].every })));
            if (result.cycle) this.config.global_interval = result.cycle;
            enabled.forEach(m => { this.config[m.key].reminders = result.reminders[m.key]; });
            this.schedule = result;
        },
        // Where a minute sits on the preview track, in percent of the cycle.
        position(minute) {
            return (minute / this.schedule.cycle) * 100 + '%';
        },
        testReminder(module) {
            call('test_reminder', module, this.config[module])
                .catch(error => alert(`Error triggering test reminder: ${error.message || error}`));
        },
        showSaveStatus(success, message) {
            this.saveStatus.show = true;
            this.saveStatus.success = success;
            this.saveStatus.message = message;
            
            setTimeout(() => {
                this.saveStatus.show = false;
            }, 3000);
        }
    },
    mounted() {
        Promise.all([call('get_library'), call('get_config')])
            .then(([library, saved]) => {
                saved = saved || {};
                const types = Object.fromEntries(library.map(m => [m.key, { ...JSON.parse(JSON.stringify(m.defaults)), ...saved[m.key] }]));
                this.config = { ...this.config, ...saved, ...types };
                this.modules = library;
                this.redistribute();
            })
            .catch(error => this.showSaveStatus(false, `Could not load config: ${error.message || error}`));

        call('service_info')
            .then(info => {
                this.serviceStatus = info.status;
                this.isServiceRunning = info.running;
                this.isServiceEnabled = info.enabled;
            })
            .catch(error => console.error('Error fetching service info:', error));
    }
});
