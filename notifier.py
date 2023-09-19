#!/usr/bin/env python3
import tkinter as tk

from datetime import datetime
import os
from PIL import Image, ImageTk
import matplotlib
matplotlib.use('Agg')
from generate_fancy_plot import Plotter
import json


class Notifier:
    def __init__(self, reminder_type):
        # Construct the full path to reminder_config.json based on the script's directory
        config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'reminder_config.json')
            # Load configurations
        with open(config_path, 'r') as file:
            self.config = json.load(file)
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.plot_file_path = os.path.join(self.script_dir, 'ratings_plot.png')
        self.ratings_file_path = os.path.join(self.script_dir, 'posture_ratings.txt')

        self.root = tk.Tk()
        self.plotter = Plotter()
        self.accept_keypress = False

        # Hide the root window
        self.root.withdraw()

        if reminder_type == "eye_relax":
            self.eye_relax_reminder()
        elif reminder_type == "posture":
            self.posture_reminder()

    def eye_relax_reminder(self):
        # Use the root window itself for the reminder
        relax_win = self.root
        relax_win.attributes('-fullscreen', True)
        relax_win.attributes('-topmost', True)
        relax_win.deiconify()  # Show the root window
        relax_win.focus_set()

        flash_interval = round(1000/self.config['flash_frequency']) if self.config['flash_frequency'] > 0 else 10000
        relax_duration_s = round(self.config['relax_duration']) if self.config['relax_duration'] > 0 else 20
        relax_duration_ms = round(relax_duration_s * 1000)



        # Variables to control the blinking
        self.blinking = True

        # Function to update the text color based on the background color
        def update_text_colors(current_color):
            foreground_color = "black" if current_color == "white" else "white"
            for label in [message_label, stop_blink_label, countdown_label]:
                label.configure(foreground=foreground_color, background=current_color)

        # This function will toggle between black and white
        def toggle_color(current_color):
            if not self.blinking:
                return
            next_color = "white" if current_color == "black" else "black"
            relax_win.configure(background=next_color)
            update_text_colors(next_color)
            relax_win.after(flash_interval, toggle_color, next_color)

        def stop_blinking(event):
            self.blinking = False

        def start_blinking(event):
            self.blinking = True
            toggle_color(relax_win.cget('background'))

        # Countdown logic
        self.remaining_time = relax_duration_s

        def update_countdown():
            self.remaining_time -= 1
            countdown_label.configure(text=f"Remaining: {self.remaining_time}s")
            if self.remaining_time > 0:
                relax_win.after(1000, update_countdown)

        # Bind mouse button events
        relax_win.bind('<Button-1>', stop_blinking)
        relax_win.bind('<ButtonRelease-1>', start_blinking)

        # Create the labels with large font in the center
        message_label = tk.Label(relax_win, text="Look more than 20m away!", font=('Arial', 60))
        message_label.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

        stop_blink_label = tk.Label(relax_win, text="Hold mouse button to stop flashing", font=('Arial', 40))
        stop_blink_label.place(relx=0.5, rely=0.55, anchor=tk.CENTER)

        countdown_label = tk.Label(relax_win, text=f"Remaining: {self.remaining_time}s", font=('Arial', 40))
        countdown_label.place(relx=0.5, rely=0.65, anchor=tk.CENTER)

        # Start the color toggle and countdown
        toggle_color("white")
        update_countdown()

        # Destroy the window after relax_duration in seconds
        relax_win.after(relax_duration_ms, relax_win.destroy)


        
    def posture_reminder(self):
        wait_duration_ms = round(self.config['wait_duration']*1000) if self.config['wait_duration'] > 0 else 3000
        # Use the root window itself for the reminder
        posture_win = self.root
        posture_win.attributes('-fullscreen', True)
        posture_win.attributes('-topmost', True)
        posture_win.deiconify()  # Show the root window
        posture_win.configure(background="black")

        
        if os.path.exists(self.plot_file_path):

            image = Image.open(self.plot_file_path)
            photo = ImageTk.PhotoImage(image)
            label = tk.Label(posture_win, image=photo, background="black")
            label.image = photo
            label.place(relx=0.5, rely=0.6, anchor=tk.CENTER)

        # Display the main message
        message_label = tk.Label(posture_win, text="How is your posture?", font=('Arial', 60), foreground="white", background="black")
        message_label.place(relx=0.5, rely=0.1, anchor=tk.CENTER)

        def enable_keypress():
            self.accept_keypress = True
            # Create the "Rate 1-5" label here
            rating_label = tk.Label(posture_win, text="Rate 1-5", font=('Arial', 40), foreground="white", background="black")
            rating_label.place(relx=0.5, rely=0.2, anchor=tk.CENTER)

        def on_key(event):
            if not self.accept_keypress:
                return
            if event.char in ['1', '2', '3', '4', '5']:
                self.ratings_file_path = os.path.join(self.script_dir, 'posture_ratings.txt')
                with open(self.ratings_file_path, "a") as file:
                        file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Rating: {event.char}\n")
                posture_win.destroy()
            else:
                # Handle invalid key press if necessary
                pass

        posture_win.bind('<Key>', on_key)
        posture_win.after(wait_duration_ms, enable_keypress)


    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    import sys
    reminder_type = sys.argv[1] if len(sys.argv) > 1 else "eye_relax"
    app = Notifier(reminder_type)
    app.run()