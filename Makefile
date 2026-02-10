# For source checking and testing

all: rufflint mypy 

rufflint:
	-uv run ruff check .
# To turn on checks for pathlib - add --select PTH to the above

# Not yet
#rufffmt:
#	-uv run ruff check --select I --fix .
#	-uv run ruff format .

typecheck:
	-uv run ty check --output-format github 2>/dev/null

test:
	-uv run pytest -rsx --cov --cov-report term-missing tests/

testhtml:
	-uv run pytest -rsx --cov --cov-report html tests/

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

