# autoresearch

This is an experiment to have the LLM do its own research.

## Setup

To set up a new experiment:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar29`). The branch `autoresearch/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current master.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `prepare.py` — fixed constants, data prep, tokenizer, dataloader, evaluation. Do not modify.
   - `train.py` — the file you modify. Model architecture, optimizer, training loop.
4. **Verify data exists**: Check that `~/.cache/autoresearch/` contains data shards and a tokenizer. If not, run `uv run prepare.py`.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once setup is done, kick off the experimentation loop below.

## Experimentation

Each experiment runs on a single GPU. The training script runs for a **fixed time budget of 5 minutes** (wall clock training time, excluding startup/compilation). You launch it simply as: `uv run train.py`.

**What you CAN do:**
- Modify `train.py` — this is the only file you edit. Everything is fair game: model architecture, optimizer, hyperparameters, training loop, batch size, model size, etc.

**What you CANNOT do:**
- Modify `prepare.py`. It is read-only. It contains the fixed evaluation, data loading, tokenizer, and training constants (time budget, sequence length, etc).
- Install new packages or add dependencies. You can only use what's already in `pyproject.toml`.
- Modify the evaluation harness. The `evaluate_bpb` function in `prepare.py` is the ground truth metric.

**The goal is simple: get the lowest val_bpb.** Since the time budget is fixed, you don't need to worry about training time — it's always 5 minutes. Everything is fair game: change the architecture, the optimizer, the hyperparameters, the batch size, the model size. The only constraint is that the code runs without crashing and finishes within the time budget.

**VRAM** is a soft constraint. Some increase is acceptable for meaningful val_bpb gains, but it should not blow up dramatically.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome — that's a simplification win. When evaluating whether to keep a change, weigh the complexity cost against the improvement magnitude. A 0.001 val_bpb improvement that adds 20 lines of hacky code? Probably not worth it. A 0.001 val_bpb improvement from deleting code? Definitely keep. An improvement of ~0 but much simpler code? Keep.

**The first run**: Your very first run should always be to establish the baseline, so you will run the training script as is.

**Think scientifically**: Before each experiment, form a hypothesis about *why* the change should help. After each experiment, interpret the result — did it match your prediction? What does that tell you about what to try next? Use your results to build a mental model of what matters in this training setup. Let your experiments inform each other rather than trying random changes.

## Output format

Once the script finishes it prints a summary like this:

```
---
val_bpb:          0.997900
training_seconds: 300.1
total_seconds:    325.9
peak_vram_mb:     45060.2
mfu_percent:      39.80
total_tokens_M:   499.6
num_steps:        953
num_params_M:     50.3
depth:            8
```

Note that the script is configured to always stop after 5 minutes, so depending on the computing platform of this computer the numbers might look different. You can extract the key metric from the log file:

```
grep "^val_bpb:" run.log
```

## Recording experiments (dashboard integration)

After every run (success or crash), record an `ExperimentRecord` to `experiments.jsonl`.
This file is the single source of truth for the dashboard — it reads this file and
renders the interactive experiment graph.

Use `schema.py` to create and append the record:

```python
import subprocess
from schema import ExperimentRecord, append_jsonl, load_records, next_id, current_best, git_short_hash, git_diff_stat, git_diff_hash, utc_now_iso

# After parsing run.log output:
best = current_best("experiments.jsonl")
status = "keep" if val_bpb < best else "discard"  # or "crash" if it crashed
delta = val_bpb - best if best != float("inf") else 0.0

record = ExperimentRecord(
    id=next_id("experiments.jsonl"),
    commit=git_short_hash(),
    parent_commit=parent_commit,       # from git rev-parse --short HEAD~1 (before reset)
    timestamp=utc_now_iso(),
    status=status,
    description="what you tried",

    val_bpb=val_bpb,
    delta=delta,

    num_steps=num_steps,
    training_seconds=training_seconds,
    total_seconds=total_seconds,
    mfu_percent=mfu_percent,
    total_tokens_M=total_tokens_m,

    peak_vram_gb=peak_vram_mb / 1024,
    num_params_M=num_params_m,
    depth=depth,

    train_bpb=train_bpb,               # final training loss (if available, else None)
    bpb_at_checkpoints=checkpoints,    # val_bpb sampled at 25%, 50%, 75%, 100% of training
    still_improving=still_improving,    # was loss still dropping in last 25% of steps?
    tokens_per_second=tok_per_sec,      # throughput (if available, else None)

    diff_stat=git_diff_stat(),
    diff_hash=git_diff_hash(),
)

# Add diff_text for inline rendering in the dashboard (not in ExperimentRecord schema)
d = record.to_dict()
try:
    diff_result = subprocess.run(
        ["git", "diff", "HEAD~1", "--", "train.py"],
        capture_output=True, text=True, timeout=5,
    )
    d["diff_text"] = diff_result.stdout or ""
except Exception:
    d["diff_text"] = ""

append_jsonl("experiments.jsonl", d)
```

**Key rules:**
- Write the record BEFORE doing `git reset` (on discard), so the commit hash is still valid.
- The `parent_commit` field is what links experiments into a tree in the dashboard.
- The `description` field should be a concise summary of what you changed and why.
- For crashes, set `val_bpb=0.0`, `delta=0.0`, and fill what you can. Use status `"crash"`.
- `experiments.jsonl` should NOT be git-committed — leave it untracked.
- `diff_text` is appended outside the schema so the dashboard can render inline diffs.

**Convergence tracking:** To populate the convergence chart and "still improving" badge:
- `bpb_at_checkpoints`: Sample `val_bpb` at 25%, 50%, 75%, and 100% of training steps. If not feasible, pass `[]`.
- `still_improving`: Set to `True` if the loss was still decreasing in the last 25% of steps. Parse from run.log or estimate from the last few logged losses.

In fleet mode, the visualization contract is:

- Each completed run must create `research/plans/<experiment_id>.json`.
- Each completed run must create `research/runs/<experiment_id>/config.json`, `metadata.json`, `result.json`, and `events.jsonl`.
- `result.json` must include `commit`, `parent_commit`, concise `analysis`, optional `outcome`, and final `metrics.val_bpb`.
- After runs complete, execute `uv run python orchestrator.py sync`. That exports root `experiments.jsonl`, which is what the local dashboard reads.

If a worker only updates `results.tsv` and skips the run artifact bundle, the run will be missing from `/history`.

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch/mar29` or `autoresearch/mar29-gpu0`).

If you are in fleet mode, interpret that strictly:

- the observer agent stays in the repo root
- the tool-builder also stays in the repo root
- each worker agent operates only in its own git worktree
- each worker branch should map to one worker identity, such as `autoresearch/<tag>-gpu0`
- workers should not edit the root checkout directly
- the observer controls dispatch by editing `research/research_brief.json`
- workers execute assigned hypotheses; they do not self-dispatch new experiment families
- workers should treat the generic autonomous loop below as background context only; their binding instructions come from the generated fleet Markdown

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Tune `train.py` with an experimental idea by directly hacking the code.
3. git commit
4. Run the experiment: `uv run train.py > run.log 2>&1` (redirect everything — do NOT use tee or let output flood your context)
5. Read out the results: `grep "^val_bpb:\|^peak_vram_mb:" run.log`
6. If the grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the Python stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up.
7. Record the experiment to `experiments.jsonl` (see "Recording experiments" above; do NOT git-commit this file)
8. If val_bpb improved (lower), you "advance" the branch, keeping the git commit
9. If val_bpb is equal or worse, you git reset back to where you started

The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, discard. And you're advancing the branch so that you can iterate. If you feel like you're getting stuck in some way, you can rewind but you should probably do this very very sparingly (if ever).

In fleet mode, reinterpret the loop by role. This overrides the generic loop above whenever there is a conflict:

- Observer: maintain `research/search_model.md`, update `research/research_brief.json` `hypothesis_queue`, assign hypotheses to idle workers, decide keep/discard/crash at the fleet level, and run `uv run python orchestrator.py sync` after each dispatch cycle.
- Tool-builder: watch `research/tools/registry.json`, publish reusable helper scripts under `research/tools/published/`, and mark requested tools as published once they are usable.
- GPU worker: read the generated assignment Markdown, execute the assigned hypothesis on the assigned GPU, write the required `research/plans/` + `research/runs/` artifact bundle for that experiment, report the outcome, and then wait for the next observer dispatch. Workers do not choose new experiment families and should not make the final keep/discard decision for the fleet unless explicitly told to.

**Timeout**: Each experiment should take ~5 minutes total (+ a few seconds for startup and eval overhead). If a run exceeds 10 minutes, kill it and treat it as a failure (discard and revert).

**Crashes**: If a run crashes (OOM, or a bug, or etc.), use your judgment: If it's something dumb and easy to fix (e.g. a typo, a missing import), fix it and re-run. If the idea itself is fundamentally broken, just skip it, log "crash" as the status in the tsv, and move on.

**NEVER STOP**: Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or gone from a computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of ideas, think harder — read papers referenced in the code, re-read the in-scope files for new angles, try combining previous near-misses, try more radical architectural changes. The loop runs until the human interrupts you, period.

As an example use case, a user might leave you running while they sleep. If each experiment takes you ~5 minutes then you can run approx 12/hour, for a total of about 100 over the duration of the average human sleep. The user then wakes up to experimental results, all completed by you while they slept!

## Dashboard

After a batch of runs has completed, regenerate the viewer input with:

```bash
uv run python orchestrator.py sync
uv run uvicorn dashboard.server:app --host 127.0.0.1 --port 8000
```

Then open:

- `/` for the latest-run summary
- `/history` for the lineage graph
