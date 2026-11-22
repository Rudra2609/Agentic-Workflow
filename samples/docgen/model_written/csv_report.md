# CSV‑Stats Reporter  

A tiny Python utility that reads a CSV file, computes basic statistics for every **numeric** column, and renders the results as either a Markdown table or an HTML snippet. It can be used from the command line, imported as a library, or served via a minimal Flask web app.

---

## Table of Contents  

- [Features](#features)  
- [Installation](#installation)  
- [Quick Start (CLI)](#quick-start-cli)  
- [Using the Library in Your Code](#using-the-library-in-your-code)  
- [Running the Optional Web Server](#running-the-optional-web-server)  
- [Configuration & Environment Variables](#configuration--environment-variables)  
- [API Reference](#api-reference)  
- [Testing](#testing)  
- [License](#license)  

---

## Features  

- **Automatic numeric column detection** – only columns where *all* rows contain a valid number are processed.  
- Computes **min, max, mean, median** for each numeric column.  
- Render output as:  
  - **Markdown** (perfect for README files, GitHub comments, etc.)  
  - **HTML** (ready to embed in a web page)  
- Simple **CLI** (`report.py`) with `--input`, `--output`, and `--format` options.  
- Optional **Flask** server (`serve.py`) that serves an HTML report at `/report`.  
- Fully typed, type‑annotated code and a small test suite with **pytest**.  

---

## Installation  

```bash
# Clone the repository
git clone https://github.com/yourusername/csv-stats-reporter.git
cd csv-stats-reporter

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

> **Note**: The only runtime dependency is **Flask** (for the optional web server). The CLI and library work with the Python standard library alone.

---

## Quick Start (CLI)

```bash
# Summarize a CSV and print Markdown to stdout
python report.py --input data.csv

# Save an HTML report to a file
python report.py --input data.csv --output report.html --format html
```

**Arguments**

| Argument | Description | Required? | Default |
|----------|-------------|-----------|---------|
| `--input` | Path to the CSV file to analyse | Yes | – |
| `--output` | Path to write the rendered report. If omitted, the report is printed to stdout. | No | – |
| `--format` | Output format: `md` for Markdown, `html` for HTML. | No | `md` |

---

## Using the Library in Your Code  

```python
from pathlib import Path
import stats
import render

csv_path = Path("data.csv")

# Load rows (list of dicts)
rows = stats.load(csv_path)

# Compute statistics for numeric columns
summary = stats.summarize(rows)

# Render as Markdown
md_report = render.to_markdown(summary)
print(md_report)

# Or render as HTML
html_report = render.to_html(summary)
print(html_report)
```

All functions are type‑annotated and documented in the source files.

---

## Running the Optional Web Server  

The `serve.py` script starts a tiny Flask app that serves an HTML report at `http://localhost:5001/report`.

```bash
# Set the CSV file to use (optional, defaults to data.csv in the project root)
export REPORT_CSV=/path/to/your/file.csv   # Linux/macOS
set REPORT_CSV=C:\path\to\file.csv          # Windows PowerShell

# Start the server
python serve.py
```

Visit **http://localhost:5001/report** in your browser to see the live report.

---

## Configuration & Environment Variables  

| Variable | Description | Default |
|----------|-------------|---------|
| `REPORT_CSV` | Path to the CSV file used by the Flask server (`serve.py`). | `data.csv` (relative to the project root) |

The CLI (`report.py`) does **not** use environment variables; all options are passed via command‑line arguments.

---

## API Reference  

### `stats.load(path: Path) -> list[dict[str, str]]`  
Read a CSV file and return a list of rows as dictionaries (keys are column headers).

### `stats.numeric_columns(rows: list[dict[str, str]]) -> list[str]`  
Return a list of column names that contain **only numeric values** across all rows.

### `stats.summarize(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]`  
Compute statistics for each numeric column. Returns a mapping:

```python
{
    "column_name": {
        "min": float,
        "max": float,
        "mean": float,
        "median": float
    },
    ...
}
```

### `render.to_markdown(summary: dict) -> str`  
Convert the summary dictionary into a Markdown table.

### `render.to_html(summary: dict) -> str`  
Convert the summary dictionary into a simple HTML table (only column name and mean are shown).

### `report.main()`  
Entry point for the CLI (`report.py`). Parses arguments, calls the above functions, and writes/prints the result.

### Flask app (`serve.py`)  
- `app.route("/report")` → returns an HTML table with the mean of each numeric column.

---

## Testing  

The project includes a minimal test suite using **pytest**.

```bash
# Run all tests
pytest
```

### Test coverage  

- **`tests/test_stats.py`** checks that `stats.summarize` correctly processes numeric columns and ignores non‑numeric ones.

You can add more tests under the `tests/` directory; they will be automatically discovered by pytest.

---

## License  

This project is released under the **MIT License** – see the `LICENSE` file for details.  

---  

*Happy reporting!*