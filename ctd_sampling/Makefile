# For source checking, testing

all: rufffmt rufflint typecheck test

rufflint:
	-uv run ruff check .

rufffmt:
	-uv run ruff check --select I --fix src tests
	-uv run ruff format src tests

typecheck:
	-uv run ty check --output-format github 2>/dev/null

test:
	-uv run pytest --cov --cov-report term-missing tests/

testhtml:
	-uv run pytest --cov --cov-report html tests/

# Requires act tool to be installed
# For MacOS
# brew install act
# Runs github workflow locally
act:
	-act -j check --container-daemon-socket -  --container-architecture linux/aarch64 push

doc:
	-uv run mkdocs build
