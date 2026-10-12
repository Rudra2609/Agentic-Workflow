"""ids, errors (taxonomy + retry classifier), tracing and config."""

import pytest

from hmap.core import ids
from hmap.core.config import REPO_ROOT, Settings, parse_cloud_role_map, parse_key_list, parse_role_map, read_env_file
from hmap.core.errors import ErrorCode, HmapError, InvalidMessage, classify, is_retryable
from hmap.core.tracing import child_traceparent, is_valid_traceparent, new_traceparent, parse_traceparent


def test_ulids_are_unique_and_time_ordered() -> None:
    values = [ids.new_ulid() for _ in range(200)]
    assert len(set(values)) == 200 and all(len(v) == 26 for v in values)
    assert ids.new_task_id().startswith("T-") and ids.new_execution_id().startswith("E-")


def test_retry_classifier() -> None:
    assert is_retryable(ErrorCode.TIMEOUT) and is_retryable("MODEL_TRANSIENT")
    for code in (ErrorCode.INVALID_MESSAGE, ErrorCode.AUTHORIZATION, ErrorCode.WRONG_RESULT, ErrorCode.CANCELLED):
        assert not is_retryable(code)
    assert classify(TimeoutError()) is ErrorCode.TIMEOUT
    assert classify(ConnectionRefusedError()) is ErrorCode.NETWORK
    assert classify(InvalidMessage("x")) is ErrorCode.INVALID_MESSAGE
    assert classify(RuntimeError("?")) is ErrorCode.INTERNAL_AGENT
    err = HmapError("boom", code=ErrorCode.TOOL_TRANSIENT)
    assert err.retryable and err.to_dict()["error_code"] == "TOOL_TRANSIENT"


def test_traceparent_child_keeps_trace_id() -> None:
    parent = new_traceparent()
    child = child_traceparent(parent)
    assert is_valid_traceparent(parent) and is_valid_traceparent(child)
    assert parse_traceparent(child).trace_id == parse_traceparent(parent).trace_id
    assert parse_traceparent(child).span_id != parse_traceparent(parent).span_id
    assert is_valid_traceparent(child_traceparent("garbage"))
    assert not is_valid_traceparent("00-" + "0" * 32 + "-" + "1" * 16 + "-01")  # all-zero trace id


def test_role_map_and_settings() -> None:
    assert parse_role_map("reasoner=qwen3.5:9b, embed=nomic-embed-text") == {
        "reasoner": "qwen3.5:9b", "embed": "nomic-embed-text"}
    with pytest.raises(ValueError):
        parse_role_map("reasoner")
    s = Settings.from_env({"HMAP_LLM_MODE": "fake", "HMAP_ROLE_MAP": "fast=m1", "HMAP_PLUGINS": "stubs, doc_intel",
                           "HMAP_LOG_JSON": "false", "HMAP_CLOUD_API_KEY": "secret"})
    assert s.llm_mode == "fake" and s.role_map == {"fast": "m1"} and not s.log_json
    assert s.enabled_plugins() == {"stubs", "doc_intel"} and Settings.from_env({}).enabled_plugins() is None
    assert "secret" not in repr(s)


def test_relative_paths_resolve_against_repo_root(tmp_path, monkeypatch) -> None:
    """Regression: `make api` runs from backend/ and scripts from the root; both must see the same artifact folder
    and the members' replay caches in <root>/samples/llm_cache (not backend/samples/...)."""
    monkeypatch.chdir(tmp_path)
    s = Settings.from_env({})
    assert s.artifact_root == REPO_ROOT / "data" / "artifacts"
    assert s.llm_cache_dir == REPO_ROOT / "samples" / "llm_cache"
    assert (REPO_ROOT / "backend" / "pyproject.toml").exists()
    assert Settings.from_env({"HMAP_ARTIFACT_ROOT": "x/y"}).artifact_root == REPO_ROOT / "x" / "y"
    assert Settings(artifact_root=tmp_path).artifact_root == tmp_path


def test_cloud_pool_settings() -> None:
    assert parse_key_list(" a, ,b,a ") == ["a", "b"] and parse_key_list(None) == []
    assert parse_cloud_role_map("coder=groq:m1|gemini:m2") == {"coder": [("groq", "m1"), ("gemini", "m2")]}
    with pytest.raises(ValueError, match="unknown provider"):
        parse_cloud_role_map("coder=openai:m")
    s = Settings.from_env({"HMAP_GROQ_API_KEYS": "gsk_test_1,gsk_test_2", "HMAP_GEMINI_API_KEYS": "AIza_test_1",
                           "HMAP_CLOUD_ROLE_MAP": "coder=groq:m1|gemini:m2,reasoner=gemini:m3"})
    assert s.cloud_keys("groq") == ["gsk_test_1", "gsk_test_2"] and s.cloud_keys("gemini") == ["AIza_test_1"]
    assert s.cloud_role_map["reasoner"] == [("gemini", "m3")] and s.cloud_ok
    assert not any(k in repr(s) + s.model_dump_json() for k in ("gsk_test_1", "gsk_test_2", "AIza_test_1"))
    legacy = Settings.from_env({"HMAP_CLOUD_BASE_URL": "https://h/v1", "HMAP_CLOUD_API_KEY": "secret"})
    assert legacy.cloud_keys("cloud") == ["secret"] and legacy.cloud_base_url_for("cloud") == "https://h/v1"


def test_env_file_is_read_with_inline_comments_and_quotes(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\n"
                   "HMAP_GROQ_API_KEYS=gsk_test_a,gsk_test_b      # one per teammate\n"
                   "HMAP_GEMINI_API_KEYS=                 # comma-separated\n"
                   "export HMAP_LLM_MODE='fake'\n"
                   'HMAP_CLOUD_ROLE_MAP="coder=groq:m1|gemini:m2"\n'
                   "not a valid line\n", encoding="utf-8")
    assert read_env_file(env) == {"HMAP_GROQ_API_KEYS": "gsk_test_a,gsk_test_b", "HMAP_GEMINI_API_KEYS": "",
                                  "HMAP_LLM_MODE": "fake", "HMAP_CLOUD_ROLE_MAP": "coder=groq:m1|gemini:m2"}
    monkeypatch.setenv("HMAP_ENV_FILE", str(env))
    monkeypatch.setenv("HMAP_LLM_MODE", "replay")                       # a real env var beats the file
    s = Settings.from_env()
    assert s.cloud_keys("groq") == ["gsk_test_a", "gsk_test_b"] and s.cloud_keys("gemini") == []
    assert s.llm_mode == "replay" and s.cloud_role_map["coder"] == [("groq", "m1"), ("gemini", "m2")]
    assert Settings.from_env({}).cloud_keys("groq") == []               # explicit dict ignores .env
    assert "gsk_test_a" not in repr(s)


def test_test_suite_never_reads_the_developer_env_file() -> None:
    import os

    assert os.environ["HMAP_ENV_FILE"] == "none"
    assert read_env_file(REPO_ROOT / "does-not-exist") == {}
