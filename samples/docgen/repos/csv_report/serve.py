"""Optional tiny web view of a report."""

import os
from pathlib import Path

from flask import Flask

import render
import stats

app = Flask(__name__)
DATA = Path(os.environ.get("REPORT_CSV", "data.csv"))


@app.route("/report")
def report() -> str:
    return render.to_html(stats.summarize(stats.load(DATA)))


if __name__ == "__main__":
    app.run(port=5001)
