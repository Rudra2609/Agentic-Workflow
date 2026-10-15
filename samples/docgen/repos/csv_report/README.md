# CSV report

Summarizes the numeric columns of a CSV file (min, max, mean, median) as a Markdown or HTML table. The core uses
only the standard library (`csv`, `statistics`); Flask is needed only for the optional web view.

## Use
```bash
python report.py --input scores.csv
python report.py --input scores.csv --format html --output report.html
```

## Web view
`python serve.py` serves GET /report on port 5001 for the file named by `REPORT_CSV` (default `data.csv`).

## Code
- `stats.py`: `load()`, `numeric_columns()`, `summarize()`
- `render.py`: `to_markdown()`, `to_html()`
- `report.py`: the command line (`--input`, `--output`, `--format md|html`)

## Tests
```bash
pip install -r requirements.txt
pytest
```
