<script lang="ts">
	import { onMount } from 'svelte';
	import type { Experiment, ParamChange, Plateau, PlateauChild } from '$lib/types';
	import { HYPERPARAM_KEYS } from '$lib/types';
	import { fetchExperiments } from '$lib/api';
	import { connectSSE } from '$lib/stores.svelte';
	import RunGraph from '$lib/components/RunGraph.svelte';
	import InsightSidebar from '$lib/components/InsightSidebar.svelte';
	import DiffViewer from '$lib/components/DiffViewer.svelte';

	let experiments: Experiment[] = $state([]);
	let selectedExp: Experiment | null = $state(null);
	let showInsights = $state(true);

	onMount(async () => {
		experiments = await fetchExperiments();
		const disconnect = connectSSE((exp) => {
			experiments = [...experiments, exp];
		});
		return disconnect;
	});

	// Build plateaus for insight sidebar
	function paramDiff(child: Experiment, parent: Experiment): ParamChange[] {
		const changes: ParamChange[] = [];
		for (const key of HYPERPARAM_KEYS) {
			const cv = child[key]; const pv = parent[key];
			if (cv != null && pv != null && String(cv) !== String(pv))
				changes.push({ key, from: pv as string | number, to: cv as string | number });
		}
		return changes;
	}

	let plateaus = $derived.by((): Plateau[] => {
		const kept = experiments.filter(e => e.status === 'keep').sort((a, b) => a.id - b.id);
		return kept.map(parent => {
			const children: PlateauChild[] = experiments
				.filter(e => e.parent_commit === parent.commit && e.id !== parent.id)
				.sort((a, b) => a.id - b.id)
				.map(exp => ({ exp, paramChanges: paramDiff(exp, parent) }));
			return { parent, children };
		});
	});

	function onSelectExp(exp: Experiment | null) {
		selectedExp = exp;
	}

	let selectedParent = $derived(
		selectedExp?.parent_commit
			? experiments.find(e => e.commit === selectedExp!.parent_commit) ?? null
			: null
	);

	let selectedParams = $derived.by((): ParamChange[] => {
		if (!selectedExp || !selectedParent) return [];
		return paramDiff(selectedExp, selectedParent);
	});

	function fmtParam(key: string, val: string | number): string {
		if (typeof val === 'number') {
			if (key.endsWith('_lr')) return val.toPrecision(3);
			if (key.endsWith('_ratio')) return val.toFixed(2);
			return String(val);
		}
		return String(val);
	}

	// Keep traversal
	let keepExps = $derived(
		experiments.filter(e => e.status === 'keep').sort((a, b) => a.id - b.id)
	);

	let keepIdx = $derived(
		selectedExp ? keepExps.findIndex(e => e.id === selectedExp!.id) : -1
	);

	function goKeep(dir: -1 | 1) {
		if (keepExps.length === 0) return;
		let idx = keepIdx;
		if (idx === -1) {
			idx = dir === 1 ? 0 : keepExps.length - 1;
		} else {
			idx += dir;
			if (idx < 0) idx = keepExps.length - 1;
			if (idx >= keepExps.length) idx = 0;
		}
		onSelectExp(keepExps[idx]);
	}
</script>

<div class="decisions-view">
	<div class="graph-area">
		<RunGraph {experiments} onSelect={onSelectExp} focusId={selectedExp?.id ?? null} />
	</div>

	<!-- Floating Insight Sidebar -->
	<div class="insight-float" class:collapsed={!showInsights}>
		<button class="insight-toggle" onclick={() => (showInsights = !showInsights)}>
			{showInsights ? '\u2715' : '\u2139'}
		</button>
		{#if showInsights}
			<div class="insight-body">
				<InsightSidebar {experiments} {plateaus} />
			</div>
		{/if}
	</div>

	<!-- Selected Experiment Detail Card -->
	{#if selectedExp}
		<div class="detail-card">
			<div class="dc-header">
				<div class="dc-title">
					<span class="dc-iter">#{selectedExp.id}</span>
					<span class="dc-id">{selectedExp.commit}</span>
					<span class="dc-badge {selectedExp.status}">{selectedExp.status}</span>
				</div>
				<button class="dc-close" onclick={() => onSelectExp(null)}>&times;</button>
			</div>

			<div class="dc-bpb">
				<span class="dc-bpb-val">{selectedExp.val_bpb.toFixed(6)}</span>
				<span class="dc-bpb-label">bpb</span>
				{#if selectedExp.delta !== 0}
					<span class="dc-delta" class:good={selectedExp.delta < 0} class:bad={selectedExp.delta > 0}>
						{selectedExp.delta >= 0 ? '+' : ''}{selectedExp.delta.toFixed(6)} ({((selectedExp.delta / (selectedExp.val_bpb - selectedExp.delta)) * 100).toFixed(1)}%)
					</span>
				{/if}
			</div>

			<div class="dc-section">
				<div class="dc-desc">{selectedExp.description}</div>
			</div>

			{#if selectedParams.length > 0}
				<div class="dc-pills">
					{#each selectedParams as ch}
						<span class="dc-pill">
							<span class="pill-k">{ch.key}</span>
							<span class="pill-from">{fmtParam(ch.key, ch.from)}</span>
							<span class="pill-arr">&rarr;</span>
							<span class="pill-to">{fmtParam(ch.key, ch.to)}</span>
						</span>
					{/each}
				</div>
			{/if}

			<!-- Metrics -->
			<div class="dc-metrics">
				{#if selectedExp.num_steps > 0}<span>{selectedExp.num_steps} steps</span>{/if}
				<span>{selectedExp.peak_vram_gb.toFixed(1)}GB</span>
				{#if selectedExp.tokens_per_second != null}<span>{selectedExp.tokens_per_second.toLocaleString()} tok/s</span>{/if}
				{#if selectedExp.mfu_percent > 0}<span>{selectedExp.mfu_percent.toFixed(1)}% MFU</span>{/if}
			</div>

			<!-- Diff -->
			{#if selectedExp.diff_text}
				<details class="dc-diff-details">
					<summary>View diff</summary>
					<div class="dc-diff"><DiffViewer diff={selectedExp.diff_text} /></div>
				</details>
			{/if}

			<!-- Keep traversal -->
			<div class="dc-nav">
				{#if keepIdx > 0}
					<button class="dc-nav-btn" onclick={() => goKeep(-1)}>
						<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 3L4.5 7l4 4"/></svg>
						Prev
					</button>
				{:else}
					<span></span>
				{/if}
				<span class="dc-nav-pos">{keepIdx >= 0 ? keepIdx + 1 : '-'} / {keepExps.length}</span>
				{#if keepIdx >= 0 && keepIdx < keepExps.length - 1}
					<button class="dc-nav-btn" onclick={() => goKeep(1)}>
						Next
						<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 3l4 4-4 4"/></svg>
					</button>
				{:else}
					<span></span>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.decisions-view { position: relative; height: calc(100vh - 56px - 3rem); min-height: 500px; }
	.graph-area { width: 100%; height: 100%; }

	/* Insight panel */
	.insight-float { position: absolute; top: 12px; right: 12px; z-index: 20; }
	.insight-float.collapsed { background: transparent; }
	.insight-float:not(.collapsed) { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-lg); width: 260px; }
	.insight-toggle {
		position: absolute; top: 0; right: 0; width: 32px; height: 32px;
		background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-sm);
		display: flex; align-items: center; justify-content: center;
		cursor: pointer; color: var(--text-dim); font-size: 0.85rem; z-index: 1;
		box-shadow: var(--shadow-sm); transition: all 0.15s ease;
	}
	.insight-float:not(.collapsed) .insight-toggle { top: 8px; right: 8px; border: none; box-shadow: none; background: none; }
	.insight-toggle:hover { color: var(--text); }
	.insight-body { padding: 1rem 1.1rem; max-height: calc(100vh - 56px - 6rem); overflow-y: auto; }

	/* Detail card */
	.detail-card {
		position: absolute; bottom: 12px; left: 12px; z-index: 20;
		background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);
		box-shadow: var(--shadow-lg); padding: 1rem 1.25rem; width: 400px;
		min-height: 220px;
		display: flex; flex-direction: column;
	}
	.dc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
	.dc-title { display: flex; align-items: center; gap: 0.4rem; }
	.dc-iter { font-family: var(--font-mono); font-weight: 700; font-size: 1.1rem; color: var(--text); }
	.dc-id { font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-dim); }
	.dc-badge {
		font-size: 0.6rem; font-weight: 600; text-transform: uppercase;
		letter-spacing: 0.04em; padding: 0.12rem 0.4rem; border-radius: 4px;
	}
	.dc-badge.keep { background: var(--green-bg); color: var(--green); }
	.dc-badge.discard { background: var(--red-bg); color: var(--red); }
	.dc-badge.crash { background: var(--amber-bg); color: var(--amber); }
	.dc-close {
		background: none; border: 1px solid var(--border); color: var(--text-dim);
		font-size: 1.1rem; cursor: pointer; width: 26px; height: 26px;
		display: flex; align-items: center; justify-content: center;
		border-radius: var(--radius-sm); line-height: 1; transition: all 0.15s ease;
	}
	.dc-close:hover { color: var(--text); background: var(--bg-hover); }

	.dc-bpb { display: flex; align-items: baseline; gap: 0.35rem; margin-bottom: 0.5rem; }
	.dc-bpb-val { font-family: var(--font-mono); font-size: 1.3rem; font-weight: 700; color: var(--text); }
	.dc-bpb-label { font-size: 0.72rem; color: var(--text-dim); text-transform: uppercase; }
	.dc-delta { font-family: var(--font-mono); font-size: 0.78rem; font-weight: 600; margin-left: 0.25rem; }
	.dc-delta.good { color: var(--green); }
	.dc-delta.bad { color: var(--red); opacity: 0.7; }

	.dc-section { margin-bottom: 0.5rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }
	.dc-desc { font-size: 0.82rem; font-weight: 500; color: var(--text); line-height: 1.4; }

	.dc-pills { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.5rem; }
	.dc-pill {
		display: inline-flex; align-items: center; gap: 0.2rem;
		padding: 0.15rem 0.5rem; background: var(--bg-subtle); border: 1px solid var(--border);
		border-radius: 999px; font-size: 0.68rem; font-family: var(--font-mono);
	}
	.pill-k { color: var(--text-dim); font-weight: 500; }
	.pill-from { color: var(--red); opacity: 0.7; }
	.pill-arr { color: var(--text-dim); font-size: 0.6rem; }
	.pill-to { color: var(--accent); font-weight: 600; }

	.dc-convergence {
		margin-bottom: 0.5rem; padding: 0.5rem; background: var(--bg-subtle);
		border-radius: var(--radius-sm); border: 1px solid var(--border);
	}
	.dc-conv-label { font-size: 0.65rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
	.dc-conv-points { display: flex; gap: 0.6rem; margin-top: 0.3rem; }
	.dc-conv-point { display: flex; flex-direction: column; gap: 0.1rem; }
	.dc-conv-pct { font-size: 0.6rem; color: var(--text-dim); }
	.dc-conv-val { font-family: var(--font-mono); font-size: 0.78rem; font-weight: 600; color: var(--text); }
	.dc-still-improving { font-size: 0.68rem; color: var(--amber); font-style: italic; margin-top: 0.25rem; display: block; }

	.dc-metrics {
		display: flex; flex-wrap: wrap; gap: 0.5rem;
		font-size: 0.72rem; color: var(--text-dim); font-family: var(--font-mono);
	}

	.dc-diff-details { border-top: 1px solid var(--border); padding-top: 0.4rem; margin-bottom: 0.5rem; }
	.dc-diff-details summary {
		font-size: 0.72rem; font-weight: 600; color: var(--text-secondary);
		cursor: pointer; padding: 0.25rem 0; text-transform: uppercase; letter-spacing: 0.04em;
	}
	.dc-diff-details summary:hover { color: var(--text); }
	.dc-diff { margin-top: 0.4rem; max-height: 300px; overflow-y: auto; }

	.dc-nav {
		display: flex; align-items: center; justify-content: space-between;
		margin-top: auto; padding-top: 0.6rem;
		border-top: 1px solid var(--border);
	}
	.dc-nav-btn {
		display: flex; align-items: center; gap: 0.3rem;
		background: none; border: 1px solid var(--border); border-radius: var(--radius-sm);
		padding: 0.3rem 0.6rem; font-size: 0.72rem; font-weight: 500;
		color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;
	}
	.dc-nav-btn:hover { color: var(--text); background: var(--bg-hover); border-color: var(--border-strong); }
	.dc-nav-pos { font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-dim); }
</style>
