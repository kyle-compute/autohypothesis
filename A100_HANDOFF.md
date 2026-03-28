# A100-SXM4 Handoff

This document is for the agent/operator bringing this repo up on a 2x A100-SXM4 machine.

Goal: verify that CUDA training, telemetry, orchestration, and the 2-worker fleet all work on the target node before leaving autoresearch running unattended.

## Rules

- Run everything from the repo root.
- Use `uv run ...`, not bare `python3 ...`.
- Re-generate fleet files on the new machine. The generated prompt files contain machine-specific absolute paths.
- Treat `research/` as shared memory for the whole fleet.
- Do not trust the fleet until a real training run emits live worker status and a completed run artifact.

## Success Criteria

The bring-up is successful only if all of these are true:

1. `torch` sees 2 CUDA GPUs and both are A100-class devices.
2. A direct `train.py` run completes on GPU `0`.
3. `sync`, `status`, and `monitor` work from `orchestrator.py`.
4. `init-fleet --gpus 0,1 --create-worktrees` succeeds on the target machine.
5. `dispatch --dry-run` produces one launch command for `worker-gpu0` and one for `worker-gpu1`.
6. A real `dispatch` creates live worker JSON files and run event logs.

If any of those fail, fix that first. Do not start autonomous research yet.

## 1. Environment Bring-Up

Install dependencies and verify CUDA visibility:

```bash
uv sync
uv run python -c "import torch; print('torch', torch.__version__); print('cuda', torch.cuda.is_available()); print('count', torch.cuda.device_count()); [print(i, torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]"
nvidia-smi --query-gpu=index,name,memory.total --format=csv
```

Expected:

- `torch.cuda.is_available()` is `True`
- `torch.cuda.device_count()` is `2`
- GPUs are `A100-SXM4-*` or equivalent A100 SXM names

If this fails, stop. The Python/CUDA environment is not ready.

## 2. Data Preparation

Run the one-time data/tokenizer setup:

```bash
uv run prepare.py
```

This should populate the cached training data and tokenizer if they are missing.

## 3. Single-GPU Smoke Test

Run one direct training job on GPU `0` before involving the orchestrator:

```bash
CUDA_VISIBLE_DEVICES=0 uv run train.py > baseline.log 2>&1
tail -n 40 baseline.log
grep "^val_bpb:\|^peak_vram_mb:\|^mfu_percent:\|^total_seconds:" baseline.log
```

Expected:

- The log reports an NVIDIA CUDA device
- CUDA capability is `8.0` on A100-SXM4
- The training loop runs for the fixed time budget and prints a final summary
- No Python traceback

Important:

- On A100, `train.py` should take the non-Hopper attention path. If it behaves like an H100-only path, inspect that before proceeding.
- If this direct run fails, do not continue to fleet bring-up.

## 4. Orchestrator Smoke Test

Verify the shared-state layer without launching workers yet:

```bash
uv run python orchestrator.py --help
uv run python orchestrator.py sync
uv run python orchestrator.py status
uv run python orchestrator.py monitor --interval 1 --iterations 1
```

Expected:

- `sync` writes under `research/aggregate` and `research/live`
- `status` runs without crashing
- `monitor` prints a summary line and exits

## 5. Initialize the 2-Worker Fleet

Create fresh worktrees and fleet prompts on the A100 box:

```bash
uv run python orchestrator.py init-fleet --tag <tag> --gpus 0,1 --create-worktrees
uv run python orchestrator.py sync
uv run python orchestrator.py status
```

Use a fresh tag, for example `mar28-a100`.

Expected files:

- `worktrees/worker-gpu0`
- `worktrees/worker-gpu1`
- `research/fleet/main-agent.md`
- `research/fleet/worker-prompts/worker-gpu0.md`
- `research/fleet/worker-prompts/worker-gpu1.md`

Expected status output:

- `worker-gpu0` shows `state=idle`
- `worker-gpu1` shows `state=idle`

If the workers do not show up as idle, fix that before moving on.

## 6. Dispatch Dry-Run

Verify launch commands before starting real runs:

```bash
uv run python orchestrator.py dispatch --dry-run
```

Expected:

- One launch command for `worker-gpu0`
- One launch command for `worker-gpu1`
- Each command points at the corresponding worktree `train.py`
- Each command writes telemetry to `research/runs/exp-XXXX`

This is the place to catch bad paths before spending GPU time.

## 7. Real Two-GPU Telemetry Test

Start the shared monitor in one terminal:

```bash
uv run python orchestrator.py monitor --interval 5
```

In another terminal, dispatch real work:

```bash
uv run python orchestrator.py dispatch
```

Then check status:

```bash
uv run python orchestrator.py status
```

While the runs are active, verify these files appear:

- `research/live/workers/worker-gpu0.json`
- `research/live/workers/worker-gpu1.json`
- `research/runs/exp-XXXX/events.jsonl`
- `research/runs/exp-YYYY/events.jsonl`

Expected live behavior:

- `status` shows workers in `launching` or `running`
- `monitor` reports `active=2 free=0`
- worker JSON files contain changing progress fields
- each run directory accumulates `events.jsonl`

## 8. Completion Checks

After the runs end, verify:

```bash
uv run python orchestrator.py sync
uv run python orchestrator.py status
ls research/runs/exp-*
```

Each completed run should have:

- `config.json`
- `events.jsonl`
- `metadata.json`
- `run.log`

Note:

- A completed run is not scientifically finalized until it is recorded as `keep`, `discard`, `replicate`, or `crash`.
- Until that happens, aggregate state may show `completed_unrecorded`, which is expected.

## 9. Multi-Agent Startup Layout

Once the checks above pass, the recommended 4-terminal layout is:

1. Terminal 1, repo root: `uv run python orchestrator.py monitor --interval 5`
2. Terminal 2, repo root: main/meta agent reading `research/fleet/main-agent.md`
3. Terminal 3, `worktrees/worker-gpu0`: worker agent reading its generated worker prompt
4. Terminal 4, `worktrees/worker-gpu1`: worker agent reading its generated worker prompt

The main agent should:

- watch live worker status
- record completed runs into the scientific log
- refresh shared briefs with `sync`
- dispatch new work only when a worker becomes free

The worker agents should:

- edit only their own worktree
- read shared fleet state before each new experiment
- avoid duplicating peer work unless intentionally replicating a result

## 10. Known Caveats

- `python3 train.py --help` can fail on a host that does not have repo dependencies in the system Python. This is normal here. Use `uv run train.py ...` instead.
- Fleet prompt files are machine-specific because they include absolute paths. Always regenerate them with `init-fleet` on the target machine.
- `init-fleet --create-worktrees` requires a git-initialized repo with a baseline commit. If you are reorganizing the repo first, re-enable the worktree flow only after `git init` and the initial commit.
- `dispatch` launches runs, but scientific decisions still require recording outcomes back into the knowledge base.
- The local Mac validation only covered orchestration behavior and dry-run dispatch. Actual CUDA runtime validation must happen on the A100 node.

## Go / No-Go

Go only if:

- the direct GPU smoke test passes
- the fleet initializes cleanly
- dry-run dispatch looks correct
- a real dispatch writes live status and event logs
- at least one real run reaches `metadata.json` without crashing

If any of those do not happen, stop autoresearch and fix the issue before leaving the system unattended.
