import logging
from src.ui_utils import USE_GTK, HAS_TK, setup_tk_fullscreen

# Try to import GTK/Gdk/GLib
try:
    from gi.repository import Gtk, Gdk, GLib
    from src.ui_utils import apply_aggressive_fullscreen, apply_css
except ImportError:
    pass

# Try to import Tkinter
try:
    import tkinter as tk
except ImportError:
    pass

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

def show_custom_reminder(message, flashing, duration, cancel_key, freq=2, color="black", fontsize=60):
    logging.info(f"custom: msg='{message}', backend={'GTK' if USE_GTK else 'Tk'}")
    if USE_GTK: show_custom_reminder_gtk(message, flashing, duration, cancel_key, freq, color, fontsize)
    elif HAS_TK: show_custom_reminder_tk(message, flashing, duration, cancel_key, freq, color, fontsize)
    else: logging.error("No UI backend available")
