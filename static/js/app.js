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
            slider: null,
            saveStatus: { show: false, success: false, message: '' }
        };
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
            this.$nextTick(() => {
                this.updateSlider();
            });
        },
        updateSlider() {
            if (this.slider) {
                this.slider.destroy();
            }

            const allReminders = this.modules
                .filter(m => this.config[m.key].enabled)
                .flatMap(m => this.config[m.key].reminders.map(time => ({ time, module: m.key })));
            const colors = Object.fromEntries(this.modules.map(m => [m.key, m.color]));

            const sliderElement = document.getElementById('interval-slider');

            if (allReminders.length === 0) {
                sliderElement.innerHTML = '';
                return;
            }

            this.slider = noUiSlider.create(sliderElement, {
                start: allReminders.map(r => r.time),
                connect: false,
                range: {
                    'min': 0,
                    'max': this.config.global_interval || 60
                },
                step: 1,
                tooltips: true,
                behaviour: 'unconstrained-tap',
                crossable: true
            });

            let activeHandle = null;

            const handles = sliderElement.querySelectorAll('.noUi-handle');
            handles.forEach((handle, index) => {
                handle.style.backgroundColor = colors[allReminders[index].module];
                
                const deleteButton = document.createElement('button');
                deleteButton.className = 'delete-button';
                deleteButton.innerHTML = '<svg class="delete-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';
                handle.appendChild(deleteButton);

                handle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const wasActive = handle.classList.contains('active');
                    handles.forEach(h => h.classList.remove('active'));
                    if (!wasActive) {
                        handle.classList.add('active');
                    }
                });

                deleteButton.addEventListener('click', (event) => {
                    event.stopPropagation();
                    const moduleIndex = allReminders[index].module;
                    const reminderIndex = this.config[moduleIndex].reminders.indexOf(allReminders[index].time);
                    this.deleteReminder(moduleIndex, reminderIndex);
                });
            });

            // Close active handle when clicking outside
            document.addEventListener('click', (e) => {
                if (!e.target.closest('.noUi-handle')) {
                    handles.forEach(handle => handle.classList.remove('active'));
                }
            });

            this.slider.on('update', (values) => {
                allReminders.forEach((reminder, index) => {
                    reminder.time = Math.round(values[index]);
                });

                this.modules.forEach(({ key: module }) => {
                    if (this.config[module].enabled) {
                        this.config[module].reminders = allReminders
                            .filter(r => r.module === module)
                            .map(r => r.time)
                            .sort((a, b) => a - b);
                    }
                });
            });
        },
        addReminder(module) {
            this.config[module].reminders.push(0);
            this.$nextTick(() => {
                this.updateSlider();
                const handles = document.querySelectorAll('.noUi-handle');
                const lastHandle = handles[handles.length - 1];
                if (lastHandle) {
                    lastHandle.classList.add('active');
                }
            });
        },
        testReminder(module) {
            call('test_reminder', module, this.config[module])
                .catch(error => alert(`Error triggering test reminder: ${error.message || error}`));
        },
        deleteReminder(module, index) {
            console.log('Deleting reminder:', module, index);
            const moduleConfig = this.config[module];
            if (moduleConfig && Array.isArray(moduleConfig.reminders)) {
                moduleConfig.reminders.splice(index, 1);
                console.log('Remaining reminders:', moduleConfig.reminders);
                this.$nextTick(() => {
                    this.updateSlider();
                });
            }
        },
        updateTotalInterval() {
            this.config.global_interval = parseInt(this.config.global_interval) || 60;
            this.updateSlider();
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
                const defaults = Object.fromEntries(library.map(m => [m.key, JSON.parse(JSON.stringify(m.defaults))]));
                this.config = { ...this.config, ...defaults, ...(saved || {}) };
                this.modules = library;
                this.$nextTick(() => this.updateSlider());
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
