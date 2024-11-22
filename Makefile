# For source checking and testing

all: rufflint mypy 

rufflint:
	-ruff check .

rufffmt:
	-ruff check --select I --fix .
	-ruff format .


mypy:
	-mypy

test:
	-pytest --cov --cov-report term-missing tests/

testhtml:
	-pytest --cov --cov-report html tests/

# Runs github workflow locally
# Requires act tool to be installed.  Act requires docker to be installed.

# For MacOS
# brew install act
# Note: --container-architecture is for ARM mac
act:
	-act -j check --container-daemon-socket -  --container-architecture linux/aarch64 push

# For Ubuntu:
# curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash
# The following is also needed:
#
# sudo chown $USER:docker /var/run/docker.sock
#
# Assuming the docker post-install script has been run
# Obviously, this needs to be set after every reboot/restart of docker
actlinux:
	-act -j check --container-daemon-socket -  push

