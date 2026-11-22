# Code summaries: tpl_python_package

The `tpl_python_package` repository provides a Python package structured to separate core execution logic from input and output. The primary implementation resides in `app/core.py`, while `app/__init__.py` defines the package and contains module logic designed for testing. Keeping `app/__init__.py` free of input and output operations enables the repository's single test file to reliably call its functions.

Public functions and classes: 1; described: 100 % (from docstrings or the model; the rest show their signature).

## `app/__init__.py`

“The project's package.”


## `app/core.py`

“Core logic of the package.”

- `app/core.py::normalise`: “Example function: collapse whitespace and lower-case.”
