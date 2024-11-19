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

# Requires act tool to be installed
# For MacOS
# brew install act
# Runs github workflow locally
act:
	-act -j check --container-daemon-socket -  --container-architecture linux/aarch64 push

