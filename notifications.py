import gi
import sys
import argparse
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
from datetime import datetime
import os
import logging
from PIL import Image
import matplotlib
matplotlib.use('Agg')
from generate_plot import generate_plot

# Set up logging
logging.basicConfig(filename='notifications.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Variables for file paths
script_dir = os.path.dirname(os.path.realpath(__file__))
ratings_file_path = os.path.join(script_dir, 'posture_ratings.txt')

def apply_aggressive_fullscreen(window):
    window.set_decorated(False)
    window.set_keep_above(True)
    window.stick()
    window.fullscreen()
    
    def bring_forward():
        window.present()
        return False
        
    GLib.idle_add(bring_forward)

def apply_css(widget, css):
    screen = Gdk.Screen.get_default()
    style_provider = Gtk.CssProvider()
    style_provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_screen(
        screen,
        style_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

def eye_relax_reminder(flash_frequency, relax_duration):
    logging.info(f"eye_relax_reminder called with flash_frequency={flash_frequency}, relax_duration={relax_duration}")
    
    def run_gtk():
        win = Gtk.Window()
        apply_aggressive_fullscreen(win)
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        main_box.set_valign(Gtk.Align.CENTER)
        main_box.set_halign(Gtk.Align.CENTER)
        win.add(main_box)
        
        message_label = Gtk.Label(label="Look more than 20m away!")
        message_label.set_name("message-label")
        main_box.pack_start(message_label, False, False, 0)
        
        hint_label = Gtk.Label(label="Hold mouse button to stop flashing")
        hint_label.set_name("hint-label")
        main_box.pack_start(hint_label, False, False, 0)
        
        countdown_label = Gtk.Label(label=f"Remaining: {int(relax_duration)}s")
        countdown_label.set_name("countdown-label")
        main_box.pack_start(countdown_label, False, False, 0)
        
        css = """
            window { background-color: white; }
            #message-label { font: bold 60px Arial; color: black; }
            #hint-label { font: 40px Arial; color: black; }
            #countdown-label { font: 40px Arial; color: black; }
            .dark { background-color: black; }
            .dark #message-label, .dark #hint-label, .dark #countdown-label { color: white; }
        """
        apply_css(win, css)
        
        state = {"blinking": True, "remaining": int(relax_duration), "is_white": True}
        
        def toggle_blink():
            if not state["blinking"]:
                return True
            state["is_white"] = not state["is_white"]
            if state["is_white"]:
                win.get_style_context().remove_class("dark")
            else:
                win.get_style_context().add_class("dark")
            return True
        
        def update_countdown():
            state["remaining"] -= 1
            countdown_label.set_text(f"Remaining: {state['remaining']}s")
            if state["remaining"] <= 0:
                win.destroy()
                Gtk.main_quit()
                return False
            return True
        
        def on_button_press(w, event):
            state["blinking"] = False
            return True
        
        def on_button_release(w, event):
            state["blinking"] = True
            return True
            
        win.connect("button-press-event", on_button_press)
        win.connect("button-release-event", on_button_release)
        
        flash_interval = int(1000 / flash_frequency) if flash_frequency > 0 else 10000
        GLib.timeout_add(flash_interval, toggle_blink)
        GLib.timeout_add(1000, update_countdown)
        
        win.show_all()
        Gtk.main()

    run_gtk()

def show_custom_reminder(message, flashing, duration, cancel_key, flashing_freq=2, initial_color="black", fontsize=60):
    logging.info(f"show_custom_reminder called with message={message}")
    
    def run_gtk():
        win = Gtk.Window()
        apply_aggressive_fullscreen(win)
        
        label = Gtk.Label(label=message)
        label.set_name("custom-label")
        win.add(label)
        
        bg_init = "white" if initial_color == "white" else "black"
        fg_init = "black" if initial_color == "white" else "white"
        
        css = f"""
            window {{ background-color: {bg_init}; }}
            #custom-label {{ font: {fontsize}px Arial; color: {fg_init}; }}
            .inverted {{ background-color: {fg_init}; }}
            .inverted #custom-label {{ color: {bg_init}; }}
        """
        apply_css(win, css)
        
        def on_key_press(w, event):
            keyname = Gdk.keyval_name(event.keyval)
            if keyname == cancel_key or (cancel_key == "Escape" and keyname == "Escape"):
                win.destroy()
                Gtk.main_quit()
            return True
            
        win.connect("key-press-event", on_key_press)
        
        if flashing:
            state = {"inverted": False}
            def toggle():
                state["inverted"] = not state["inverted"]
                if state["inverted"]:
                    win.get_style_context().add_class("inverted")
                else:
                    win.get_style_context().remove_class("inverted")
                return True
            interval = int(1000 / max(1, flashing_freq))
            GLib.timeout_add(interval, toggle)
            
        if duration > 0:
            GLib.timeout_add_seconds(duration, lambda: (win.destroy(), Gtk.main_quit(), False)[-1])
            
        win.show_all()
        Gtk.main()
        
    run_gtk()

def posture_reminder(wait_duration, timeout=10):
    logging.info(f"posture_reminder called with wait_duration={wait_duration}")
    
    def run_gtk():
        win = Gtk.Window()
        apply_aggressive_fullscreen(win)
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        main_box.set_valign(Gtk.Align.CENTER)
        main_box.set_halign(Gtk.Align.CENTER)
        win.add(main_box)
        
        title_label = Gtk.Label(label="How is your posture?")
        title_label.set_name("title")
        main_box.pack_start(title_label, False, False, 0)
        
        rating_prompt = Gtk.Label(label="")
        rating_prompt.set_name("prompt")
        main_box.pack_start(rating_prompt, False, False, 0)
        
        image_widget = Gtk.Image()
        main_box.pack_start(image_widget, False, False, 0)
        
        css = """
            window { background-color: black; }
            #title { font: bold 60px Arial; color: white; }
            #prompt { font: 40px Arial; color: white; }
        """
        apply_css(win, css)
        
        plot_img = generate_plot(ratings_file_path)
        if plot_img:
            # Convert PIL image to GdkPixbuf
            import io
            from gi.repository import GdkPixbuf
            buf = io.BytesIO()
            plot_img.save(buf, format='PNG')
            loader = GdkPixbuf.PixbufLoader.new_with_type('png')
            loader.write(buf.getvalue())
            loader.close()
            image_widget.set_from_pixbuf(loader.get_pixbuf())
            
        state = {"accept_keypress": False}
        
        def enable_input():
            state["accept_keypress"] = True
            rating_prompt.set_text("Rate 1-5")
            return False
            
        def on_key_press(w, event):
            if not state["accept_keypress"]:
                return True
            char = Gdk.keyval_name(event.keyval)
            if char in ['1', '2', '3', '4', '5']:
                try:
                    with open(ratings_file_path, "a") as file:
                        file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Rating: {char}\n")
                    logging.info(f"Posture rating {char} recorded")
                except IOError as e:
                    logging.error(f"Error writing to ratings file: {str(e)}")
                win.destroy()
                Gtk.main_quit()
            return True
            
        win.connect("key-press-event", on_key_press)
        GLib.timeout_add(int(wait_duration * 1000), enable_input)
        GLib.timeout_add_seconds(timeout, lambda: (win.destroy(), Gtk.main_quit(), False)[-1])
        
        win.show_all()
        Gtk.main()

    run_gtk()

def main():
    parser = argparse.ArgumentParser(description="Remind2Rest GTK Layer Shell Notifications")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Eye Relax
    eye_parser = subparsers.add_parser("eye_relax")
    eye_parser.add_argument("--freq", type=float, default=2.0)
    eye_parser.add_argument("--duration", type=int, default=20)
    
    # Posture
    posture_parser = subparsers.add_parser("posture")
    posture_parser.add_argument("--wait", type=float, default=3.0)
    posture_parser.add_argument("--timeout", type=int, default=10)
    
    # Custom
    custom_parser = subparsers.add_parser("custom")
    custom_parser.add_argument("--message", type=str, required=True)
    custom_parser.add_argument("--flashing", action="store_true")
    custom_parser.add_argument("--duration", type=int, default=0)
    custom_parser.add_argument("--cancel-key", type=str, default="Escape")
    custom_parser.add_argument("--freq", type=int, default=2)
    custom_parser.add_argument("--color", type=str, default="black")
    custom_parser.add_argument("--fontsize", type=int, default=60)
    
    args = parser.parse_args()
    
    if args.command == "eye_relax":
        eye_relax_reminder(args.freq, args.duration)
    elif args.command == "posture":
        posture_reminder(args.wait, args.timeout)
    elif args.command == "custom":
        show_custom_reminder(args.message, args.flashing, args.duration, args.cancel_key, args.freq, args.color, args.fontsize)
    else:
        parser.print_help()
        return

if __name__ == "__main__":
    main()