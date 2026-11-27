import json
from pathlib import Path

from hmap.agents.models.finetune import data, serve, train
from hmap.agents.models.finetune import eval as ft_eval


def test_dataset_from_the_recordings(tmp_path: Path) -> None:
    stats = data.build(out_dir=tmp_path)
    assert stats["examples"] >= 200 and stats["enough"]
    train_rows = [json.loads(line) for line in (tmp_path / "train.jsonl").read_text().splitlines()]
    assert len(train_rows) == stats["splits"]["train"]["examples"]
    assert all([m["role"] for m in r["messages"]] == ["system", "user", "assistant"] for r in train_rows)
    # contamination (trap T15): no evaluation claim anywhere in the data, and no claim in two splits
    held = data.eval_claims()
    claims = {}
    for split in ("train", "valid", "test"):
        for line in (tmp_path / f"{split}.jsonl").read_text().splitlines():
            c = data.norm(data.claim_of(json.loads(line)["messages"][1]["content"]) or "")
            assert c not in held
            claims.setdefault(c, set()).add(split)
    assert all(len(s) == 1 for s in claims.values())
    assert stats["drops"]["contamination: an evaluation claim"] > 0


def test_heldout_set_is_m6_with_gold_labels() -> None:
    items = ft_eval.heldout_items()
    assert len(items) >= 50 and {i["gold"] for i in items} == {"supports", "not_enough"}
    assert items[0]["messages"][0]["content"].startswith(ft_eval.HINT)
    assert data.SYSTEM_PREFIX in items[0]["messages"][0]["content"] and len(items[0]["messages"]) == 2
    assert ft_eval.verdict_of('{"rationale": "x", "verdict": "not_enough"}') == "not_enough"
    assert ft_eval.verdict_of("I think it supports it") is None
    acc = ft_eval.score_judge(items[:2], {items[0]["id"]: f'{{"verdict": "{items[0]["gold"]}"}}'})
    assert acc["n"] == 2 and acc["invalid"] == 1 and acc["accuracy"] in (0.5, 1.0)
    refuted = ft_eval.score_judge([{"id": "x", "gold": "not_enough"}], {"x": '{"verdict": "refutes"}'})
    assert refuted["accuracy"] == 1.0 and refuted["strict"] == 0.0     # same platform verdict (UNSUPPORTED)


def test_training_log_parsing_and_commands() -> None:
    out = "Iter 1: Val loss 0.912, Val took 3s\nIter 10: Train loss 0.700, It/sec 0.3\nIter 20: Val loss 0.650"
    assert train.parse_losses(out) == {"train": [(10, 0.7)], "val": [(1, 0.912), (20, 0.65)]}
    table = ("\x1b[38;5;244m 120\x1b[0m    \x1b[1;35mval\x1b[0m \x1b[1m0.459\x1b[0m    3.31s\n"
             "  130    0.620 ▼    49    34.6k\n")
    assert train.parse_losses(table) == {"train": [(130, 0.62)], "val": [(120, 0.459)]}
    cmd = serve.mlx_server_command(Path("/x/adapter"))
    assert "--adapter-path" in cmd and train.BASE in cmd
