# Code summaries: tpl_cli

The `tpl_cli` project provides a command-line interface skeleton implemented as a Python project. Its main entry point is defined in `cli.py::main`, which receives arguments, executes a chosen subcommand, and returns an exit code. The repository is structured around a single module, `cli.py`, and includes a single test file to support the codebase.

Public functions and classes: 4; described: 100 % (from docstrings or the model; the rest show their signature).

## `cli.py`

“Command-line tool skeleton: ``main(argv)`` parses arguments, runs one subcommand and returns an exit code.”

- `cli.py::count`: Counts lines, words, and characters in a given text string.
- `cli.py::read_input`: Reads and returns file contents or stdin if path is '-'.
- `cli.py::build_parser`: Creates an ArgumentParser with a 'count' subcommand that accepts a file path.
- `cli.py::main`: Parses arguments, runs count on input, prints results, and returns exit code.
