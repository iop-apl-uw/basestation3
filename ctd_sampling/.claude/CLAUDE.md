## Python Environment
This project uses a virtual environment at `.venv/`. 

## Python Standards (Python 3.13)
- **Type Hinting**: Mandatory for all definitions. Use standard built-in collections natively (`list`, `dict`, `set`, `tuple`) and use `|` for unions. 
- **Modern Features**: Fully leverage `TypeVar` PEP 695 syntax if creating generics (`def function[T](arg: T) -> T:` instead of old `TypeVar('T')` bindings).
- **Docstrings**: Conform strictly to the Google Python Style Guide. Every public function must contain `Args:`, `Returns:`, and `Raises:` clauses.
- **Bypassing errors**: If a Type Error cannot be cleanly refactored due to a dynamic Python 3.13 implementation, instruct Claude to explicitly use `# ty: ignore[rule-name]` over generic `# type: ignore` comments.

## Validation Commands
- Format & Fix: `uv run ruff check --fix` and `uv run ruff format`
- Type Check: `uv run ty check`

# Python Testing Strategy
- Testing Framework: pytest with pytest-cov
- Code Coverage Targets: 
  - Minimum global coverage: 85%
  - Core logic / service layer: 100% (Strict)
  - Exclude: `__init__.py`, migrations, and local setup scripts.
- Execution Command: `pytest --cov=src --cov-report=term-missing

## Conventions
- Use `pathlib.Path` for all filesystem paths — never `os.path`, string concatenation, or `os.system`/`shutil` path args as raw strings.
  - Imports: `from pathlib import Path`
  - Joining: `Path(base) / "subdir" / "file.txt"`, not `os.path.join(...)`
  - Existence/type checks: `.exists()`, `.is_file()`, `.is_dir()`
  - Reading/writing: `.read_text()`, `.write_text()`, `.read_bytes()` instead of manual `open()` where feasible
  - Globbing: `.glob()` / `.rglob()` instead of `os.walk` or `glob.glob`
  - When a third-party API strictly requires a `str`, cast explicitly at the boundary: `str(path)`, with a short comment noting why.
