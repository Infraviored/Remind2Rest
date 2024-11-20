// static/js/app.js

new Vue({
    el: '#app',
    data: function() {
        const initialData = JSON.parse(document.getElementById('initial-data').textContent);
        return {
            config: initialData.config || {
                global_interval: 60,
                eye_relax: {
                    enabled: false,
                    relax_duration: 20,
                    flash_frequency: 1,
                    reminders: []
                },
                posture: {
                    enabled: false,
                    wait_duration: 3,
                    reminders: []
                }
            },
            serviceStatus: 'Unknown',
            isServiceRunning: false,
            isServiceEnabled: false,
            autostartStatus: '',
            slider: null,
            colors: {
                eye_relax: '#3498db',
                posture: '#e74c3c'
            },
            saveStatus: initialData.saveStatus || {
                show: false,
                success: false,
                message: ''
            }
        };
    },
    methods: {
        saveConfig() {
            const button = document.querySelector('button[type="submit"]');
            
            axios.post('/save_config', this.config)
                .then(response => {
                    if (response.data.status === 'success') {
                        button.classList.add('saving-success');
                        setTimeout(() => button.classList.remove('saving-success'), 3000);
                    } else {
                        button.classList.add('saving-error');
                        setTimeout(() => button.classList.remove('saving-error'), 3000);
                        console.error('Save error:', response.data.message);
                    }
                })
                .catch(error => {
                    button.classList.add('saving-error');
                    setTimeout(() => button.classList.remove('saving-error'), 3000);
                    console.error('Save error:', error.response?.data?.message || error);
                });
        },
        toggleService() {
            axios.post('/toggle_service')
                .then(response => {
                    this.isServiceRunning = response.data.running;
                    this.serviceStatus = response.data.status;
                })
                .catch(error => {
                    console.error('Error toggling service:', error);
                    alert('Error toggling service');
                });
        },
        toggleServiceEnabled() {
            axios.post('/toggle_service_enabled')
                .then(response => {
                    this.isServiceEnabled = response.data.enabled;
                })
                .catch(error => {
                    console.error('Error toggling service enabled state:', error);
                    alert('Error enabling/disabling service');
                });
        },
        createConfiguratorShortcut() {
            axios.post('/create_configurator_shortcut')
                .then(() => alert('Configurator shortcut created successfully!'))
                .catch(error => alert('Error creating configurator shortcut'));
        },
        stopConfigurator() {
            axios.post('/stop_configurator')
                .then(() => window.close())
                .catch(error => alert('Error stopping configurator'));
        },
        toggleAutostart() {
            axios.post('/toggle_autostart')
                .then(response => this.updateAutostartStatus(response.data.status))
                .catch(error => {
                    console.error('Error toggling autostart:', error);
                    alert('Error toggling autostart');
                });
        },
        createDesktopEntry() {
            axios.post('/create_desktop_entry')
                .then(() => alert('Desktop entry created successfully!'))
                .catch(error => {
                    console.error('Error creating desktop entry:', error);
                    alert('Error creating desktop entry');
                });
        },
        updateAutostartStatus(status) {
            this.autostartStatus = `Start on Login (${status})`;
        },
        toggleModule(module, event) {
            this.config[module].enabled = event.target.checked;
            if (!this.config[module].enabled) {
                this.config[module].reminders = [];
            }
            this.$nextTick(() => {
                this.updateSlider();
            });
        },
        updateSlider() {
            if (this.slider) {
                this.slider.destroy();
            }

            const allReminders = Object.entries(this.config)
                .filter(([key, value]) => key !== 'global_interval' && value.enabled)
                .flatMap(([module, data]) =>
                    data.reminders.map(time => ({ time, module }))
                );

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
                pips: {
                    mode: 'count',
                    values: 5,
                    density: 2
                },
                behaviour: 'unconstrained-tap',
                crossable: true
            });

            let activeHandle = null;

            const handles = sliderElement.querySelectorAll('.noUi-handle');
            handles.forEach((handle, index) => {
                handle.style.backgroundColor = this.colors[allReminders[index].module];

                const tooltip = handle.querySelector('.noUi-tooltip');
                if (tooltip) {
                    tooltip.style.display = 'none';
                }

                const deleteButton = document.createElement('button');
                deleteButton.className = 'delete-button';
                deleteButton.innerHTML = '<svg class="delete-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';
                handle.appendChild(deleteButton);

                handle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    handles.forEach(h => {
                        h.classList.remove('active');
                        const t = h.querySelector('.noUi-tooltip');
                        if (t) t.style.display = 'none';
                    });
                    handle.classList.toggle('active');
                    if (tooltip) {
                        tooltip.style.display = handle.classList.contains('active') ? 'block' : 'none';
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
                    handles.forEach(handle => {
                        handle.classList.remove('active');
                        const tooltip = handle.querySelector('.noUi-tooltip');
                        if (tooltip) {
                            tooltip.style.display = 'none';
                        }
                    });
                }
            });

            this.slider.on('update', (values) => {
                allReminders.forEach((reminder, index) => {
                    reminder.time = Math.round(values[index]);
                });

                Object.keys(this.config).forEach(module => {
                    if (module !== 'global_interval' && this.config[module].enabled) {
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
        const savedConfig = JSON.parse(document.getElementById('config-data').textContent);
        if (Object.keys(savedConfig).length > 0) {
            this.config = { ...this.config, ...savedConfig };
        }

        axios.get('/service_info')
            .then(response => {
                this.serviceStatus = response.data.status;
                this.isServiceRunning = response.data.running;
                this.isServiceEnabled = response.data.enabled;
            })
            .catch(error => console.error('Error fetching service info:', error));

        axios.get('/autostart_status')
            .then(response => this.updateAutostartStatus(response.data.status))
            .catch(error => console.error('Error fetching autostart status:', error));

        this.$nextTick(() => {
            this.updateSlider();
        });
    },
    created() {
        // Start ping interval when component is created
        console.log('Starting ping interval...');
        this.pingInterval = setInterval(() => {
            axios.post('/ping')
                .then(() => console.log('Ping sent successfully'))
                .catch((error) => {
                    console.error('Ping failed:', error);
                    clearInterval(this.pingInterval);
                });
        }, 5000);
    },
    beforeDestroy() {
        console.log('Cleaning up ping interval...');
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
        }
    }
});