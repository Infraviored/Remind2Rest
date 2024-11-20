#!/usr/bin/env python3

import os
from datetime import timedelta, datetime
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.interpolate import Akima1DInterpolator
from io import BytesIO
from PIL import Image
from matplotlib.collections import PolyCollection
from matplotlib.colors import LinearSegmentedColormap
import logging


def rating_to_color(rating):
    colors = [
        (1, 0, 0),  # Red
        (1, 0.5, 0),  # Orange
        (1, 1, 0),  # Yellow
        (0, 1, 0),  # Green
        (0, 0, 1),  # Blue
    ]
    return LinearSegmentedColormap.from_list("custom_div_cmap", colors, N=4000)(
        (rating - 0.4) / 5
    )


def generate_plot(ratings_file):
    try:
        if not os.path.exists(ratings_file):
            logging.warning("Ratings file does not exist.")
            return None

        data_dict = {}
        with open(ratings_file, "r") as file:
            for line in file:
                try:
                    time_str, rating_str = line.strip().split(" - Rating: ")
                    timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    data_dict[timestamp] = int(rating_str)
                except ValueError as e:
                    logging.error(
                        f"Error parsing line in ratings file: {line}. Error: {str(e)}"
                    )

        if len(data_dict) < 2:
            logging.warning("Insufficient data to generate a plot.")
            return None

        current_time = datetime.now()
        one_day_ago = current_time - timedelta(days=1)
        filtered_data = [
            (time, rating) for time, rating in data_dict.items() if time >= one_day_ago
        ]

        if len(filtered_data) < 2:
            logging.warning(
                "Insufficient data for the last 24 hours to generate a plot."
            )
            return None

        times, ratings = zip(*filtered_data)
        time_nums = mdates.date2num(times)

        akima = Akima1DInterpolator(time_nums, ratings)
        xnew = np.linspace(min(time_nums), max(time_nums), 1000)
        ynew = np.clip(akima(xnew), 1, 5)

        verts = [
            [
                (xnew[i], 0),
                (xnew[i + 1], 0),
                (xnew[i + 1], ynew[i + 1]),
                (xnew[i], ynew[i]),
            ]
            for i in range(len(xnew) - 1)
        ]

        colors = [rating_to_color(y) for y in ynew]
        poly = PolyCollection(verts, facecolors=colors)

        fig, ax = plt.subplots(figsize=(10, 6), frameon=False)
        ax.xaxis.set_major_locator(plt.MaxNLocator(15))
        ax.scatter(time_nums, ratings, color="white", s=20)
        ax.add_collection(poly)
        ax.plot(xnew, ynew, color="white", linewidth=1)
        ax.set_xlim(min(xnew), max(xnew))
        ax.set_ylim(0, 5.1)
        ax.set_ylabel("Rating", color="white", fontsize=20)
        ax.set_title("Ratings Over Time", color="white", fontsize=24)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.tick_params(axis="both", colors="white", labelsize=16)
        plt.xticks(rotation=45)
        plt.gca().patch.set_facecolor("none")

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=300)
        buf.seek(0)
        return Image.open(buf)
    except Exception as e:
        logging.error(f"Error generating plot: {str(e)}")
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
