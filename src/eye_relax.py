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

def eye_relax_reminder(freq, duration):
    logging.debug(f"eye_relax: freq={freq}, dur={duration}, backend={'GTK' if USE_GTK else 'Tk'}")
    if USE_GTK: eye_relax_reminder_gtk(freq, duration)
    elif HAS_TK: eye_relax_reminder_tk(freq, duration)
    else: logging.error("No UI backend available")
