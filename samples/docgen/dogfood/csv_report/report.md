# Project report

## Overview

`csv_report` is a Python project designed to analyze CSV data and display formatted results. Numerical processing is handled by `stats.py`, which computes column statistics for input CSV files, while `render.py` turns those summaries into Markdown or HTML. Users can interact with the project via the command-line entry point `report.py` to summarize numeric columns, or serve a web view using `serve.py` over an HTTP endpoint. The codebase includes four modules, a command-line interface, one web endpoint, and one test file using pytest.

## Design

| Component | Modules | What it is |
|---|---|---|
| `render.py` | 1 | Turn a summary into Markdown or HTML. |
| `report.py` | 1 | Command-line entry point: summarize the numeric columns of a CSV file. |
| `serve.py` | 1 | Optional tiny web view of a report. |
| `stats.py` | 1 | Column statistics for CSV files. |

## Implementation

- `stats.py`: Column statistics for CSV files.
- `render.py`: Turn a summary into Markdown or HTML.
- `report.py`: Command-line entry point: summarize the numeric columns of a CSV file.
- `serve.py`: Optional tiny web view of a report.

## Testing

1 test file(s) with 1 test functions.

```bash
pytest
```

## How to run

```bash
pip install -r requirements.txt
python report.py --input VALUE
python serve.py
```
