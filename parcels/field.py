from scipy.interpolate import RectBivariateSpline
from cachetools import cachedmethod, LRUCache
from collections import Iterable
from py import path
import numpy as np
from xray import DataArray, Dataset
import operator
import matplotlib.pyplot as plt
from ctypes import Structure, c_int, c_float, c_double, POINTER


__all__ = ['Field']


class Field(object):
    """Class that encapsulates access to field data.

    :param name: Name of the field
    :param data: 2D array of field data
    :param lon: Longitude coordinates of the field
    :param lat: Latitude coordinates of the field
    :param transpose: Transpose data to required (lon, lat) layout
    """

    def __init__(self, name, data, lon, lat, depth=None, time=None,
                 transpose=False, vmin=None, vmax=None):
        self.name = name
        self.data = data
        self.lon = lon
        self.lat = lat
        self.depth = np.zeros(1, dtype=np.float32) if depth is None else depth
        self.time = np.zeros(1, dtype=np.float64) if time is None else time

        # Ensure that field data is the right data type
        if not self.data.dtype == np.float32:
            print("WARNING: Casting field data to np.float32")
            self.data = self.data.astype(np.float32)
        if transpose:
            # Make a copy of the transposed array to enforce
            # C-contiguous memory layout for JIT mode.
            self.data = np.transpose(self.data).copy()
        self.data = self.data.reshape((self.time.size, self.lat.size, self.lon.size))

        # If land points are defined as 0 or other non-nan values, make them nan
        if vmin is not None:
            self.data[self.data < vmin] = np.nan
        if vmax is not None:
            self.data[self.data > vmax] = np.nan
        self.data[self.data == 0] = np.nan

        # Variable names in JIT code
        self.ccode_data = self.name
        self.ccode_lon = self.name + "_lon"
        self.ccode_lat = self.name + "_lat"

        self.interpolator_cache = LRUCache(maxsize=2)
        self.time_index_cache = LRUCache(maxsize=2)

    @classmethod
    def from_netcdf(cls, name, dimensions, datasets, nemo=False, **kwargs):
        """Create field from netCDF file using NEMO conventions

        :param name: Name of the field to create
        :param dimensions: Variable names for the relevant dimensions
        :param dataset: Single or multiple netcdf.Dataset object(s)
        containing field data. If multiple datasets are present they
        will be concatenated along the time axis
        """
        if not isinstance(datasets, Iterable):
            datasets = [datasets]
        lon = datasets[0][dimensions['lon']]
        lon = lon[0, :] if len(lon.shape) > 1 else lon[:]
        lat = datasets[0][dimensions['lat']]
        lat = lat[:, 0] if len(lat.shape) > 1 else lat[:]
        # Default depth to zeros until we implement 3D grids properly
        depth = np.zeros(1, dtype=np.float32)
        # Concatenate time variable to determine overall dimension
        # across multiple files
        timeslices = [dset[dimensions['time']][:] for dset in datasets]
        time = np.concatenate(timeslices)

        # Pre-allocate grid data before reading files into buffer
        data = np.empty((time.size, 1, lat.size, lon.size), dtype=np.float32)
        tidx = 0
        for tslice, dset in zip(timeslices, datasets):
            data[tidx:, 0, :, :] = dset[dimensions['data']][:, 0, :, :]
            tidx += tslice.size
        # If reading from nemo file the U and V field positions need to be adjusted
        if nemo:
            if name == 'U':
                lon += np.diff(lon)[range(len(lon) - 1) + [len(lon) - 2]] / 2
            elif name == 'V':
                lat += np.diff(lat)[range(len(lat) - 1) + [len(lat) - 2]] / 2
        return cls(name, data, lon, lat, depth=depth, time=time, **kwargs)

    def __getitem__(self, key):
        return self.eval(*key)

    @cachedmethod(operator.attrgetter('interpolator_cache'))
    def bilinear(self, t_idx, x, y):
        try:
            xi = np.where(x >= self.lon)[0][-1]
            yi = np.where(y >= self.lat)[0][-1]


        return (sw * (self.lon[xi+1] - x) * (self.lat[yi+1] - y) +\
            se * (x - self.lon[xi]) * (self.lat[yi+1] - y) +\
            nw * (self.lon[xi+1] - x) * (y - self.lat[yi]) +\
            ne * (x - self.lon[xi]) * (y - self.lat[yi])) /\
            ((self.lon[xi+1] - self.lon[xi]) * (self.lat[yi+1] - self.lat[yi]))

    @cachedmethod(operator.attrgetter('interpolator_cache'))
    def interpolator2D(self, t_idx):
        return RectBivariateSpline(self.lat, self.lon,
                                   self.data[t_idx, :])

    def interpolator1D(self, idx, time, y, x):
        # Return linearly interpolated field value:
        if x is None and y is None:
            t0 = self.time[idx-1]
            t1 = self.time[idx]
            f0 = self.data[idx-1, :]
            f1 = self.data[idx, :]
        else:
            f0 = self.bilinear(idx-1, x, y)
            f1 = self.bilinear(idx, x, y)
#            f0 = self.interpolator2D(idx-1).ev(y, x)
#            f1 = self.interpolator2D(idx).ev(y, x)
            t0 = self.time[idx-1]
            t1 = self.time[idx]
        return f0 + (f1 - f0) * ((time - t0) / (t1 - t0))

    @cachedmethod(operator.attrgetter('time_index_cache'))
    def time_index(self, time):
        time_index = self.time < time
        if time_index.all():
            # If given time > last known grid time, use
            # the last grid frame without interpolation
            return -1
        else:
            return time_index.argmin()

    def eval(self, time, x, y):
        idx = self.time_index(time)
        if idx > 0:
            return self.interpolator1D(idx, time, y, x)
        else:
#            print self.bilinear(idx, x, y)
#            print self.interpolator2D(idx).ev(y, x)
#            return self.interpolator(idx).ev(y, x)
            return self.bilinear(idx, x, y)

    def ccode_subscript(self, t, x, y):
        ccode = "temporal_interpolation_linear(%s, %s, %s, %s, %s, %s)" \
                % (y, x, "particle->yi", "particle->xi", t, self.name)
        return ccode

    @property
    def ctypes_struct(self):
        """Returns a ctypes struct object containing all relevnt
        pointers and sizes for this field."""

        # Ctypes struct corresponding to the type definition in parcels.h
        class CField(Structure):
            _fields_ = [('xdim', c_int), ('ydim', c_int),
                        ('tdim', c_int), ('tidx', c_int),
                        ('lon', POINTER(c_float)), ('lat', POINTER(c_float)),
                        ('time', POINTER(c_double)),
                        ('data', POINTER(POINTER(c_float)))]

        # Create and populate the c-struct object
        cstruct = CField(self.lat.size, self.lon.size, self.time.size, 0,
                         self.lat.ctypes.data_as(POINTER(c_float)),
                         self.lon.ctypes.data_as(POINTER(c_float)),
                         self.time.ctypes.data_as(POINTER(c_double)),
                         self.data.ctypes.data_as(POINTER(POINTER(c_float))))
        return cstruct

    def show(self, **kwargs):
        t = kwargs.get('t', 0)
        idx = self.time_index(t)
        if self.time.size > 1:
            data = np.squeeze(self.interpolator1D(idx, t, None, None))
        else:
            data = np.squeeze(self.data)
        vmin = kwargs.get('vmin', data.min())
        vmax = kwargs.get('vmax', data.max())
        cs = plt.contourf(self.lon, self.lat, data,
                          levels=np.linspace(vmin, vmax, 256))
        cs.cmap.set_over('k')
        cs.cmap.set_under('w')
        cs.set_clim(vmin, vmax)
        plt.colorbar(cs)

    def write(self, filename, varname=None):
        filepath = str(path.local('%s%s.nc' % (filename, self.name)))
        if varname is None:
            varname = self.name
        # Derive name of 'depth' variable for NEMO convention
        vname_depth = 'depth%s' % self.name.lower()

        # Create DataArray objects for file I/O
        t, d, x, y = (self.time.size, self.depth.size,
                      self.lon.size, self.lat.size)
        nav_lon = DataArray(self.lon + np.zeros((y, x), dtype=np.float32),
                            coords=[('y', self.lat), ('x', self.lon)])
        nav_lat = DataArray(self.lat.reshape(y, 1) + np.zeros(x, dtype=np.float32),
                            coords=[('y', self.lat), ('x', self.lon)])
        vardata = DataArray(self.data.reshape((t, d, y, x)),
                            coords=[('time_counter', self.time),
                                    (vname_depth, self.depth),
                                    ('y', self.lat), ('x', self.lon)])
        # Create xray Dataset and output to netCDF format
        dset = Dataset({varname: vardata}, coords={'nav_lon': nav_lon,
                                                   'nav_lat': nav_lat})
        dset.to_netcdf(filepath)
