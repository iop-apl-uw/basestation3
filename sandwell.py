# -*- coding: utf-8 -*-

# ruff: noqa
"""
Created on Sun Feb 02 17:45:16 2014

Functions for reading Smith and Sandwell bathymetry.

https://github.com/jessecusack/ocean_tools/blob/master/ocean_tools/sandwell.py

@author: jc3e13
MIT license
"""

import os
import numpy as np
import glob


def read_grid(lon_lat, file_path=None):
    """Read in Smith and Sandwell bathymetry data.

    Parameters
    ----------
    lon_lat : array_like
        [lonmin lonmax lat_min lat_max].
         west   east   south   north
    file_path : string, optional
        Path to the Smith and Sandwell data file.

    Returns
    -------
    lon_grid : 2-D numpy.ndarray of floats
        Longitude values.
    lat_grid : 2-D numpy.ndarray of floats
        Latitude values.
    bathy_grid : 2-D numpy.ndarray of 16 bit integers.
        Bathymetry values.

    Raises
    ------
    ValueError
        If lon_lat bounds are not in the range -180 to +180 or
        -80.738 to +80.738.

    Notes
    -----
    The returned bathymetry array indexing is as follows,
    bathygrid[longitude, latitude], where both are monotonically increasing
    with index.

    This function has not been tested across the dateline.

    Examples
    --------
    See code.

    """

    # Important parameters.
    nlon = 21600         # Number of longitude points.
    nlat = 17280         # Number of latitude points.
    lat_min = -80.738    # Most southern extent of grid.
    lat_max = 80.738     # Most northern extent of grid.
    arcmin = 1./60.      # A single arcminute. (1/60 of a degree)
    rad = np.pi/180.     # A single radian.
    bytes_per_val = 2    # Number of bytes for each datum in file.
    dtype = '>i2'        # Data are big-endian (>) 2 byte signed integers.
    cross_0 = False      # Flag if grid crosses Greenwich meridian.

    west, east, south, north = lon_lat

    if (west < -180.) | (west > 180.) | (east < -180.) | (east > 180.):
        raise ValueError('Longitude out of bounds (-180 to 180).')

    if ((south < lat_min) | (south > lat_max) |
        (north < lat_min) | (north > lat_max)):

        raise ValueError(
            'Latitude out of bounds ({} to {}).'.format(lat_min, lat_max)
            )

    if north < south:
        raise ValueError('The north latitude is less than the south.')

    south = 90. - south
    north = 90. - north

    if west < 0:
        west = west + 360.
    if east < 0:
        east = east + 360.

    # Mercator projection transformations. (Ref: Wikipedia)
    y = lambda phi: np.log(np.tan(np.pi/4. + phi/2.))
    phi = lambda y: 2*np.arctan(np.exp(y)) - np.pi/2.

    all_lons = np.arange(0., 360., arcmin)
    all_lats = 90. - phi(np.linspace(y(lat_max*rad), y(lat_min*rad), nlat))/rad

    loni1, loni2 = all_lons.searchsorted([west, east]) + 1
    lati1, lati2 = all_lats.searchsorted([north, south]) + 1
    Nlats = lati2 - lati1
    lats = all_lats[lati1:lati2]

    if east < west:
        cross_0 = True
        lons = np.concatenate((all_lons[(loni1 - nlon):], all_lons[:loni2]))
    else:
        Nlons = loni2 - loni1
        lons = all_lons[loni1:loni2]

    lat_grid, lon_grid = np.meshgrid(lats, lons)
    bathy_grid = np.ndarray(lat_grid.shape, dtype='i2')

    if file_path is None:
        file_path = '/usr/local/basestation3/data/topo_17.1.img';

    with open(file_path, 'rb') as f:
        for i in range(Nlats):
            if cross_0:
                f.seek(bytes_per_val*((lati1 + i)*nlon + loni1))
                N = nlon - loni1
                bathy_grid[:N, i] = np.fromfile(f, dtype=dtype, count=N)

                f.seek(bytes_per_val*(lati1 + i)*nlon)
                bathy_grid[N:, i] = np.fromfile(f, dtype=dtype, count=loni2)
            else:
                f.seek(bytes_per_val*((lati1 + i)*nlon + loni1))
                bathy_grid[:, i] = np.fromfile(f, dtype=dtype, count=Nlons)

    lat_grid = 90 - lat_grid
    lon_grid[lon_grid > 180.] = lon_grid[lon_grid > 180.] - 360.

    # So because I couldn't get the grid orientations correct to begin with I
    # flip them here so that latitude and longitude are both monotonically
    # increasing with index. Not ideal.
    lat_grid = np.fliplr(lat_grid)
    bathy_grid = np.fliplr(bathy_grid)

    return lon_grid, lat_grid, bathy_grid

def bilinear_interpolation(xa, ya, fg, x, y):
    """Because, bizarrely, this doesn't exist in numpy.

    Parameters
    ----------
    xa : 1-D numpy.ndarray of floats
        x values of fg, must be monotonically increasing.
    ya : 1-D numpy.ndarray of floats
        y values of fg, must be monotonically increasing.
    fg : 2-D numpy.ndarray of floats
        values to be interpolated, formatted such that first index (rows)
        correspond to x and second index (columns) correspond to y, f[x,y]
    x : 1-D numpy.ndarray of floats
        x values of interpolation points.
    y : 1-D numpy.ndarray of floats
        y values of interpolation points.

    Returns
    -------
    fi : 1-D numpy.ndarray of floats
        Interpolated values of fg.

    Raises
    ------
    None.

    Notes
    -----
    Currently no error checking.
    Source: wikipedia.

    Examples
    --------
    None.

    """

    i1 = np.searchsorted(xa, x)
    i2 = i1 + 1
    j1 = np.searchsorted(ya, y)
    j2 = j1 + 1

    dx = xa[i2] - xa[i1]
    dy = ya[j2] - ya[j1]

    f11, f21, f12, f22 = fg[i1, j1], fg[i2, j1], fg[i1, j2], fg[i2, j2]

    x1, y1, x2, y2 = xa[i1], ya[j1], xa[i2], ya[j2]

    fi = (f11*(x2 - x)*(y2 - y) + f21*(x - x1)*(y2 - y) +
          f12*(x2 - x)*(y - y1) + f22*(x - x1)*(y - y1))/(dx*dy)

    return fi
