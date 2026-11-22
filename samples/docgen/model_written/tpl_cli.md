# CLI – Simple Text Counter

A tiny command‑line utility that counts **lines**, **words**, and **characters** in a text file or from standard input.  
It is deliberately minimal, making it an excellent example for learning how to:

* Parse arguments with `argparse`
* Structure a Python CLI entry point
* Write unit tests for CLI behaviour
* Package a small, reusable script

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [API](#api)
- [Configuration](#configuration)
- [Running the Test Suite](#running-the-test-suite)
- [Contributing](#contributing)
- [License](#license)

---

## Features

| Feature | Description |
|---------|-------------|
| **Count** | Returns the number of lines, words, and characters. |
| **File or stdin** | Accepts a file path or `-` to read from standard input. |
| **Zero‑dependency** | Only uses the Python standard library. |
| **Cross‑platform** | Works on any OS with Python 3.9+. |
| **Tested** | Comes with a small `unittest` suite. |

---

## Installation

The project is a single‑file script, so you can either:

### 1. Clone the repository (recommended for development)

```bash
git clone https://github.com/yourusername/cli-count.git
cd cli-count
```

### 2. Install as a package (editable)

```bash
pip install -e .
```

> **Note:** The `setup.cfg`/`pyproject.toml` is not included in this minimal example, but you can add one if you want to distribute the tool on PyPI.

### 3. Run directly without installing

```bash
python cli.py --help
```

---

## Usage

```bash
python cli.py count <path>
```

* `<path>` – Path to a text file, or `-` to read from **stdin**.

### Examples

```bash
# Count a regular file
python cli.py count notes.txt
# → lines=10 words=42 chars=256

# Count from a pipe
echo "Hello world" | python cli.py count -
# → lines=1 words=2 chars=11

# Using the script as an executable (Unix)
chmod +x cli.py
./cli.py count notes.txt
```

The output format is a space‑separated list of `key=value` pairs:

```
lines=<int> words=<int> chars=<int>
```

---

## API

If you want to reuse the counting logic in your own Python code, import the helper functions:

```python
from cli import count, read_input

# Count a string directly
stats = count("some text")
# → {'lines': 1, 'words': 2, 'chars': 9}

# Read a file (or stdin) and count it
text = read_input("myfile.txt")   # or read_input("-") for stdin
stats = count(text)
```

### Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `count` | `count(text: str) -> dict[str, int]` | Returns a dictionary with keys `lines`, `words`, `chars`. |
| `read_input` | `read_input(path: str) -> str` | Reads the whole content of `path`. If `path` is `"-"`, reads from `sys.stdin`. |
| `build_parser` | `build_parser() -> argparse.ArgumentParser` | Constructs the `argparse` parser used by the CLI. |
| `main` | `main(argv: Sequence[str] | None = None) -> int` | Entry point used by `if __name__ == "__main__":`. Returns an exit code (0 = success, 1 = I/O error, 2 = unknown command). |

---

## Configuration

The tool does **not** require any external configuration files or environment variables. All behaviour is controlled via command‑line arguments.

If you need to extend it (e.g., add more sub‑commands or output formats), edit `cli.py`:

* Add a new sub‑parser in `build_parser()`.
* Implement the corresponding logic in `main()`.

---

## Running the Test Suite

The project includes a small `unittest` suite (`test_cli.py`). To run the tests:

```bash
python -m unittest discover -v
```

Or directly:

```bash
python test_cli.py
```

The tests verify:

* Correctness of the `count` function.
* Proper handling of file input.
* Correct exit codes for missing files.

---

## Contributing

Contributions are welcome! Feel free to:

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/awesome‑feature`).
3. Add your changes and tests.
4. Submit a pull request.

Please keep the code style consistent (PEP 8) and ensure all tests pass before opening a PR.

---

## License

This project is released under the **MIT License** – see the `LICENSE` file for details.