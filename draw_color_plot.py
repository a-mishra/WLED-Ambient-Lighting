import matplotlib.pyplot as plt
import numpy as np
from config import load_config

# Load current config
config = load_config()

# Define resolution and segment dimensions
WIDTH, HEIGHT = config['OUTPUT_RESOLUTION']
H_SEGMENTS = config['H_SEGMENTS']
V_SEGMENTS = config['V_SEGMENTS']

# Global figure and axis variables for real-time updates
fig, ax = plt.subplots(figsize=(H_SEGMENTS, V_SEGMENTS))
plt.ion()  # Enable interactive mode
plt.show()

def normalize_color(color):
    """Normalize RGB color values to the range [0, 1]."""
    return tuple(c / 255.0 for c in color)

def draw_color_plot(color_segments):
    """Draw the updated plot with color segments."""
    image = np.zeros((V_SEGMENTS, H_SEGMENTS, 3), dtype=float)  # Use float for normalized colors

    # Top segments
    for i in range(H_SEGMENTS):
        image[0, i] = normalize_color(color_segments.get(f'top-{i}', (0, 0, 0)))

    # Bottom segments
    for i in range(H_SEGMENTS):
        image[V_SEGMENTS - 1, i] = normalize_color(color_segments.get(f'bottom-{i}', (0, 0, 0)))

    # Left segments
    for i in range(V_SEGMENTS):
        image[i, 0] = normalize_color(color_segments.get(f'left-{i}', (0, 0, 0)))

    # Right segments
    for i in range(V_SEGMENTS):
        image[i, H_SEGMENTS - 1] = normalize_color(color_segments.get(f'right-{i}', (0, 0, 0)))

    # Update plot
    ax.clear()  # Clear previous image before updating
    ax.imshow(image, extent=[0, WIDTH, 0, HEIGHT])
    ax.axis('off')

def set_colors(smoothed_colors):
    """Updates the color segments and redraws the plot."""
    color_segments = {
        f'top-{i}': smoothed_colors.get(f'top-{i}', (0, 0, 0)) for i in range(H_SEGMENTS)
    }
    color_segments.update({
        f'bottom-{i}': smoothed_colors.get(f'bottom-{i}', (0, 0, 0)) for i in range(H_SEGMENTS)
    })
    color_segments.update({
        f'left-{i}': smoothed_colors.get(f'left-{i}', (0, 0, 0)) for i in range(V_SEGMENTS)
    })
    color_segments.update({
        f'right-{i}': smoothed_colors.get(f'right-{i}', (0, 0, 0)) for i in range(V_SEGMENTS)
    })

    # Draw and update the figure
    draw_color_plot(color_segments)
    plt.draw()
    plt.pause(0.02)  # Pause to allow the plot to update in real time
