# 📦 app – Simple Text Normalisation Library

## Overview

`app` is a tiny Python package that provides a single utility function, **`normalise`**, which collapses whitespace and lower‑cases a string.  
It is deliberately minimalistic:

* No I/O or side‑effects in the core logic – perfect for unit testing and reuse.
* A clean, versioned package structure (`app/__init__.py`, `app/core.py`).
* Comes with a small test suite using the standard library’s `unittest`.

This repository serves as a teaching/example project for:

* Packaging a Python library.
* Writing pure functions that are easy to test.
* Setting up a basic CI‑friendly test layout.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Running the Test Suite](#running-the-test-suite)
- [Development & Contributing](#development--contributing)
- [License](#license)

---

## Installation

The package can be installed directly from the source or via `pip` once it is published to a package index.

### From Source (editable)

```bash
# Clone the repository
git clone https://github.com/yourusername/app.git
cd app

# Install in editable mode (recommended for development)
pip install -e .
```

### From a Wheel / sdist

If you have a built distribution (`.whl` or `.tar.gz`):

```bash
pip install dist/app-0.1.0-py3-none-any.whl   # or the .tar.gz file
```

> **Note:** The package requires **Python 3.8+** (type hints are used).

---

## Quick Start

```python
>>> from app.core import normalise
>>> normalise("  Hello   World ")
'hello world'
```

That’s it! The function removes extra spaces, collapses any whitespace (including tabs and newlines) into a single space, and lower‑cases the result.

---

## API Reference

### `app.core.normalise(text: str) -> str`

**Description**  
Collapses consecutive whitespace characters into a single space, strips leading/trailing whitespace, and converts the entire string to lower‑case.

**Parameters**

| Name | Type | Description |
|------|------|-------------|
| `text` | `str` | The input string to normalise. |

**Returns**

| Type | Description |
|------|-------------|
| `str` | The normalised string. |

**Example**

```python
>>> from app.core import normalise
>>> normalise("\tPython   is   Awesome!\n")
'python is awesome!'
```

---

## Configuration

The library itself does not require any runtime configuration.  
If you need to extend it (e.g., add locale‑aware case folding), you can modify `app/core.py` or create additional modules under `app/`.

---

## Running the Test Suite

The project uses the built‑in `unittest` framework. Tests live in the `tests/` directory.

```bash
# Run all tests
python -m unittest discover -s tests
```

You should see output similar to:

```
..
----------------------------------------------------------------------
Ran 2 tests in 0.001s

OK
```

### Test Coverage (optional)

If you want to check test coverage, install `coverage`:

```bash
pip install coverage
coverage run -m unittest discover -s tests
coverage report -m
```

---

## Development & Contributing

1. **Fork** the repository.
2. **Create a feature branch** (`git checkout -b feature/awesome-feature`).
3. **Make your changes** and add tests as needed.
4. **Run the test suite** to ensure everything passes.
5. **Submit a Pull Request** with a clear description of your changes.

### Setting Up a Development Environment

```bash
# Clone your fork
git clone https://github.com/yourusername/app.git
cd app

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# Install the package in editable mode plus dev dependencies
pip install -e .[dev]

# (Optional) Install testing tools
pip install coverage
```

*The `setup.cfg`/`pyproject.toml` files are omitted for brevity but can be added to support packaging and linting tools.*

---

## License

This project is licensed under the **MIT License** – see the `LICENSE` file for details.

--- 

*Happy coding!*