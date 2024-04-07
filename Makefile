# For source checking and testing

all: rufflint mypy 

rufflint:
	-ruff check .

rufffmt:
	-ruff format .

mypy:
	-mypy

# Change to --cov-report html to generate html coverage reports
#test:
#	-pytest --cov --cov-report term-missing tests/

