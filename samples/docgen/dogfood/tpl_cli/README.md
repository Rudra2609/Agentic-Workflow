# tpl_cli

`tpl_cli` provides a command-line interface skeleton designed to process arguments, execute selected subcommands, and return exit codes. It offers a lightweight, ready-to-use starting point for developers who need to build command-line applications.

## Run
```bash
python cli.py --help
```

## Architecture

```mermaid
flowchart LR
  cli(["cli.py"])
```

More: [architecture](architecture.md).

## Code

- `cli.py`: “Command-line tool skeleton: ``main(argv)`` parses arguments, runs one subcommand and returns an exit code.”

## Tests

```bash
pytest
```
1 test file(s) with 3 test functions: `test_cli.py`.
