// static/js/app.js

new Vue({
    el: '#app',
    data: {
        config: {
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
        serviceStatus: '',
        autostartStatus: '',
        slider: null,
        colors: {
            eye_relax: '#3498db',
            posture: '#e74c3c'
        }
    },
    methods: {
        saveConfig() {
            axios.post('/save_config', this.config)
                .then(() => alert('Configuration saved successfully!'))
                .catch(error => {
                    console.error('Error saving configuration:', error);
                    alert('Error saving configuration');
                });
        },
        toggleService() {
            const action = this.serviceStatus.includes('OFF') ? 'start' : 'stop';
            axios.post('/toggle_service', { action: action })
                .then(response => this.updateServiceStatus(response.data.status))
                .catch(error => {
                    console.error('Error toggling service:', error);
                    alert('Error toggling service');
                });
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
        updateServiceStatus(status) {
            this.serviceStatus = `ReminderApp is ${status.toUpperCase()} (Click to turn ${status === 'on' ? 'OFF' : 'ON'})`;
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

            const handles = sliderElement.querySelectorAll('.noUi-handle');
            handles.forEach((handle, index) => {
                handle.style.backgroundColor = this.colors[allReminders[index].module];

                const deleteButton = document.createElement('button');
                deleteButton.className = 'delete-button';
                deleteButton.innerHTML = '<svg class="delete-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>';
                handle.appendChild(deleteButton);

                handle.addEventListener('click', () => {
                    deleteButton.style.display = deleteButton.style.display === 'block' ? 'none' : 'block';
                });

                deleteButton.addEventListener('click', (event) => {
                    event.stopPropagation();
                    this.deleteReminder(allReminders[index].module, index);
                });
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
            this.updateSlider();
        },
        deleteReminder(module, index) {
            this.config[module].reminders.splice(index, 1);
            this.updateSlider();
        },
        updateTotalInterval() {
            this.config.global_interval = parseInt(this.config.global_interval) || 60;
            this.updateSlider();
        }
    },
    mounted() {
        const savedConfig = JSON.parse(document.getElementById('config-data').textContent);
        if (Object.keys(savedConfig).length > 0) {
            this.config = { ...this.config, ...savedConfig };
        }

        axios.get('/service_status')
            .then(response => this.updateServiceStatus(response.data.status))
            .catch(error => console.error('Error fetching service status:', error));

        axios.get('/autostart_status')
            .then(response => this.updateAutostartStatus(response.data.status))
            .catch(error => console.error('Error fetching autostart status:', error));

        this.$nextTick(() => {
            this.updateSlider();
        });
    }
});