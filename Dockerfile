FROM andrewosh/binder-base

MAINTAINER Erik van Sebille

USER root

# Add dependency
RUN export HDF5_LIBDIR=/usr/lib/x86_64-linux-gnu/hdf5/serial/
RUN export HDF5_INCDIR=/usr/include/hdf5/serial/
RUN apt-get update
RUN apt-get install -y libhdf5-serial-dev netcdf-bin libnetcdf-dev

USER main

# Install requirements for Python 2
ADD requirements.txt requirements.txt
RUN pip install -r requirements.txt

