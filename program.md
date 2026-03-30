# autoresearch

This is an experiment to have the LLM do its own research.

## Setup

The top-level operating model is observer-centered N+2:

1. A `main` agent bootstraps the repository.
2. The `observer` controls experiment dispatch.
3. The `tool-builder` publishes reusable helpers when needed.
4. One GPU worker runs per GPU in its own worktree.

`program.md` is the binding document for the top-level `main` agent. Do not use it as the prompt for the observer or GPU workers after the fleet exists.

## Main Agent Bootstrap

Before any long-running autonomous loop begins, the `main` agent must do this in order:

1. Verify the environment, data, and git state.
2. Establish the local hardware baseline from the unmodified baseline config in `train.py`.
3. Use `https://github.com/karpathy/autoresearch` as the upstream benchmark reference. If the best-known Karpathy-style optimization is not already pinned in local state, inspect that repo's docs, commit history, and relevant diffs to recover the best-known configuration, then reproduce it on this same hardware and store it locally next to the baseline. Record the upstream commit or provenance you used.
4. Reset back to the baseline `train.py` after that benchmark comparison. Do not start autonomous search from the imported best-known optimization.
5. Treat the baseline config as the active reference config until a locally kept run from this repository beats it.
6. Initialize the observer + tool-builder + worker fleet.
7. Hand off control to the generated fleet prompts. After handoff, the observer is the scientific decision-maker of record.

To set up a new experiment:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar29`). The branch `autoresearch/<tag>` must not already exist - this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from the current default branch.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `prepare.py` — fixed constants, data prep, tokenizer, dataloader, evaluation. Do not modify.
   - `train.py` — the file you modify. Model architecture, optimizer, training loop.
4. **Verify data exists**: Check that `~/.cache/autoresearch/` contains data shards and a tokenizer. If not, run `uv run prepare.py`.
5. **Initialize the baseline record**: The first completed run must leave behind the canonical run artifact bundle. `results.tsv` will be regenerated from those artifacts by `uv run python orchestrator.py sync`.
6. **Confirm and go**: Confirm setup looks good.

Once setup is done, complete the bootstrap flow above before entering any long-running experimentation loop.

## Reference Config

The search should always start from the current reference configuration.

- At the very beginning, the reference configuration is the baseline config.
- The first run must establish the baseline on the target hardware.
- The Karpathy best-known optimization comes from the upstream reference repo `https://github.com/karpathy/autoresearch` and is stored locally as a benchmark comparison, not as the live starting point for autonomous search.
- After a locally authored run is kept, that kept config becomes the new best-known reference for future hypotheses.
- When you branch new experiments, mutate the best-known reference config, not the original baseline.
- Warm-start findings can inform your hypotheses, but they do not replace the local baseline. The active reference config only advances from locally kept runs in this repository.

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

**The first run**: Your very first run should always be to establish the baseline, so you will run the training script as is. Treat that baseline config as the starting reference until a better run is kept.

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

## Logging Results

In N+2 mode, do not hand-edit `results.tsv`. The canonical source of truth is the run artifact bundle under `research/plans/` and `research/runs/`. `results.tsv` and `experiments.jsonl` are regenerated from those artifacts by `uv run python orchestrator.py sync`.

The canonical run artifact bundle is:

- `research/plans/<experiment_id>.json`
- `research/plans/<experiment_id>.md`
- `research/runs/<experiment_id>/config.json`
- `research/runs/<experiment_id>/metadata.json`
- `research/runs/<experiment_id>/result.json`
- `research/runs/<experiment_id>/events.jsonl`

The semantics are:

- The observer authors `research/plans/<experiment_id>.json` and `research/plans/<experiment_id>.md` before dispatch.
- The worker records execution artifacts under `research/runs/<experiment_id>/`.
- The worker writes provisional execution status only: `completed` or `failed`.
- If a run crashes before a real validation metric exists, the worker or observer must still leave a numeric crash footprint in `result.json`: `metrics.val_bpb = 0.0`, and if no memory metric exists, `metrics.peak_vram_mb = 0.0`.
- The observer stamps the terminal fleet decision in `result.json` as `decision_status`: `keep`, `discard`, `crash`, or `replicate`.
- Only after that observer decision and a `sync` should the run be treated as final in `results.tsv` and `/history`.

The regenerated TSV still has 5 columns:

```
commit	val_bpb	memory_gb	status	description
```

1. git commit hash (short, 7 chars)
2. val_bpb achieved (e.g. 1.234567) — use 0.000000 for crashes
3. peak memory in GB, round to .1f (e.g. 12.3 — divide peak_vram_mb by 1024) — use 0.0 for crashes
4. status: `keep`, `discard`, or `crash`
5. short text description of what this experiment tried

Example:

```
commit	val_bpb	memory_gb	status	description
a1b2c3d	0.997900	44.0	keep	baseline
b2c3d4e	0.993200	44.2	keep	increase LR to 0.04
c3d4e5f	1.005000	44.0	discard	switch to GeLU activation
d4e5f6g	0.000000	0.0	crash	double model width (OOM)
```

Each run must also have a scientific decision Markdown note at `research/plans/<experiment_id>.md`. That note is what `/history` uses to show the scientific reasoning behind the run.

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch/mar29` or `autoresearch/mar29-gpu0`).

If you are in fleet mode, interpret that strictly:

- the main agent bootstraps the baseline, best-known reference, and fleet handoff
- the observer agent stays in the repo root
- the tool-builder also stays in the repo root
- each worker agent operates only in its own git worktree
- each worker worktree should expose `research/` as the shared repo-root research state, not as an isolated local directory
- each worker branch should map to one worker identity, such as `autoresearch/<tag>-gpu0`
- workers should not edit the root checkout directly
- the observer controls dispatch by editing `research/research_brief.json`
- workers execute assigned hypotheses; they do not self-dispatch new experiment families
- workers make dedicated experiment commits before they train so `commit` and `parent_commit` stay explicit
- workers stop after writing execution artifacts; the observer stamps the final decision and controls whether the branch should advance or reset
- workers should treat the generic autonomous loop below as background context only; their binding instructions come from the generated fleet Markdown

If the fleet has already been initialized, the role-specific generated Markdown overrides the generic loop below.

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Tune `train.py` with an experimental idea by directly hacking the code.
3. git commit
4. Run the experiment: `uv run train.py > run.log 2>&1` (redirect everything — do NOT use tee or let output flood your context)
5. Read out the results: `grep "^val_bpb:\|^peak_vram_mb:" run.log`
6. If the grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the Python stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up.
7. Record the canonical run artifact bundle, then run `uv run python orchestrator.py sync` to regenerate `results.tsv`
8. If val_bpb improved (lower), you "advance" the branch, keeping the git commit
9. If val_bpb is equal or worse, you git reset back to where you started

The idea is that you are a completely autonomous researcher trying things out. If they work, keep. If they don't, discard. The config reference advances with the best kept run, so later hypotheses should always start from the strongest known point rather than from the original baseline. If you feel like you're getting stuck in some way, you can rewind but you should probably do this very very sparingly (if ever).

In fleet mode, reinterpret the loop by role. This overrides the generic loop above whenever there is a conflict:

- Observer: maintain `research/search_model.md`, update `research/research_brief.json` `hypothesis_queue`, author the per-run `research/plans/<experiment_id>.md` scientific note, assign hypotheses to idle workers, stamp `decision_status`, and run `uv run python orchestrator.py sync` after each dispatch cycle.
- Tool-builder: watch `research/tools/registry.json`, publish reusable helper scripts under `research/tools/published/`, and mark requested tools as published once they are usable.
- GPU worker: read the generated assignment Markdown, execute the assigned hypothesis on the assigned GPU, create a dedicated experiment commit, write the required execution artifacts under `research/runs/`, report the outcome, and then wait for the next observer dispatch. Workers do not choose new experiment families and do not make the final keep/discard decision for the fleet.

**Timeout**: Each experiment should take ~5 minutes total (+ a few seconds for startup and eval overhead). If a run exceeds 10 minutes, kill it and treat it as a failure (discard and revert).

**Crashes**: If a run crashes (OOM, or a bug, or etc.), use your judgment: If it's something dumb and easy to fix (e.g. a typo, a missing import), fix it and re-run. If the idea itself is fundamentally broken, mark it as `crash`, ensure the artifact bundle still includes `result.json.metrics.val_bpb = 0.0` and `metrics.peak_vram_mb = 0.0` when no real values exist, run `sync`, and move on.

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
