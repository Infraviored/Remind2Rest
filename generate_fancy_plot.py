#!/usr/bin/env python3

import os
import datetime
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.interpolate import Akima1DInterpolator
from scipy.interpolate import CubicSpline



from matplotlib.collections import PolyCollection
from matplotlib.colors import LinearSegmentedColormap

class Plotter:
    def __init__(self):
        # Custom colormap for ratings
        self.colors = [(1, 0, 0),  # Red
                       (1, 0.5, 0),  # Orange
                       (1, 1, 0),  # Yellow
                       (0, 1, 0),  # Green
                       (0, 0, 1)]  # Blue
        self.cm = LinearSegmentedColormap.from_list("custom_div_cmap", self.colors, N=4000)
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        self.plot_file_path = os.path.join(self.script_dir, 'ratings_plot.png')
        self.ratings_file_path = os.path.join(self.script_dir, 'posture_ratings.txt')



    def rating_to_color(self, rating):
        return self.cm((rating-0.4)/5)


    def generate_plot(self):
        if not os.path.exists(self.ratings_file_path):
            return None

        # Use a dictionary to automatically remove duplicated timestamps
        data_dict = {}

        with open(self.ratings_file_path, 'r') as file:
            for line in file:
                split_line = line.strip().split(" - Rating: ")
                timestamp = datetime.datetime.strptime(split_line[0], '%Y-%m-%d %H:%M:%S')
                data_dict[timestamp] = int(split_line[1])

        # Convert dictionary keys and values to lists
        times = list(data_dict.keys())
        ratings = list(data_dict.values())

        # Ensure data is sorted by time
        times, ratings = zip(*sorted(zip(times, ratings)))  
        
        if len(times) < 2:
            print("Not enough data points for interpolation. Need at least 2 ratings.")
            return None

        # Interpolation using Akima
        time_nums = mdates.date2num(times)
        akima = Akima1DInterpolator(time_nums, ratings)
        xnew = np.linspace(min(time_nums), max(time_nums), 1000)
        ynew = akima(xnew)
        ynew = np.clip(ynew, 1, 5)  # Ensure values stay between 1 and 5

        # Create shaded regions
        verts = []
        colors = []
        for i in range(len(xnew) - 1):
            v = [(xnew[i], 0), (xnew[i+1], 0), (xnew[i+1], ynew[i+1]), (xnew[i], ynew[i])]
            verts.append(v)
            colors.append(self.rating_to_color(ynew[i]))
        poly = PolyCollection(verts, facecolors=colors)

        # Plotting
        fig, ax = plt.subplots(figsize=(10, 6), frameon=False)
        ax.add_collection(poly)
        ax.plot(xnew, ynew, color="white", linewidth=1)
        ax.set_xlim(min(xnew), max(xnew))
        ax.set_ylim(0, 5.01)
        ax.set_ylabel("Rating", color="white", fontsize=20)
        ax.set_title("Ratings Over Time", color="white", fontsize=24)
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=15))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.tick_params(axis='both', colors='white', labelsize=16)



        plt.xticks(rotation=45)
        plt.gca().patch.set_facecolor('none')
        plt.savefig(self.plot_file_path, transparent=True, format="png", dpi=300)
        plt.close()


if __name__ == "__main__":
    plotter = Plotter()
    plotter.generate_plot()