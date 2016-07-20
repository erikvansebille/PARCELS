FROM andrewosh/binder-base

MAINTAINER Erik van Sebille

USER root
RUN apt update
RUN apt install -y libhdf5-serial-dev netcdf-bin libnetcdf-dev

# Install requirements for Python 2
RUN pip install --only-binary all netcdf4
ADD requirements.txt requirements.txt
RUN pip install -r requirements.txt

