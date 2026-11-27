"""Child script for :mod:`.eval` (runs under ``uv run --with mlx-lm``, so it imports nothing from hmap): greedy
answers for a JSONL of chat prompts with the base model, optionally plus a LoRA adapter.

    python mlx_generate.py <base> <adapter or -> <prompts.jsonl> <answers.jsonl> <max_tokens>
"""

import json
import sys
import time


def main() -> None:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    base, adapter, prompts_path, out_path, max_tokens = sys.argv[1:6]
    model, tokenizer = load(base, adapter_path=None if adapter == "-" else adapter)
    sampler = make_sampler(temp=0.0)
    with open(prompts_path, encoding="utf-8") as f, open(out_path, "w", encoding="utf-8") as out:
        for line in f:
            item = json.loads(line)
            prompt = tokenizer.apply_chat_template(item["messages"], add_generation_prompt=True, tokenize=False,
                                                   enable_thinking=False)
            started = time.perf_counter()
            text = generate(model, tokenizer, prompt=prompt, max_tokens=int(max_tokens), sampler=sampler)
            out.write(json.dumps({"id": item["id"], "text": text, "seconds": round(time.perf_counter() - started, 2)})
                      + "\n")
            out.flush()


if __name__ == "__main__":
    main()
