#!/usr/bin/env python3

import os
from datetime import timedelta, datetime
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.interpolate import Akima1DInterpolator
from io import BytesIO
from PIL import Image
from matplotlib.patches import Polygon
import logging
import colorsys

def rating_to_color(rating):
    # Clip rating to standard [1.0, 5.0] range
    r = max(1.0, min(5.0, rating))
    
    # Interpolate Hue (0 to 240 degrees) in HSV space
    if r < 2.0:
        h = 0.0 + (r - 1.0) * 30.0
    elif r < 3.0:
        h = 30.0 + (r - 2.0) * 30.0
    elif r < 4.0:
        h = 60.0 + (r - 3.0) * 60.0
    else:
        h = 120.0 + (r - 4.0) * 120.0
        
    # Convert Hue from degrees (0-360) to [0.0, 1.0] for colorsys
    h_val = h / 360.0
    
    # Return RGBA color with full saturation and brightness (Value = 1.0)
    return colorsys.hsv_to_rgb(h_val, 1.0, 1.0) + (1.0,)


def generate_plot(ratings_file, figsize=(10, 6), dpi=100):
    try:
        if not os.path.exists(ratings_file):
            logging.warning("Ratings file does not exist.")
            return None

        data_dict = {}
        with open(ratings_file, "r") as file:
            for line in file:
                line = line.strip()
                if not line or " - Rating: " not in line:
                    continue
                try:
                    time_str, rating_str = line.split(" - Rating: ")
                    timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    data_dict[timestamp] = int(rating_str)
                except (ValueError, IndexError) as e:
                    logging.error(f"Error parsing line: {line} ({e})")

        if len(data_dict) < 2:
            return None

        current_time = datetime.now()
        one_day_ago = current_time - timedelta(days=1)
        filtered_data = [(t, r) for t, r in data_dict.items() if t >= one_day_ago]

        if len(filtered_data) < 2:
            return None

        filtered_data.sort(key=lambda x: x[0])
        times, ratings = zip(*filtered_data)
        time_nums = mdates.date2num(times)

        akima = Akima1DInterpolator(time_nums, ratings)
        xnew = np.linspace(time_nums.min(), time_nums.max(), 2000)
        ynew = np.clip(akima(xnew), 1, 5)

        fig, ax = plt.subplots(figsize=figsize, frameon=False)

        # Build a 1-row RGBA image that varies only along x, then stretch vertically.
        rgba = np.array([rating_to_color(y) for y in ynew], dtype=float)[None, :, :]  # shape (1, W, 4)

        im = ax.imshow(
            rgba,
            extent=[xnew.min(), xnew.max(), 0, 5.1],
            origin="lower",
            aspect="auto",
            interpolation="bicubic",   # smooths horizontal transitions perfectly
            zorder=1
        )

        # Clip image to area under curve
        xy = np.column_stack([xnew, ynew])
        clip_xy = np.vstack([[xnew[0], 0], xy, [xnew[-1], 0]])
        clip_patch = Polygon(clip_xy, closed=True, facecolor="none", edgecolor="none")
        ax.add_patch(clip_patch)
        im.set_clip_path(clip_patch)

        # Foreground line and sample points
        ax.plot(xnew, ynew, color="white", linewidth=1.2, zorder=3)
        ax.scatter(time_nums, ratings, color="white", s=20, zorder=4)

        ax.set_xlim(xnew.min(), xnew.max())
        ax.set_ylim(0, 5.1)
        ax.set_ylabel("Rating", color="white", fontsize=20)
        ax.xaxis.set_major_locator(plt.MaxNLocator(15))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.tick_params(axis="both", colors="white", labelsize=16)
        plt.xticks(rotation=45)

        fig.patch.set_alpha(0)
        ax.set_facecolor((0, 0, 0, 0))

        plt.tight_layout()
        plt.subplots_adjust(bottom=0.11)

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=dpi, transparent=True)
        buf.seek(0)
        plt.close(fig)
        return Image.open(buf)

    except Exception as e:
        logging.error(f"Error generating plot: {e}")
        return None


if __name__ == "__main__":
    # For testing purposes
    script_dir = os.path.dirname(os.path.realpath(__file__))
    ratings_file_path = os.path.join(script_dir, "posture_ratings.txt")
    img = generate_plot(ratings_file_path)
    if img:
        img.show()
    else:
        print("Failed to generate plot.")
