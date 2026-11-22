# Code summaries: csv_report

`csv_report` is a Python project designed to analyze CSV data and display formatted results. Numerical processing is handled by `stats.py`, which computes column statistics for input CSV files, while `render.py` turns those summaries into Markdown or HTML. Users can interact with the project via the command-line entry point `report.py` to summarize numeric columns, or serve a web view using `serve.py` over an HTTP endpoint. The codebase includes four modules, a command-line interface, one web endpoint, and one test file using pytest.

Public functions and classes: 7; described: 86 % (from docstrings or the model; the rest show their signature).

## `render.py`

“Turn a summary into Markdown or HTML.”

- `render.py::to_markdown`: Converts a summary dictionary into a Markdown table string with columns, min, max, mean, median.
- `render.py::to_html`: Creates an HTML table string showing each column and its mean value from a summary dictionary.

## `report.py`

“Command-line entry point: summarize the numeric columns of a CSV file.”

- `report.py::main`: `def main() -> None`

## `serve.py`

“Optional tiny web view of a report.”

- `serve.py::report`: Returns HTML rendering of summarized statistics from a CSV file.

## `stats.py`

“Column statistics for CSV files.”

- `stats.py::load`: Loads a CSV file into a list of dictionaries mapping column names to string values.
- `stats.py::numeric_columns`: Returns column names where all values can be converted to floats.
- `stats.py::summarize`: Computes min, max, mean, and median for each numeric column in the data.
