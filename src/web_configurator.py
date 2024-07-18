from flask import Flask, render_template, request, jsonify
from config_manager import ConfigManager
from service_manager import ServiceManager
import webbrowser
import threading

app = Flask(__name__)
config_manager = ConfigManager()
service_manager = ServiceManager()

@app.route('/')
def index():
    return render_template('index.html', config=config_manager.load_config())

@app.route('/save_config', methods=['POST'])
def save_configuration():
    new_config = request.json
    config_manager.save_config(new_config)
    service_manager.reload()
    return jsonify({"status": "success"})

@app.route('/toggle_service', methods=['POST'])
def toggle_service():
    if service_manager.is_running():
        service_manager.stop()
        return jsonify({"status": "off"})
    else:
        service_manager.start()
        return jsonify({"status": "on"})

@app.route('/service_status')
def service_status():
    return jsonify({"status": "on" if service_manager.is_running() else "off"})

@app.route('/toggle_autostart', methods=['POST'])
def toggle_autostart():
    if service_manager.is_autostart_enabled():
        service_manager.disable_autostart()
        status = "Disabled"
    else:
        service_manager.enable_autostart()
        status = "Enabled"
    return jsonify({"status": status})

@app.route('/autostart_status')
def autostart_status():
    status = "Enabled" if service_manager.is_autostart_enabled() else "Disabled"
    return jsonify({"status": status})

@app.route('/create_desktop_entry', methods=['POST'])
def create_desktop_entry():
    service_manager.create_desktop_entry()
    return jsonify({"status": "success"})

def open_browser():
    webbrowser.open('http://localhost:5000', new=2)

if __name__ == '__main__':
    threading.Thread(target=open_browser).start()
    app.run(debug=True, use_reloader=False)