"""Items 9.15-9.20 (platform work): the make demo pre-flight catches a stopped Ollama / busy port / low memory with
a fix line, the configuration reference has no drift and no secret, make report compiles the member documents,
and reset-demo refuses to delete anything outside the copy's data/ folder."""

import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType

from hmap.agents.docgen import compile_report, config_reference
from tests.docgen.conftest import ROOT


def preflight() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_preflight", ROOT / "scripts" / "demo_preflight.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_busy_port_is_caught_with_a_fix() -> None:
    pf = preflight()
    checks = pf.check_ports(busy=lambda p: p == 3000, infra_ours=lambda: False)
    bad = [c for c in checks if c.status == "FAIL"]
    assert [c.name for c in bad] == ["port 3000"] and "make stop" in bad[0].fix
    other = pf.check_ports(busy=lambda p: p == 5433, infra_ours=lambda: False)
    assert any(c.name == "infra ports" and c.status == "FAIL" for c in other)
    ours = pf.check_ports(busy=lambda p: p == 5433, infra_ours=lambda: True)
    assert all(c.status == "OK" for c in ours)


def test_stopped_ollama_and_missing_model() -> None:
    pf = preflight()

    def down(url: str) -> object:
        raise OSError("connection refused")

    no_keys = pf.check_model("live", {}, fetch=down)
    ollama = next(c for c in no_keys if c.name == "ollama")
    assert ollama.status == "FAIL" and "ollama serve" in ollama.fix and "OLLAMA_MODELS" in ollama.fix
    with_keys = pf.check_model("live", {"HMAP_GROQ_API_KEYS": "a,b"}, fetch=down)
    assert next(c for c in with_keys if c.name == "ollama").status == "WARN"
    assert "2 team key(s)" in next(c for c in with_keys if c.name == "cloud keys").detail
    up = pf.check_model("live", {}, fetch=lambda url: {"models": [{"name": "nomic-embed-text:latest"}]})
    missing = next(c for c in up if c.name == "model qwen3.5:9b")
    assert missing.status == "FAIL" and missing.fix == "ollama pull qwen3.5:9b"
    assert pf.check_model("replay", {}, fetch=down)[0].status == "OK"


def test_memory_floor_depends_on_the_mode() -> None:
    pf = preflight()
    assert pf.check_ram("live", 3.0).status == "FAIL"
    assert "make demo-replay" in pf.check_ram("live", 3.0).fix
    assert pf.check_ram("live", 3.0, keys=2).status == "OK"
    assert pf.check_ram("replay", 2.0).status == "OK"
    assert pf.check_ram("replay", 2.0, minimum=3).status == "FAIL"
    assert pf.check_ram("live", None).status == "WARN"


def test_preflight_runs_and_never_prints_a_key() -> None:
    out = subprocess.run(["python3", str(ROOT / "scripts" / "demo_preflight.py"), "--mode", "replay", "--json"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode in (0, 1) and '"name": "free memory"' in out.stdout
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith(("HMAP_GROQ_API_KEYS=", "HMAP_GEMINI_API_KEYS=")):
                for key in line.split("=", 1)[1].split("#")[0].split(","):
                    if key.strip():
                        assert key.strip() not in out.stdout


def test_configuration_reference_has_no_drift_and_no_secret() -> None:
    assert config_reference.drift() == {"read_by_code_not_in_env_example": [], "in_env_example_not_read": []}
    names = {v.name for v in config_reference.variables()}
    assert {"HMAP_DOCGEN_SUMMARY_LIMIT", "HMAP_LLM_MODE", "HMAP_TESTING_RUNTIME", "OLLAMA_BASE_URL"} <= names
    text = config_reference.render()
    assert "/Volumes/" not in text and "PosixPath" not in text
    committed = (ROOT / "docs" / "members" / "9" / "platform" / "configuration.md").read_text()
    assert committed == text, "regenerate: uv run python -m hmap.agents.docgen.config_reference"


def test_compile_report(tmp_path: Path) -> None:
    for n, title in ((1, "Member 1 — Core"), (2, "Docs")):
        d = tmp_path / "docs" / "members" / str(n)
        d.mkdir(parents=True)
        (d / "README.md").write_text(f"# {title}\n")
        (d / "research.md").write_text("# Research\n\n## Topic\n\nSee [design](design.md).\n" + "x" * 300)
    (tmp_path / "docs" / "members" / "1" / "design.md").write_text("# Design\n" + "y" * 300)
    out, missing = compile_report.compile_report(tmp_path, tmp_path / "reports" / "r.md")
    text = out.read_text()
    assert "## Member 1: Core" in text and "## Member 2: Docs" in text
    assert "#### Topic" in text                                       # headings moved down
    assert "](../docs/members/1/design.md)" in text                   # links rewritten from the report's folder
    assert missing == ["docs/members/1/eval.md", "docs/members/2/design.md", "docs/members/2/eval.md"]


def test_reset_refuses_paths_outside_data(tmp_path: Path) -> None:
    out = subprocess.run(["bash", str(ROOT / "scripts" / "reset_demo.sh"), "--yes"], capture_output=True, text=True,
                         env={**os.environ, "HMAP_ARTIFACT_ROOT": str(tmp_path)}, timeout=30)
    assert out.returncode == 2 and "refusing" in out.stdout
    assert tmp_path.exists()
