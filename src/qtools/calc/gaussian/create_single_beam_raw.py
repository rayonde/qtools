"""
Create a single-beam raw file by removing one beam from a multi-beam raw file.
This is useful for testing the beam profile fitting algorithm with a single beam.
"""

import numpy as np
import cv2
from scipy.ndimage import maximum_filter

# Parameters (same as in 2D_1D_guass.py)
pixel_size = 3.75e-3
local_size = 50


def read_raw(raw_filename, bit_depth=8):
    """Read raw file and return 2D array."""
    if bit_depth == 16:
        dtype = np.uint16
    else:
        dtype = np.uint8

    data = np.fromfile(raw_filename, dtype=dtype)
    width = int(np.sqrt(len(data) / 12) * 4)
    height = int(np.sqrt(len(data) / 12) * 3)
    return data.reshape(height, width), width, height


def find_beam_centers(data, n_beams=2):
    """Find beam centers using local maxima detection."""
    # Auto-detect background threshold using Otsu
    _, binary = cv2.threshold(data.astype('uint8'), 0, 1,
                              cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bg_threshold = np.max(data[binary == 0])

    # Create mask for valid region
    valid_mask = data > bg_threshold

    # Find local maxima
    local_max = maximum_filter(data, size=local_size) == data
    coords = np.argwhere(local_max)

    # Get intensity at each peak
    intensities = data[coords[:, 0], coords[:, 1]]

    # Sort by intensity and take top n_beams
    top_indices = np.argsort(intensities)[-n_beams:]
    peak_coords = coords[top_indices]

    return peak_coords, intensities[top_indices]


def remove_beam(data, center, radius=150):
    """Remove a beam by zeroing out a circular region around the center."""
    h, w = data.shape
    y, x = center
    mask = np.ones_like(data, dtype=bool)

    for i in range(h):
        for j in range(w):
            if (i - y)**2 + (j - x)**2 < radius**2:
                mask[i, j] = False

    result = data.copy()
    result[~mask] = 0
    return result


def save_raw(data, filename, bit_depth=8):
    """Save 2D array as raw file."""
    if bit_depth == 16:
        dtype = np.uint16
    else:
        dtype = np.uint8

    data.astype(dtype).tofile(filename)
    print(f"Saved: {filename}")


if __name__ == "__main__":
    input_file = "/Users/rayonde/Documents/杭师大/qkd/gaussian/2.5cm.raw"
    output_file = "/Users/rayonde/Documents/杭师大/qkd/gaussian/2.5cm_single_beam.raw"

    # Read the raw file
    print(f"Reading {input_file}...")
    data, width, height = read_raw(input_file)
    print(f"Image size: {width} x {height}")

    # Find beam centers
    print("Detecting beams...")
    peak_coords, intensities = find_beam_centers(data, n_beams=2)
    print(f"Found {len(peak_coords)} beams at:")
    for i, (coord, intensity) in enumerate(zip(peak_coords, intensities)):
        print(f"  Beam {i+1}: y={coord[0]}, x={coord[1]}, intensity={intensity}")

    # Remove the second beam (less intense one)
    beam_to_remove = 1  # Remove the second (less bright) beam
    center_to_remove = peak_coords[beam_to_remove]
    print(f"\nRemoving beam at y={center_to_remove[0]}, x={center_to_remove[1]}")

    # Remove the beam with a radius that covers the beam spot
    radius = 150  # pixels - adjust as needed
    data_single = remove_beam(data, center_to_remove, radius=radius)

    # Save the result
    print(f"\nSaving single-beam raw file...")
    save_raw(data_single, output_file)

    # Verification
    print("\nVerifying...")
    peak_coords_new, intensities_new = find_beam_centers(data_single, n_beams=1)
    if len(peak_coords_new) == 1:
        print(f"SUCCESS: Single beam file created with beam at y={peak_coords_new[0][0]}, x={peak_coords_new[0][1]}")
    else:
        print(f"WARNING: Found {len(peak_coords_new)} peaks in output file")

    print(f"\nOutput file: {output_file}")