FROM andrewosh/binder-base

MAINTAINER Erik van Sebille

USER main

# Install requirements for Python 2
RUN export USE_SETUPCFG=0
RUN export HDF5_INCDIR=/usr/include/hdf5/serial 
RUN export HDF5_LIBDIR=/usr/lib/x86_64-linux-gnu/hdf5/serial
RUN pip install netcdf4
ADD requirements.txt requirements.txt
RUN pip install -r requirements.txt

