import io
import os
import logging
from datetime import datetime
from PIL import Image
from generate_plot import generate_plot
from src.config import RATINGS_FILE_PATH
from src.ui_utils import USE_GTK, HAS_TK, setup_tk_fullscreen

# Try to import GTK/Gdk/GLib
try:
    from gi.repository import Gtk, Gdk, GLib
    import cairo
    from src.ui_utils import apply_aggressive_fullscreen, apply_css
except ImportError:
    pass

# Try to import Tkinter
try:
    import tkinter as tk
    from PIL import ImageTk
except ImportError:
    pass

def posture_reminder_gtk(wait_duration, timeout=10):
    win = Gtk.Window()
    apply_aggressive_fullscreen(win)
    
    main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
    main_box.set_valign(Gtk.Align.FILL)
    main_box.set_halign(Gtk.Align.CENTER)
    win.add(main_box)
    
    title_label = Gtk.Label(label="How is your posture?")
    title_label.set_name("title")
    main_box.pack_start(title_label, False, False, 0)
    
    rating_prompt = Gtk.Label(label="Wait...")
    rating_prompt.set_name("prompt")
    main_box.pack_start(rating_prompt, False, False, 0)
    
    image_widget = Gtk.Image()
    image_widget.set_valign(Gtk.Align.END)
    main_box.pack_start(image_widget, True, True, 0)
    
    # State tracker to prevent redundant plot updates
    state = {"width": 0, "height": 0, "accept_keypress": False}
    
    def on_size_allocate(widget, allocation):
        sw = allocation.width
        sh = allocation.height
        if sw < 300 or sh < 300:
            return
        if sw == state["width"] and sh == state["height"]:
            return
        state["width"] = sw
        state["height"] = sh
        scale = win.get_scale_factor()
        
        logging.debug(f"GTK Allocated Size: {sw}x{sh}. Scale: {scale}")
        
        # Position margins dynamically using height percentage
        title_label.set_margin_top(int(sh * 0.06))
        image_widget.set_margin_bottom(int(sh * 0.008))
        
        # Recalculate fonts for actual allocation
        title_fs = max(30, int(sh * 0.055))
        prompt_fs = max(20, int(sh * 0.037))
        css = f"""
            window {{ background-color: black; }}
            #title {{ font: bold {title_fs}px Arial; color: white; }}
            #prompt {{ font: {prompt_fs}px Arial; color: white; }}
        """
        apply_css(win, css)
        
        # Calculate sensible plot size (95% width, 78% height max)
        plot_w = int(sw * 0.95)
        plot_h = int(sh * 0.78)
        
        # Calculate DPI to fit within constraints
        dpi_w = plot_w / 10
        dpi_h = plot_h / 6
        dynamic_dpi = int(min(dpi_w, dpi_h)) * scale
        
        logging.debug(f"GTK Constraints: {plot_w}x{plot_h}. Chosen DPI: {dynamic_dpi}")
        
        plot_img = generate_plot(RATINGS_FILE_PATH, figsize=(10, 6), dpi=dynamic_dpi)
        if plot_img:
            try:
                # Resize high-res plot to keep exact dimensions scaled by scale
                plot_img.thumbnail((plot_w * scale, plot_h * scale), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                plot_img.save(buf, format='PNG')
                buf.seek(0)
                
                surface = cairo.ImageSurface.create_from_png(buf)
                surface.set_device_scale(scale, scale)
                image_widget.set_from_surface(surface)
            except Exception as e:
                logging.error(f"GTK Cairo Image loading error: {e}")
                # Fallback to standard Pixbuf loader if cairo fails
                plot_img.thumbnail((plot_w, plot_h), Image.Resampling.LANCZOS)
                from gi.repository import GdkPixbuf
                buf = io.BytesIO()
                plot_img.save(buf, format='PNG')
                loader = GdkPixbuf.PixbufLoader.new_with_type('png')
                loader.write(buf.getvalue())
                loader.close()
                image_widget.set_from_pixbuf(loader.get_pixbuf())
                
    win.connect("size-allocate", on_size_allocate)
    
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
                with open(RATINGS_FILE_PATH, "a") as file:
                    file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Rating: {char}\n")
            except IOError as e:
                logging.error(f"IOError: {e}")
            win.destroy()
            Gtk.main_quit()
        return True
        
    win.connect("key-press-event", on_key_press)
    GLib.timeout_add(int(wait_duration * 1000), enable_input)
    GLib.timeout_add_seconds(timeout, lambda: (win.destroy(), Gtk.main_quit(), False)[-1])
    
    win.show_all()
    Gtk.main()

def posture_reminder_tk(wait_duration, timeout=10):
    root = tk.Tk()
    setup_tk_fullscreen(root)
    root.configure(background="black")
    
    msg_l = tk.Label(root, text="How is your posture?", font=('Arial', 30), fg="white", bg="black")
    msg_l.place(relx=0.5, rely=0.08, anchor=tk.CENTER)
    
    prompt_l = tk.Label(root, text="Wait...", font=('Arial', 20), fg="white", bg="black")
    prompt_l.place(relx=0.5, rely=0.16, anchor=tk.CENTER)
    
    img_l = tk.Label(root, bg="black")
    img_l.place(relx=0.5, rely=0.97, anchor=tk.S)
    
    state = {"accept": False, "width": 0, "height": 0}
    
    def on_configure(event):
        if event.widget != root:
            return
        sw = event.width
        sh = event.height
        if sw < 300 or sh < 300:
            return
        if sw == state["width"] and sh == state["height"]:
            return
        state["width"] = sw
        state["height"] = sh
        
        # Calculate fluid font sizes
        title_fs = max(30, int(sh * 0.055))
        prompt_fs = max(20, int(sh * 0.037))
        msg_l.configure(font=('Arial', title_fs))
        prompt_l.configure(font=('Arial', prompt_fs))
        
        # Calculate plot size
        plot_w = int(sw * 0.95)
        plot_h = int(sh * 0.78)
        
        dpi_w = plot_w / 10
        dpi_h = plot_h / 6
        dynamic_dpi = int(min(dpi_w, dpi_h))
        
        logging.debug(f"Tkinter Configure: {sw}x{sh}. Constraints: {plot_w}x{plot_h}. DPI: {dynamic_dpi}")
        
        plot_img = generate_plot(RATINGS_FILE_PATH, figsize=(10, 6), dpi=dynamic_dpi)
        if plot_img:
            plot_img.thumbnail((plot_w, plot_h), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(plot_img)
            img_l.configure(image=photo)
            img_l.image = photo
            
    root.bind("<Configure>", on_configure)
    
    def enable():
        state["accept"] = True
        prompt_l.configure(text="Rate 1-5")
        
    def on_key(event):
        if not state["accept"]:
            return
        if event.char in "12345":
            try:
                with open(RATINGS_FILE_PATH, "a") as f:
                    f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Rating: {event.char}\n")
            except Exception as e:
                logging.error(f"Error saving rating: {e}")
            root.destroy()
            
    root.bind("<Key>", on_key)
    root.after(int(wait_duration * 1000), enable)
    root.after(timeout * 1000, root.destroy)
    root.mainloop()

def posture_reminder(wait, timeout=10):
    logging.debug(f"posture: wait={wait}, backend={'GTK' if USE_GTK else 'Tk'}")
    if USE_GTK: posture_reminder_gtk(wait, timeout)
    elif HAS_TK: posture_reminder_tk(wait, timeout)
    else: logging.error("No UI backend available")
