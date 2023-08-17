# syntax=docker/dockerfile:1
## Copyright (c) 2023  University of Washington.
## 
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
## 
## 1. Redistributions of source code must retain the above copyright notice, this
##    list of conditions and the following disclaimer.
## 
## 2. Redistributions in binary form must reproduce the above copyright notice,
##    this list of conditions and the following disclaimer in the documentation
##    and/or other materials provided with the distribution.
## 
## 3. Neither the name of the University of Washington nor the names of its
##    contributors may be used to endorse or promote products derived from this
##    software without specific prior written permission.
## 
## THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
## IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
## DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
## GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
## HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
## OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Creates a docker container suitable for running the basestation conversions from
# BaseRunner.py.  Not well tested and highly experimental.
#
# Known Issues:
# - .pagers, .ftp, .mailer and .urls all not currently working from inside the container.
# - vis notifications not working from inside the container.
#
# To Build:
# docker build -t basestation:3.10.10 .
#
FROM ubuntu:22.04

# install app dependencies
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get -y dist-upgrade
RUN apt-get install -y build-essential checkinstall libreadline-dev libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev zlib1g-dev openssl libffi-dev libgeos-dev python3-dev python3-setuptools wget libgdbm-compat-dev uuid-dev liblzma-dev
# Build python
WORKDIR /tmp
RUN wget https://www.python.org/ftp/python/3.10.10/Python-3.10.10.tar.xz
RUN tar xvf Python-3.10.10.tar.xz
WORKDIR /tmp/Python-3.10.10
RUN ./configure --enable-optimizations --prefix /opt/python/3.10.10
RUN make
RUN mkdir -p /opt/python
RUN make install
# Get copy of basestation
RUN mkdir -p /usr/local/basestation3
RUN apt-get install -y git
RUN git clone https://github.com/iop-apl-uw/basestation3.git /usr/local/basestation3
WORKDIR /usr/local/basestation3
RUN mkdir -p /opt/basestation
# Setup virtual env for basestation
RUN /opt/python/3.10.10/bin/python3 -m venv /opt/basestation
RUN /opt/basestation/bin/pip install -r /usr/local/basestation3/requirements.txt
