// Top bar indicator for the Remind2Rest daemon. Talks to it over its unix socket
// (~/.Remind2Rest.sock) with the same plain-text commands the configurator uses.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

Gio._promisify(Gio.SocketClient.prototype, 'connect_async');
Gio._promisify(Gio.InputStream.prototype, 'read_bytes_async');
Gio._promisify(Gio.OutputStream.prototype, 'write_bytes_async');
Gio._promisify(Gio.Subprocess.prototype, 'wait_async');

const SOCKET_PATH = GLib.build_filenamev([GLib.get_home_dir(), '.Remind2Rest.sock']);

const MODULES = {
    eye_relax: {label: 'Eye relax', icon: 'view-reveal-symbolic'},
    posture: {label: 'Posture', icon: 'preferences-desktop-accessibility-symbolic'},
};

// Sends one command and returns the daemon's whole reply; throws if the daemon is not running.
async function sendCommand(command, cancellable = null) {
    const client = new Gio.SocketClient();
    const conn = await client.connect_async(Gio.UnixSocketAddress.new(SOCKET_PATH), cancellable);
    try {
        await conn.get_output_stream().write_bytes_async(
            new GLib.Bytes(new TextEncoder().encode(command)), GLib.PRIORITY_DEFAULT, cancellable);
        const chunks = [];
        for (;;) {
            const bytes = await conn.get_input_stream().read_bytes_async(4096, GLib.PRIORITY_DEFAULT, cancellable);
            if (bytes.get_size() === 0)
                break;
            chunks.push(new TextDecoder().decode(bytes.toArray()));
        }
        return chunks.join('');
    } finally {
        try {
            conn.close(null);
        } catch {
            // ignore close error
        }
    }
}

async function systemctl(action) {
    const proc = Gio.Subprocess.new(['systemctl', '--user', action, 'Remind2Rest'], Gio.SubprocessFlags.NONE);
    await proc.wait_async(null);
}

const Indicator = GObject.registerClass(
class Indicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Remind2Rest');

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({icon_name: 'alarm-symbolic', style_class: 'system-status-icon'});
        this._label = new St.Label({text: '', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this._statusItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this.menu.addMenuItem(this._statusItem);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._pauseItems = [
            this._addAction('Pause 30 minutes', () => sendCommand('PAUSE 30')),
            this._addAction('Pause 1 hour', () => sendCommand('PAUSE 60')),
        ];
        this._resumeItem = this._addAction('Resume', () => sendCommand('RESUME'));
        this._triggerItems = [
            this._addAction('Eye break now', () => sendCommand('TRIGGER eye_relax')),
            this._addAction('Posture check now', () => sendCommand('TRIGGER posture')),
        ];
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._serviceItem = this._addAction('', () => systemctl(this._running ? 'stop' : 'start'));
        this._addAction('Settings…', () => {
            const app = Gio.DesktopAppInfo.new('Remind2Rest.desktop');
            if (app)
                app.launch([], null);
            else
                Main.notify('Remind2Rest', 'Remind2Rest.desktop not found. Run setup.py.');
        });

        this._running = false;
        this._polling = false;
        this._pollCounter = 0;
        this._remainingSeconds = null;
        this._currentModule = null;
        this._paused = false;

        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._tick();
            return GLib.SOURCE_CONTINUE;
        });
        this._pollDaemon();
    }

    _addAction(label, action) {
        const item = new PopupMenu.PopupMenuItem(label);
        item.connect('activate', () => {
            Promise.resolve().then(action)
                .catch(e => logError(e, 'Remind2Rest'))
                .finally(() => this._pollDaemon());
        });
        this.menu.addMenuItem(item);
        return item;
    }

    _tick() {
        this._pollCounter = (this._pollCounter || 0) - 1;
        if (this._pollCounter <= 0) {
            this._pollDaemon();
        } else if (this._running && !this._paused && this._currentModule && this._remainingSeconds !== null) {
            if (this._remainingSeconds > 0)
                this._remainingSeconds--;
            const mm = String(Math.floor(this._remainingSeconds / 60)).padStart(2, '0');
            const ss = String(this._remainingSeconds % 60).padStart(2, '0');
            const timeStr = `${mm}:${ss}`;
            this._label.text = ` ${timeStr}`;
            this._statusItem.label.text = `Next: ${this._currentModule.label} in ${timeStr}`;
        }
    }

    async _pollDaemon() {
        if (this._polling)
            return;
        this._polling = true;
        this._pollCounter = 5;

        const cancellable = new Gio.Cancellable();
        this._cancellable = cancellable;
        const cancelTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
            cancellable.cancel();
            return GLib.SOURCE_REMOVE;
        });

        let status = null;
        try {
            status = JSON.parse(await sendCommand('STATUS', cancellable));
        } catch {
            // Daemon not running, timed out, or unparseable reply.
        } finally {
            GLib.source_remove(cancelTimer);
            if (this._cancellable === cancellable)
                this._cancellable = null;
            this._polling = false;
        }

        if (!this._timer)
            return; // destroyed while waiting for the daemon

        this._running = status !== null;
        this._paused = Boolean(status?.paused_until);
        const module = MODULES[status?.next_reminder];
        this._currentModule = module;

        if (!this._running) {
            this._remainingSeconds = null;
            this._icon.icon_name = 'alarm-symbolic';
            this._icon.opacity = 110;
            this._label.text = '';
            this._statusItem.label.text = 'Service not running';
        } else if (this._paused) {
            this._remainingSeconds = null;
            const until = status.paused_until.slice(11, 16);
            this._icon.icon_name = 'media-playback-pause-symbolic';
            this._icon.opacity = 255;
            this._label.text = ` ${until}`;
            this._statusItem.label.text = `Paused until ${until}`;
        } else if (module) {
            if (status.time_to_next) {
                const parts = status.time_to_next.split(':');
                this._remainingSeconds = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
            } else {
                this._remainingSeconds = null;
            }
            this._icon.icon_name = module.icon;
            this._icon.opacity = 255;
            this._label.text = ` ${status.time_to_next}`;
            this._statusItem.label.text = `Next: ${module.label} in ${status.time_to_next}`;
        } else {
            this._remainingSeconds = null;
            this._icon.icon_name = 'alarm-symbolic';
            this._icon.opacity = 255;
            this._label.text = '';
            this._statusItem.label.text = 'No reminders enabled';
        }

        this._pauseItems.forEach(item => (item.visible = this._running && !this._paused));
        this._resumeItem.visible = this._running && this._paused;
        this._triggerItems.forEach(item => (item.visible = this._running));
        this._serviceItem.label.text = this._running ? 'Stop service' : 'Start service';
    }

    destroy() {
        if (this._cancellable) {
            this._cancellable.cancel();
            this._cancellable = null;
        }
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = null;
        }
        super.destroy();
    }
});

export default class Remind2RestExtension extends Extension {
    enable() {
        this._indicator = new Indicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
