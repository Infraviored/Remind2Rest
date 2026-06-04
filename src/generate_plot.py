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
from matplotlib.colors import LinearSegmentedColormap
import logging

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

        # 1. Define a rich, highly saturated but non-neon palette (Royal Jewel upgraded)
        # 1: Ruby Red, 2: Amber Orange, 3: Marigold Yellow, 4: Emerald Green, 5: Cobalt Blue
        custom_colors = ["#c90c29", "#e85d04", "#fca311", "#0f9f47", "#1c51a3"]
        cmap = LinearSegmentedColormap.from_list("posture_cmap", custom_colors)

        # Map the 1-5 rating directly to 0.0-1.0 for the colormap
        normalized_y = (ynew - 1) / 4.0
        rgba = cmap(normalized_y)[None, :, :]  # shape (1, W, 4)

        # Draw the gradient image
        im = ax.imshow(
            rgba,
            extent=[xnew.min(), xnew.max(), 0, 5.1],
            origin="lower",
            aspect="auto",
            interpolation="bicubic",
            zorder=1
        )

        # Clip image to area under curve
        xy = np.column_stack([xnew, ynew])
        clip_xy = np.vstack([[xnew[0], 0], xy, [xnew[-1], 0]])
        clip_patch = Polygon(clip_xy, closed=True, facecolor="none", edgecolor="none")
        ax.add_patch(clip_patch)
        im.set_clip_path(clip_patch)

        # Add subtle horizontal gridlines to easily read the rating level
        ax.yaxis.grid(True, color="#444444", linestyle="--", linewidth=0.5, zorder=0)

        # Foreground line with a softer, broader glow
        ax.plot(xnew, ynew, color="white", linewidth=8, alpha=0.08, zorder=2) # Broad soft glow
        ax.plot(xnew, ynew, color="white", linewidth=2.5, alpha=0.9, zorder=3) # Main line (slightly softened)
        ax.scatter(time_nums, ratings, color="#ffffff", s=50, edgecolors="#222222", linewidths=1.5, zorder=4)

        ax.set_xlim(xnew.min(), xnew.max())
        ax.set_ylim(0, 5.1)
        ax.set_ylabel("Rating", color="white", fontsize=16, labelpad=10)
        
        # Hide top, right, and left spines
        for spine in ["top", "right", "left"]:
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color("#444444")
        ax.spines["bottom"].set_linewidth(1.2)

        ax.xaxis.set_major_locator(plt.MaxNLocator(8))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        
        # Remove tick marks (the little lines) but keep the labels for a cleaner UI
        ax.tick_params(axis="both", colors="white", labelsize=12, length=0, pad=8)
        plt.xticks(rotation=0)

        fig.patch.set_alpha(0)
        ax.set_facecolor((0, 0, 0, 0))

        plt.tight_layout()
        plt.subplots_adjust(bottom=0.10)

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=dpi, transparent=True)
        buf.seek(0)
        plt.close(fig)
        return Image.open(buf)

    except Exception as e:
        logging.error(f"Error generating plot: {e}")
        return None

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    ratings_file_path = os.path.join(script_dir, "posture_ratings.txt")
    img = generate_plot(ratings_file_path)
    if img:
        img.show()
    else:
        print("Failed to generate plot.")
