# Command-line tool

```bash
python cli.py --help
python cli.py count notes.txt
python -m unittest
```

Add a subcommand in `build_parser()` and handle it in `main()`; keep the logic in plain functions so tests can call
them directly.
