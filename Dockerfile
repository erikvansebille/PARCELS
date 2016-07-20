FROM andrewosh/binder-base

MAINTAINER Erik van Sebille

USER root
RUN apt update
RUN apt install -y libhdf5-serial-dev netcdf-bin libnetcdf-dev

# Install requirements for Python 2
RUN USE_SETUPCFG=0 HDF5_INCDIR=/usr/include/hdf5/serial HDF5_LIBDIR=/usr/lib/x86_64-linux-gnu/hdf5/serial pip install netcdf4
ADD requirements.txt requirements.txt
RUN pip install -r requirements.txt

RUN git clone --recursive https://github.com/erikvansebille/parcels.git
