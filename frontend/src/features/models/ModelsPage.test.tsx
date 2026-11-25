// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Hardware, Registry, Routes } from "./types";

const setModelFlag = vi.fn(async () => ({}));
const pullModel = vi.fn(async () => ({ started: false, command: "ollama pull gemma4:12b", why: "run it in a terminal" }));
const registry: Registry = {
  ollama_up: false, error: "Ollama not running at http://127.0.0.1:11434",
  models: [
    { spec: { id: "qwen3.5:9b", family: "qwen35", params_b: 9, quant: "Q4_K_M", ctx: 262144, backend: "ollama", mem_gb: 5.6, tok_s: 6.3,
      roles_ok: ["reasoner", "coder"], status: "available" }, digest: null, source: "snapshot", pinned: false, resident_gb: null, last_seen: "" },
    { spec: { id: "gemma4:12b", family: "qwen35", params_b: 4, quant: "Q4_K_M", ctx: null, backend: "ollama", mem_gb: null, tok_s: null,
      roles_ok: [], status: "missing" }, digest: null, source: "snapshot", pinned: false, resident_gb: null, last_seen: "" },
    { spec: { id: "groq:openai/gpt-oss-120b", family: "openai", params_b: null, quant: null, ctx: 131072, backend: "cloud", mem_gb: null,
      tok_s: null, roles_ok: ["coder"], status: "available" }, digest: null, source: "cloud", pinned: true, resident_gb: null, last_seen: "" },
  ],
};
const routes: Routes = {
  enabled: true, now: "2026-11-01T10:00:00+00:00",
  summary: { decisions: 1, answered_by: { groq: 1 }, failed: 0, rules: { rules: 1 }, rate_limited: 1, attempts: 2 },
  routes: [{ id: "rd-1", at: "2026-11-01T09:59:58+00:00", decision: { role: "reasoner", model: "gpt-oss-120b", backend: "groq",
    reason: "gemini:gemini-3.6-flash last (gemini: no key usable right now)" }, plugin: "planning", est_tokens: 900,
    chain: ["groq:openai/gpt-oss-120b", "gemini:gemini-3.6-flash", "ollama:qwen3.5:9b"], rule: "rules",
    answered_by: "groq:openai/gpt-oss-120b", ok: true, latency_s: 1.2, attempts: 2, rate_limited: 1, error: "" }],
};
const hardware: Hardware = {
  hardware: { platform: "Darwin arm64", chip: "Apple M3", total_gb: 17.2, free_gb: 5.4, swap_used_gb: 3.1, gpu: "metal", docker_vm_gb: null,
    resident: {}, ollama: false, notes: ["3.1 GB of swap in use: speed numbers taken now are not representative"] },
  feasibility: [{ model: "qwen3.5:9b", fit: "fits", need_gb: 5.9, why: "5.9 GB needed" }],
  sizing: [{ ram_gb: 8, model_budget_gb: -0.5, fits: [] }, { ram_gb: 16, model_budget_gb: 7.5, fits: ["qwen3.5:9b"] }],
};

vi.mock("./client", () => ({
  getRegistry: async () => registry,
  syncRegistry: async () => registry,
  setModelFlag: (...a: unknown[]) => setModelFlag(...(a as [])),
  pullModel: (...a: unknown[]) => pullModel(...(a as [])),
  getRoutes: async () => routes,
  getHardware: async () => hardware,
  getBench: async () => ({ table: {}, table_path: "", files: {
    quick_qwen: { model: "qwen3.5:9b", mode: "replay", quality: 0.833, coverage: 1, suites: { extraction: { items: 10, answered: 10, score: 0.949 },
      coding: { items: 25, answered: 25, score: 0.68 } } },
    quick_groq: { model: "groq:qwen/qwen3.8-27b", mode: "record", quality: 0.9, coverage: 0.15, suites: { verify: { items: 36, answered: 30, score: 0.97 },
      coding: { items: 25, answered: 0, score: null } } } } }),
  getFineTune: async () => ({ runs: [], files: {} }),
}));

import { ModelsPage } from "./ModelsPage";

describe("ModelsPage", () => {
  afterEach(() => cleanup());

  it("shows the router's decisions, the models, the machine and the benchmark", async () => {
    render(<ModelsPage route="models" />);
    const decisions = await screen.findByRole("table", { name: "Route decisions" });
    expect(within(decisions).getByText("groq:openai/gpt-oss-120b → gemini:gemini-3.6-flash → ollama:qwen3.5:9b")).toBeTruthy();
    expect(within(decisions).getByText("answered by groq:openai/gpt-oss-120b")).toBeTruthy();
    expect(within(decisions).getByText("2 attempts, 1 rate-limited")).toBeTruthy();
    expect(screen.getByText("Router on")).toBeTruthy();
    expect(screen.getByText("Ollama not running")).toBeTruthy();
    const models = screen.getByRole("table", { name: "Models" });
    expect(within(models).getByText("pinned")).toBeTruthy();
    expect(await screen.findByText(/3.1 GB of swap in use/)).toBeTruthy();
    expect(screen.getByText(/16 GB → qwen3.5:9b/)).toBeTruthy();
    const bench = await screen.findByRole("table", { name: "Benchmark results" });
    expect(within(bench).getByText("0.833")).toBeTruthy();
    expect(within(bench).getByText("not answered (0/25)")).toBeTruthy();
    expect(within(bench).getByText(/partial/)).toBeTruthy();
  });

  it("disables a model and explains how to get a missing one", async () => {
    render(<ModelsPage route="models" />);
    const models = await screen.findByRole("table", { name: "Models" });
    fireEvent.click(within(models).getAllByRole("button", { name: "Disable" })[0]!);
    await waitFor(() => expect(setModelFlag).toHaveBeenCalledWith("qwen3.5:9b", "disable"));
    fireEvent.click(within(models).getByRole("button", { name: "How to get it" }));
    await waitFor(() => expect(pullModel).toHaveBeenCalledWith("gemma4:12b"));
    expect(await screen.findByText(/ollama pull gemma4:12b/)).toBeTruthy();
  });
});
