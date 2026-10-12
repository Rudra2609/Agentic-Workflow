Write `column_means(csv_text: str) -> dict[str, float]`.

The first line is a comma-separated header. For each column, ignore empty cells; if every non-empty cell
parses as a float, include the column with the mean of those values. Skip columns that contain any
non-numeric value or that have no non-empty values. Use the `csv` module so quoted fields work.
