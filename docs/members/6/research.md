# Research — research verification (Member 6, written ahead of Sprint 6)

The verifier takes a `ResearchReport` from Member 5 (claims, each citing verbatim quotes with page hashes) and
decides per claim: **VERIFIED, UNSUPPORTED, CONFLICTING or NEEDS_MORE_RESEARCH**. Each topic below ends with
**→ plan**: what it means for the Sprint 6 design. The test data is ready in `samples/verify/` (86 labelled items, self-contained: it does not need Sprint 5's code).

## 1. Fact verification and claim checking
- **FEVER** (Thorne et al., 2018) set the standard task: given a claim, retrieve evidence, then label it
  Supported / Refuted / NotEnoughInfo. Most errors come from retrieval, not from the final label.
- **SciFact** (Wadden et al., 2020) shows that the same task on technical text needs sentence-level rationales,
  not whole documents.
- **Atomic claims:** FActScore (Min et al., 2023) splits long text into atomic facts and checks each against a
  source. A compound claim ("X and Y") is half right far more often than wrong.

**→ plan:** split claims into atomic claims first (6.1). Our verdicts map onto FEVER's labels (VERIFIED /
CONFLICTING ≈ Supported / Refuted; UNSUPPORTED / NEEDS_MORE_RESEARCH ≈ NotEnoughInfo). Judge against the quoted
sentence, not the whole page.

## 2. Entailment (NLI) — does the quote support the claim?
- **NLI models** label a premise / hypothesis pair as entailment / neutral / contradiction (SNLI, Bowman et al.,
  2015; MultiNLI, Williams et al., 2018).
- **NLI as a consistency checker:** SummaC (Laban et al., 2022) and the TRUE benchmark (Honovich et al., 2022) show
  NLI is a strong factual-consistency checker when applied sentence by sentence. AlignScore (Zha et al., 2023)
  improves on it with a unified alignment model.
- **An LLM judge can do the same job** with a constrained verdict, but is biased: position, verbosity,
  self-preference (Zheng et al., 2023).

**→ plan:** L2 = an LLM judge on role `judge`, a different model family from the researcher, short input (claim +
quote only), a constrained verdict + rationale (6.3). Check bias with the claim and quote swapped in order. Measure
on the `wrong_number`, `unsupported_claim` and `natural` items.

## 3. Hallucination detection
- **Kinds of error:** surveys (Ji et al., 2023; Huang et al., 2023) separate *intrinsic* errors (contradicting the
  source) from *extrinsic* ones (not supported by it).
- **SelfCheckGPT** (Manakul et al., 2023) needs no external source: sample several answers and flag statements
  they disagree on. Useful when there is no evidence, weak when there is.
- **Chain-of-Verification** (Dhuliawala et al., 2023) and **RARR** (Gao et al., 2023) generate their own check
  questions and revise using retrieved evidence. SAFE (Wei et al., 2024) runs a search per atomic fact.

**→ plan:**
- The cheapest detector is mechanical: Sprint 5 already guarantees quotes are verbatim, so **L1 re-checks every
  quote and hash for free**. It should catch 100 % of the 15 `fake_quote` items.
- Sampling-based checks (SelfCheckGPT) are a stretch idea for claims without evidence.

## 4. Attribution and citation evaluation
- **AIS**, "Attributable to Identified Sources" (Rashkin et al., 2023): a statement is attributable if a general
  reader would agree "according to this source, …".
- **ALCE** (Gao et al., 2023) measures citation recall (is each claim supported by its citations?) and precision
  (is each citation needed?).
- Liu et al. (2023, "Evaluating verifiability in generative search engines") found about half of generative-search
  sentences were not fully supported by their citations.

**→ plan:** report citation recall / precision per report alongside the verdicts (6.10). The 6 `natural` items are
exactly the over-reaching attributions these papers describe, taken from our own Sprint 5 output.

## 5. Independent retrieval and source comparison
- A verifier that only rereads the researcher's sources inherits its blind spots. Retrieval-augmented verification
  searches again with **independently written queries** (FEVER pipelines, SAFE).
- **Comparing sources:** credibility differs by domain; agreement across independent domains is stronger than
  repetition on one site; dates matter for "current" facts.

**→ plan:**
- **L3** reuses Member 5's search providers through their public interface, but with **its own query generator**
  that never sees the researcher's queries (6.4).
- **L4** compares numbers, dates and negations across ≥ 2 independent sources (6.5). Measure on the 15
  `contradiction` items (synthetic counter sources, labelled CONFLICTING).

## 6. Prompt injection (security part of Sprint 6)
- **Indirect prompt injection** (Greshake et al., 2023): instructions hidden in content the model reads (web pages,
  PDFs, repository files) can change its behaviour. The **OWASP Top 10 for LLM Applications** lists prompt
  injection as risk no. 1.
- **Defences in layers:** treat retrieved text as data (delimit and label it), strip hidden content, never let
  content trigger actions, and keep a regression suite of known attacks.

**→ plan (6.13):**
- Build the platform-wide injection suite from poisoned inputs per entry point: PDFs (Member 2), web pages
  (Member 5's `samples/research/adversarial/`, arriving with Sprint 5), repository files (Members 7 / 9), agent messages.
- The verifier itself reads untrusted quotes, so its prompts wrap them the same way Sprint 5's do.

## 7. Independence and the decision table
The verifier must not share the researcher's reasoning: a different model family, its own queries, no access to the
researcher's prompts.

**→ plan:** the aggregator (6.6) is a documented decision table, cheapest and most reliable layer first:

| L1 quote + hash | L2 entailment | L4 cross-source | Verdict |
|---|---|---|---|
| fails | — | — | UNSUPPORTED (at best) |
| passes | supports | no conflict | VERIFIED |
| passes | supports | conflict | CONFLICTING |
| passes | does not support | — | UNSUPPORTED |
| passes | unsure / too little evidence | — | NEEDS_MORE_RESEARCH → follow-up research (6.8) |

## 8. How the benchmark will be used (6.10)
1. Run L1 only, then L1 + L2, then all layers, on `samples/verify/benchmark.jsonl`.
2. Report per kind: recall of flagged errors; on the 20 `clean` items: the false-alarm rate.
3. Expected shape (to be measured): L1 alone catches the fake quotes and nothing else; L2 is needed for wrong
   numbers and unsupported claims; only L4 finds contradictions.

## References
Bowman et al. 2015 (SNLI) · Williams et al. 2018 (MultiNLI) · Thorne et al. 2018 (FEVER) · Wadden et al. 2020
(SciFact) · Laban et al. 2022 (SummaC) · Honovich et al. 2022 (TRUE) · Zha et al. 2023 (AlignScore) · Min et al.
2023 (FActScore) · Manakul et al. 2023 (SelfCheckGPT) · Dhuliawala et al. 2023 (Chain-of-Verification) · Gao et al.
2023 (RARR; ALCE) · Rashkin et al. 2023 (AIS) · Liu et al. 2023 (verifiability of generative search) · Wei et al.
2024 (SAFE / long-form factuality) · Ji et al. 2023, Huang et al. 2023 (hallucination surveys) · Zheng et al. 2023
(LLM-as-a-judge) · Greshake et al. 2023 (indirect prompt injection) · OWASP Top 10 for LLM Applications.
