import sys
import argparse
import os
import logging
import io
from datetime import datetime
from PIL import Image
import matplotlib
matplotlib.use('Agg')
from generate_plot import generate_plot

# Set up logging
logging.basicConfig(filename='notifications.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

script_dir = os.path.dirname(os.path.realpath(__file__))
ratings_file_path = os.path.join(script_dir, 'posture_ratings.txt')

# Detection logic
IS_WINDOWS = os.name == 'nt'
XDG_SESSION = os.environ.get('XDG_SESSION_TYPE', '').lower()

# Backend availability
HAS_GTK = False
if not IS_WINDOWS:
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gdk, GLib
        HAS_GTK = True
    except (ImportError, ValueError):
        pass

HAS_TK = False
try:
    import tkinter as tk
    from PIL import ImageTk
    HAS_TK = True
except ImportError:
    pass

# Selection logic:
# Wayland -> GTK (best support for overlays)
# Windows/X11 -> Tkinter (consistent with master and user's snippet)
USE_GTK = HAS_GTK and XDG_SESSION == 'wayland'

# --- GTK Implementation (from feat/wayland-support) ---
if HAS_GTK:
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
        if not screen:
            return
        style_provider = Gtk.CssProvider()
        try:
            style_provider.load_from_data(css.encode())
            Gtk.StyleContext.add_provider_for_screen(
                screen, style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            logging.error(f"Error applying CSS: {e}")

    def eye_relax_reminder_gtk(flash_frequency, relax_duration):
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
            if not state["blinking"]: return True
            state["is_white"] = not state["is_white"]
            if state["is_white"]: win.get_style_context().remove_class("dark")
            else: win.get_style_context().add_class("dark")
            return True
        
        def update_countdown():
            state["remaining"] -= 1
            countdown_label.set_text(f"Remaining: {state['remaining']}s")
            if state["remaining"] <= 0:
                win.destroy()
                Gtk.main_quit()
                return False
            return True
        
        win.connect("button-press-event", lambda w, e: state.update({"blinking": False}) or True)
        win.connect("button-release-event", lambda w, e: state.update({"blinking": True}) or True)
        
        flash_interval = int(1000 / flash_frequency) if flash_frequency > 0 else 10000
        GLib.timeout_add(flash_interval, toggle_blink)
        GLib.timeout_add(1000, update_countdown)
        win.show_all()
        Gtk.main()

    def show_custom_reminder_gtk(message, flashing, duration, cancel_key, flashing_freq=2, initial_color="black", fontsize=60):
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
                if state["inverted"]: win.get_style_context().add_class("inverted")
                else: win.get_style_context().remove_class("inverted")
                return True
            GLib.timeout_add(int(1000 / max(1, flashing_freq)), toggle)
        if duration > 0:
            GLib.timeout_add_seconds(duration, lambda: (win.destroy(), Gtk.main_quit(), False)[-1])
        win.show_all()
        Gtk.main()

    def posture_reminder_gtk(wait_duration, timeout=10):
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
            if not state["accept_keypress"]: return True
            char = Gdk.keyval_name(event.keyval)
            if char in ['1', '2', '3', '4', '5']:
                try:
                    with open(ratings_file_path, "a") as file:
                        file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Rating: {char}\n")
                except IOError as e: logging.error(f"IOError: {e}")
                win.destroy(); Gtk.main_quit()
            return True
        win.connect("key-press-event", on_key_press)
        GLib.timeout_add(int(wait_duration * 1000), enable_input)
        GLib.timeout_add_seconds(timeout, lambda: (win.destroy(), Gtk.main_quit(), False)[-1])
        win.show_all(); Gtk.main()

# --- Tkinter Implementation (from master + Windows snippet) ---
if HAS_TK:
    def setup_tk_fullscreen(root):
        if IS_WINDOWS:
            root.wm_attributes("-topmost", 1)
            root.overrideredirect(True)
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            root.geometry(f"{screen_width}x{screen_height}+0+0")
        else:
            root.attributes('-fullscreen', True)
            root.attributes('-topmost', True)
        root.focus_set()

    def eye_relax_reminder_tk(flash_frequency, relax_duration):
        root = tk.Tk()
        setup_tk_fullscreen(root)
        
        state = {"blinking": True, "remaining": int(relax_duration), "color": "white", "timer_id": None}
        
        def toggle_color():
            if not state["blinking"]:
                state["timer_id"] = None
                return
            state["color"] = "black" if state["color"] == "white" else "white"
            fg = "white" if state["color"] == "black" else "black"
            root.configure(background=state["color"])
            for l in [msg_l, hint_l, count_l]:
                l.configure(background=state["color"], foreground=fg)
            state["timer_id"] = root.after(int(1000 / flash_frequency) if flash_frequency > 0 else 10000, toggle_color)

        def update_countdown():
            state["remaining"] -= 1
            count_l.configure(text=f"Remaining: {state['remaining']}s")
            if state["remaining"] > 0: root.after(1000, update_countdown)
            else: root.destroy()

        msg_l = tk.Label(root, text="Look more than 20m away!", font=('Arial', 60))
        msg_l.place(relx=0.5, rely=0.45, anchor=tk.CENTER)
        hint_l = tk.Label(root, text="Hold mouse button to stop flashing", font=('Arial', 40))
        hint_l.place(relx=0.5, rely=0.55, anchor=tk.CENTER)
        count_l = tk.Label(root, text=f"Remaining: {state['remaining']}s", font=('Arial', 40))
        count_l.place(relx=0.5, rely=0.65, anchor=tk.CENTER)
        
        def on_press(e):
            state["blinking"] = False

        def on_release(e):
            if not state["blinking"]:
                state["blinking"] = True
                if state["timer_id"] is None:
                    toggle_color()

        root.bind('<Button-1>', on_press)
        root.bind('<ButtonRelease-1>', on_release)
        
        toggle_color()
        update_countdown()
        root.mainloop()

    def show_custom_reminder_tk(message, flashing, duration, cancel_key, flashing_freq=2, initial_color="black", fontsize=60):
        root = tk.Tk()
        setup_tk_fullscreen(root)
        
        bg_colors = ["white", "black"]
        curr = 1 if initial_color == "black" else 0
        flashing_active = [flashing]

        def toggle():
            if not flashing_active[0]: return
            nonlocal curr
            curr = 1 - curr
            root.configure(background=bg_colors[curr])
            label.configure(background=bg_colors[curr], foreground=bg_colors[1-curr])
            root.after(int(1000 / max(1, flashing_freq)), toggle)

        label = tk.Label(root, text=message, font=('Arial', fontsize), background=bg_colors[curr], foreground=bg_colors[1-curr])
        label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        root.configure(background=bg_colors[curr])
        
        root.bind(f'<{cancel_key}>' if not cancel_key.startswith('<') else cancel_key, lambda e: root.destroy())
        if flashing: toggle()
        if duration > 0: root.after(duration * 1000, root.destroy)
        root.mainloop()

    def posture_reminder_tk(wait_duration, timeout=10):
        root = tk.Tk()
        setup_tk_fullscreen(root)
        root.configure(background="black")
        
        msg_l = tk.Label(root, text="How is your posture?", font=('Arial', 60), fg="white", bg="black")
        msg_l.place(relx=0.5, rely=0.1, anchor=tk.CENTER)
        prompt_l = tk.Label(root, text="", font=('Arial', 40), fg="white", bg="black")
        prompt_l.place(relx=0.5, rely=0.2, anchor=tk.CENTER)
        
        plot_img = generate_plot(ratings_file_path)
        if plot_img:
            photo = ImageTk.PhotoImage(plot_img)
            img_l = tk.Label(root, image=photo, bg="black")
            img_l.image = photo
            img_l.place(relx=0.5, rely=0.6, anchor=tk.CENTER)
            
        state = {"accept": False}
        def enable():
            state["accept"] = True
            prompt_l.configure(text="Rate 1-5")
        
        def on_key(event):
            if not state["accept"]: return
            if event.char in "12345":
                try:
                    with open(ratings_file_path, "a") as f:
                        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Rating: {event.char}\n")
                except: pass
                root.destroy()
        
        root.bind('<Key>', on_key)
        root.after(int(wait_duration * 1000), enable)
        root.after(timeout * 1000, root.destroy)
        root.mainloop()

# --- Dispatcher ---
def eye_relax_reminder(freq, duration):
    logging.info(f"eye_relax: freq={freq}, dur={duration}, backend={'GTK' if USE_GTK else 'Tk'}")
    if USE_GTK: eye_relax_reminder_gtk(freq, duration)
    elif HAS_TK: eye_relax_reminder_tk(freq, duration)
    else: logging.error("No UI backend available")

def show_custom_reminder(message, flashing, duration, cancel_key, freq=2, color="black", fontsize=60):
    logging.info(f"custom: msg='{message}', backend={'GTK' if USE_GTK else 'Tk'}")
    if USE_GTK: show_custom_reminder_gtk(message, flashing, duration, cancel_key, freq, color, fontsize)
    elif HAS_TK: show_custom_reminder_tk(message, flashing, duration, cancel_key, freq, color, fontsize)
    else: logging.error("No UI backend available")

def posture_reminder(wait, timeout=10):
    logging.info(f"posture: wait={wait}, backend={'GTK' if USE_GTK else 'Tk'}")
    if USE_GTK: posture_reminder_gtk(wait, timeout)
    elif HAS_TK: posture_reminder_tk(wait, timeout)
    else: logging.error("No UI backend available")

def main():
    parser = argparse.ArgumentParser(description="Remind2Rest Notifications")
    subparsers = parser.add_subparsers(dest="command")
    
    eye_p = subparsers.add_parser("eye_relax")
    eye_p.add_argument("--freq", type=float, default=2.0)
    eye_p.add_argument("--duration", type=int, default=20)
    
    post_p = subparsers.add_parser("posture")
    post_p.add_argument("--wait", type=float, default=3.0)
    post_p.add_argument("--timeout", type=int, default=10)
    
    cust_p = subparsers.add_parser("custom")
    cust_p.add_argument("--message", type=str, required=True)
    cust_p.add_argument("--flashing", action="store_true")
    cust_p.add_argument("--duration", type=int, default=0)
    cust_p.add_argument("--cancel-key", type=str, default="Escape")
    cust_p.add_argument("--freq", type=int, default=2)
    cust_p.add_argument("--color", type=str, default="black")
    cust_p.add_argument("--fontsize", type=int, default=60)
    
    args = parser.parse_args()
    if args.command == "eye_relax": eye_relax_reminder(args.freq, args.duration)
    elif args.command == "posture": posture_reminder(args.wait, args.timeout)
    elif args.command == "custom": show_custom_reminder(args.message, args.flashing, args.duration, args.cancel_key, args.freq, args.color, args.fontsize)
    else: parser.print_help()

if __name__ == "__main__":
    main()
