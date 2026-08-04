# HCP Content Engine

Generates promotional content for healthcare professionals that is grounded in
an approved claim set and checked for regulatory compliance before a human
signs off.

**Core principle: the AI never invents a claim.** It assembles and rephrases
pre-approved statements, and every sentence traces back to a labelled source.

---

## The problem

Pharmaceutical companies need to reach many doctors with content relevant to
each one, but two constraints collide:

1. **Physician access is shrinking.** Around half of practices restrict sales
   rep access, and most doctors now report finding digital resources more
   useful than remote rep visits. Generic email blasts get ignored.
2. **Every claim is regulated.** Promotional content cannot make off-label
   claims, cannot state anything unsubstantiated by the label, and must carry
   fair balance — risks presented alongside benefits. Every asset goes through
   medical-legal-regulatory (MLR) review, which is slow and expensive.

So teams default to generic content that doctors ignore, or bottleneck on
manual review. Industry data puts the waste starkly: content production is
rising sharply year over year, yet field teams rarely or never use around 77%
of approved assets.

In India, this stopped being optional. The Uniform Code for Pharmaceutical
Marketing Practices became **mandatory in 2024** — the word "voluntary" was
removed and compliance is enforced with penalties.

## What this does

Given a doctor profile (specialty, therapy area, adoption stage) and a channel,
it retrieves the relevant approved claims, drafts content constrained to them,
runs four compliance rules, and presents the result to a human reviewer with
every finding explained and every claim traced to its label section.

## Compliance by design — four layers

No single layer is trusted. Each catches what the others cannot.

**1. Input layer.** `assemble_claim_set()` always injects boxed warnings and
contraindications into the claim set, regardless of what retrieval scored as
relevant. The generator therefore *cannot* produce benefit-only content,
because it never receives a benefit-only claim set. This is a structural
guarantee, not a check we hope fires later.

**2. Prompt layer.** Closed-book prompting. The model is given the complete set
of permitted assertions and told that is everything it may claim. The task
shifts from recall to arrangement — the model is not remembering facts about
the drug, it is rephrasing supplied ones. That is a far smaller failure
surface, and it is why a local 8B model is safe enough to use here.

**3. Verification layer.** The model reports which claim IDs it drew on. Every
reported ID is checked against the knowledge base. A fabricated ID means the
model invented material, and generation fails loudly rather than passing it
downstream.

**4. Compliance layer.** Four rules, deterministic first:

| Rule | Type | What it catches |
|---|---|---|
| `BANNED_TERM` | regex | Unsubstantiated superlatives — "safest", "proven", "well tolerated" |
| `UNVERIFIED_CLAIM` | deterministic | Content citing claims no human has confirmed against the label |
| `FAIR_BALANCE` | deterministic | Benefits with no risk information; missing boxed warnings |
| `LLM_JUDGE` | model | Distorted claim strength, widened scope, implied off-label use |

Deterministic rules run first because they are free, instant, and structurally
incapable of hallucinating. The model is only asked to do what regex cannot:
read for meaning.

## An honest note on the LLM judge

The judge runs **advisory by default** (`judge_can_block: false`). This is a
measured decision, not a weakening.

In testing, the local 8B model produced false positives — flagging a verbatim
restatement of the approved indication as off-label, and inventing a rule about
dose specification that does not exist. Feeding those back into the revision
loop made drafts *worse* across attempts, because the model was chasing
phantom problems and degrading working content.

A blocking rule needs near-zero false positives, since every one burns a
revision cycle. An 8B model does not meet that bar. An advisory rule with false
positives is still valuable — it surfaces things a human dismisses in seconds,
and it catches real issues the deterministic rules cannot see (it correctly
found a missing second boxed warning that `FAIR_BALANCE` passed).

Set `HCP_JUDGE_CAN_BLOCK=true` to restore blocking with a stronger model.

## Human authority is not delegated

Every claim carries a `verified` flag defaulting to `False`. An LLM can extract
candidate claims from a label, classify them, and pre-fill their references —
collapsing hours into minutes. But a human must confirm each one.

The reason is structural, not a matter of model quality: if the claim set is
verified by a model, the safety argument becomes circular. There would be no
external ground truth anywhere in the loop. If a dosing statement were
transcribed wrong, every downstream guarantee would operate perfectly on wrong
data.

The decision store is **append-only** — no update, no delete. A decision records
the compliance flags exactly as they stood when the reviewer saw them, so the
audit reflects what was actually in front of them. Corrections are new records,
not rewrites.

## Architecture

```
Profile + intent
       |
  [ retrieve ]  <- approved claims KB (+ mandatory risk claims injected)
       |
  [ generate ]  <- closed-book prompt, claim IDs verified on output
       |
  [  check   ]  <- 4 compliance rules
       |
   passed? --no--> [ revise ] --(max 3 attempts)--> [ blocked ]
       | yes
       v
[ pending human review ] -> approve / reject -> append-only audit log
```

The generate → check → revise cycle is a LangGraph state machine with
conditional edges and a retry limit.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | The generate/check/revise loop is a natural state machine with a cycle |
| LLM | Ollama (`llama3.1:8b`) | Runs locally, no API key, no data leaves the machine |
| Retrieval | TF-IDF (scikit-learn) | Small corpus of precise clinical vocabulary; fully explainable |
| API | FastAPI | Type-driven validation and auto-generated docs |
| Store | SQLite | Append-only audit log, no server to run |
| UI | Next.js + Tailwind | Document-and-margin review layout |

**Why TF-IDF and not embeddings.** In a claims KB, "nonvalvular atrial
fibrillation" and "valvular atrial fibrillation" are different indications with
different approved uses. Embeddings would score them as near-identical.
Retrieving the wrong one is a compliance failure, not a ranking annoyance —
exact terminology is the signal. TF-IDF is also explainable: `explain()` returns
which terms drove each match, which feeds the "show your work" UI directly.

## Running it

Requires Python 3.11+, Node 18+, and [Ollama](https://ollama.com).

```bash
ollama pull llama3.1:8b
```

**Backend**

```bash
cd backend
pip install -e ".[dev]"
uvicorn hcp_engine.api.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. API docs at http://localhost:8000/docs.

## Configuration

Every setting is overridable by environment variable with an `HCP_` prefix — see
`backend/.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `HCP_OLLAMA_MODEL` | `llama3.1:8b` | Model for generation and judging |
| `HCP_OLLAMA_NUM_CTX` | `4096` | Context window; caps VRAM allocation |
| `HCP_MAX_ATTEMPTS` | `3` | Revision attempts before giving up |
| `HCP_STRICT_VERIFICATION` | `false` | Block content citing unverified claims |
| `HCP_JUDGE_CAN_BLOCK` | `false` | Let the LLM judge block, not just advise |

## A deployment finding

Closed-book grounding has a VRAM cost. Putting the entire approved claim set in
every prompt is what makes the compliance argument work — and it is also what
makes the context large.

On an 8GB mobile GPU, `qwen2.5:14b-instruct` (~9GB at Q4) crashed the Ollama
runner outright. `llama3.1:8b` (~4.7GB) with `num_ctx=4096` runs comfortably.

Constrained hardware forces a smaller model, which means weaker instruction
following, which means the revision loop does more work. This is precisely why
the defence-in-depth layers exist: **the architecture has to stay safe when the
model is weak.**

## Limitations

- **The seed claims are scaffolding.** `backend/data/claims/apixaban.json` is
  built from public prescribing information and every entry is
  `verified: false`. Each must be checked line by line against the current
  approved label — and, for India, the CDSCO package insert — before this is
  used for anything beyond a local demo.
- One drug, three channels. Multi-drug support is a data question, not a code
  one.
- The UCPMP-specific rule set is not yet implemented; the `Rule` protocol makes
  it a one-class addition.
- No authentication. The reviewer name is self-reported.
