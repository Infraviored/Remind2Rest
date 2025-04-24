#!/usr/bin/env python3
import tkinter as tk
from datetime import datetime
import os
from PIL import Image, ImageTk
import matplotlib
matplotlib.use('Agg')
from generate_plot import generate_plot
import logging

# Set up logging
logging.basicConfig(filename='notifications.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Variables for file paths
script_dir = os.path.dirname(os.path.realpath(__file__))
ratings_file_path = os.path.join(script_dir, 'posture_ratings.txt')

def eye_relax_reminder(flash_frequency, relax_duration):
    print(f"Debug: eye_relax_reminder called with flash_frequency={flash_frequency}, relax_duration={relax_duration}")  # Debug print
    logging.info(f"eye_relax_reminder called with flash_frequency={flash_frequency}, relax_duration={relax_duration}")
    try:
        relax_win = tk.Tk()
        relax_win.attributes('-fullscreen', True)
        relax_win.attributes('-topmost', True)
        relax_win.focus_set()

        flash_interval = round(1000 / flash_frequency) if flash_frequency > 0 else 10000
        relax_duration_s = round(relax_duration) if relax_duration > 0 else 20
        relax_duration_ms = round(relax_duration_s * 1000)

        blinking = True  # Variable to control the blinking

        def update_text_colors(current_color):
            foreground_color = "black" if current_color == "white" else "white"
            for label in [message_label, stop_blink_label, countdown_label]:
                label.configure(foreground=foreground_color, background=current_color)

        def toggle_color(current_color):
            if not blinking:
                return
            next_color = "white" if current_color == "black" else "black"
            relax_win.configure(background=next_color)
            update_text_colors(next_color)
            relax_win.after(flash_interval, toggle_color, next_color)

        def stop_blinking(event):
            nonlocal blinking
            blinking = False

        def start_blinking(event):
            nonlocal blinking
            blinking = True
            toggle_color(relax_win.cget('background'))

        remaining_time = relax_duration_s  # Countdown logic

        def update_countdown():
            nonlocal remaining_time
            remaining_time -= 1
            countdown_label.configure(text=f"Remaining: {remaining_time}s")
            if remaining_time > 0:
                relax_win.after(1000, update_countdown)
            else:
                relax_win.destroy()

        relax_win.bind('<Button-1>', stop_blinking)
        relax_win.bind('<ButtonRelease-1>', start_blinking)

        message_label = tk.Label(relax_win, text="Look more than 20m away!", font=('Arial', 60))
        message_label.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

        stop_blink_label = tk.Label(relax_win, text="Hold mouse button to stop flashing", font=('Arial', 40))
        stop_blink_label.place(relx=0.5, rely=0.55, anchor=tk.CENTER)

        countdown_label = tk.Label(relax_win, text=f"Remaining: {remaining_time}s", font=('Arial', 40))
        countdown_label.place(relx=0.5, rely=0.65, anchor=tk.CENTER)

        toggle_color("white")
        update_countdown()

        relax_win.mainloop()
    except Exception as e:
        print(f"Debug: Error in eye_relax_reminder: {str(e)}")  # Debug print
        logging.error(f"Error in eye_relax_reminder: {str(e)}")

def show_custom_reminder(message, flashing, duration, cancel_key, flashing_freq=2, initial_color="black", fontsize=60):
    print(f"Debug: show_custom_reminder called with message={message}, flashing={flashing}, duration={duration}, cancel_key={cancel_key}, flashing_freq={flashing_freq}, initial_color={initial_color}, fontsize={fontsize}")
    logging.info(f"show_custom_reminder called with message={message}, flashing={flashing}, duration={duration}, cancel_key={cancel_key}, flashing_freq={flashing_freq}, initial_color={initial_color}, fontsize={fontsize}")
    try:
        win = tk.Tk()
        win.attributes('-fullscreen', True)
        win.attributes('-topmost', True)
        win.focus_set()

        bg_colors = ["white", "black"]
        if initial_color not in bg_colors:
            initial_color = "black"
        current_color = bg_colors.index(initial_color)
        flashing_active = [True]
        interval_ms = int(1000 / max(1, flashing_freq))

        def toggle_bg():
            if not flashing or not flashing_active[0]:
                return
            nonlocal current_color
            current_color = 1 - current_color
            win.configure(background=bg_colors[current_color])
            label.configure(foreground=bg_colors[1-current_color], background=bg_colors[current_color])
            win.after(interval_ms, toggle_bg)

        def close_reminder(event=None):
            flashing_active[0] = False
            win.destroy()

        win.bind(f'<{cancel_key}>', close_reminder)

        label = tk.Label(win, text=message, font=('Arial', fontsize))
        label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        win.configure(background=bg_colors[current_color])
        label.configure(foreground=bg_colors[1-current_color], background=bg_colors[current_color])

        if flashing:
            toggle_bg()

        if duration > 0:
            win.after(duration * 1000, close_reminder)

        win.mainloop()
    except Exception as e:
        print(f"Debug: Error in show_custom_reminder: {str(e)}")
        logging.error(f"Error in show_custom_reminder: {str(e)}")

def posture_reminder(wait_duration, timeout=10):
    print(f"Debug: posture_reminder called with wait_duration={wait_duration}, timeout={timeout}")  # Debug print
    logging.info(f"posture_reminder called with wait_duration={wait_duration}, timeout={timeout}")
    try:
        wait_duration_ms = round(wait_duration * 1000) if wait_duration > 0 else 3000
        timeout_duration_ms = round(timeout * 1000) if timeout > 0 else 10000
        accept_keypress = False
        posture_win = tk.Tk()
        posture_win.attributes('-fullscreen', True)
        posture_win.attributes('-topmost', True)
        posture_win.configure(background="black")
        plot_img = generate_plot(ratings_file_path)
        if plot_img:
            photo = ImageTk.PhotoImage(plot_img)
            label = tk.Label(posture_win, image=photo, background="black")
            label.image = photo  # Keep a reference to avoid garbage collection
            label.place(relx=0.5, rely=0.6, anchor=tk.CENTER)

        message_label = tk.Label(posture_win, text="How is your posture?", font=('Arial', 60), foreground="white", background="black")
        message_label.place(relx=0.5, rely=0.1, anchor=tk.CENTER)

        def enable_keypress():
            nonlocal accept_keypress
            accept_keypress = True
            rating_label = tk.Label(posture_win, text="Rate 1-5", font=('Arial', 40), foreground="white", background="black")
            rating_label.place(relx=0.5, rely=0.2, anchor=tk.CENTER)

        def on_key(event):
            if not accept_keypress:
                return
            if event.char in ['1', '2', '3', '4', '5']:
                try:
                    with open(ratings_file_path, "a") as file:
                        file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Rating: {event.char}\n")
                    print(f"Debug: Posture rating {event.char} recorded")  # Debug print
                    logging.info(f"Posture rating {event.char} recorded")
                except IOError as e:
                    print(f"Debug: Error writing to ratings file: {str(e)}")  # Debug print
                    logging.error(f"Error writing to ratings file: {str(e)}")
                posture_win.destroy()

        def close_window():
            posture_win.destroy()

        posture_win.bind('<Key>', on_key)
        posture_win.after(wait_duration_ms, enable_keypress)
        posture_win.after(timeout_duration_ms, close_window)

        posture_win.mainloop()
    except Exception as e:
        print(f"Debug: Error in posture_reminder: {str(e)}")  # Debug print
        logging.error(f"Error in posture_reminder: {str(e)}")

if __name__ == "__main__":
    # For testing purposes
    print("Debug: Testing eye_relax_reminder")
    eye_relax_reminder(1, 20)
    print("Debug: Testing posture_reminder")
    posture_reminder(3, 10)