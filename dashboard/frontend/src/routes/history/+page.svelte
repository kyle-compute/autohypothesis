<script lang="ts">
	import { onMount } from 'svelte';
	import type { Experiment, ParamChange, Plateau, PlateauChild } from '$lib/types';
	import { HYPERPARAM_KEYS } from '$lib/types';
	import { fetchExperiments, fetchRunDetail, fetchLineage, fetchConfigDiff } from '$lib/api';
	import type { LineageEdge, ConfigDiff } from '$lib/api';
	import { connectSSE } from '$lib/stores.svelte';
	import RunGraph from '$lib/components/RunGraph.svelte';
	import InsightSidebar from '$lib/components/InsightSidebar.svelte';
	import DiffViewer from '$lib/components/DiffViewer.svelte';

	let experiments: Experiment[] = $state([]);
	let lineageEdges: LineageEdge[] = $state([]);
	let selectedExp: Experiment | null = $state(null);
	let showInsights = $state(true);

	onMount(async () => {
		const [exps, edges] = await Promise.all([fetchExperiments(), fetchLineage()]);
		experiments = exps;
		lineageEdges = edges;
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
		const kept = experiments.filter(e => e.status === 'keep').sort((a, b) => String(a.id).localeCompare(String(b.id)));
		return kept.map(parent => {
			const children: PlateauChild[] = experiments
				.filter(e => e.parent_commit === parent.commit && e.id !== parent.id)
				.sort((a, b) => String(a.id).localeCompare(String(b.id)))
				.map(exp => ({ exp, paramChanges: paramDiff(exp, parent) }));
			return { parent, children };
		});
	});

	let runDetail: Record<string, any> | null = $state(null);
	let configDiff: ConfigDiff | null = $state(null);
	const runDetailCache = new Map<string, Record<string, any>>();
	const configDiffCache = new Map<string, ConfigDiff>();

	function onSelectExp(exp: Experiment | null) {
		selectedExp = exp;
		if (!exp) {
			runDetail = null;
			configDiff = null;
			return;
		}
		const cachedDetail = runDetailCache.get(exp.id);
		if (cachedDetail) {
			runDetail = cachedDetail;
		} else {
			fetchRunDetail(exp.id).then(d => {
				if (d) runDetailCache.set(exp.id, d);
				if (selectedExp?.id === exp.id) runDetail = d;
			});
		}
		const cachedDiff = configDiffCache.get(exp.id);
		if (cachedDiff) {
			configDiff = cachedDiff;
		} else {
			configDiff = null;
			fetchConfigDiff(exp.id).then(d => {
				if (d) configDiffCache.set(exp.id, d);
				if (selectedExp?.id === exp.id) configDiff = d;
			});
		}
	}

	let runConfig = $derived.by(() => {
		if (!runDetail) return null;
		const config = runDetail.config?.hyperparameters ?? runDetail.result?.changes_from_baseline ?? null;
		return config;
	});

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
		experiments.filter(e => e.status === 'keep').sort((a, b) => String(a.id).localeCompare(String(b.id)))
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
		<RunGraph {experiments} {lineageEdges} onSelect={onSelectExp} focusId={selectedExp?.id ?? null} />
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
			<!-- Fixed header -->
			<div class="dc-header">
				<div class="dc-header-left">
					<span class="dc-badge {selectedExp.status}">{selectedExp.status}</span>
					<span class="dc-iter" title={selectedExp.id}>{selectedExp.id}</span>
					<span class="dc-commit">{selectedExp.commit.slice(0, 7)}</span>
				</div>
				<button class="dc-close" onclick={() => onSelectExp(null)}>&times;</button>
			</div>

			<!-- Scrollable body -->
			<div class="dc-scroll">
				<!-- Result -->
				<div class="dc-result">
					<span class="dc-bpb-val">{selectedExp.val_bpb.toFixed(6)}</span>
					{#if selectedExp.delta !== 0}
						<span class="dc-delta" class:good={selectedExp.delta < 0} class:bad={selectedExp.delta > 0}>
							{selectedExp.delta >= 0 ? '+' : ''}{selectedExp.delta.toFixed(6)}
						</span>
					{/if}
				</div>

				<!-- Description -->
				<div class="dc-desc">{selectedExp.description}</div>

				<!-- Hypothesis -->
				{#if runDetail?.plan?.hypothesis && (runDetail.plan.hypothesis.rationale || runDetail.plan.hypothesis.prediction)}
					{@const hyp = runDetail.plan.hypothesis}
					<details class="dc-expand">
						<summary>Hypothesis</summary>
						<div class="dc-expand-body">
							{#if hyp.rationale}<div class="dc-hyp-text">{hyp.rationale}</div>{/if}
							{#if hyp.prediction}<div class="dc-hyp-pred">{hyp.prediction}</div>{/if}
						</div>
					</details>
				{/if}

				<!-- Param changes -->
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
					<span>{selectedExp.peak_vram_gb.toFixed(1)}GB VRAM</span>
					{#if selectedExp.tokens_per_second != null}<span>{selectedExp.tokens_per_second.toLocaleString()} tok/s</span>{/if}
					{#if selectedExp.mfu_percent > 0}<span>{selectedExp.mfu_percent.toFixed(1)}% MFU</span>{/if}
				</div>

				<!-- Config Diff -->
				{#if configDiff?.has_diff && configDiff.changes?.filter(ch => ch.old != null && ch.new != null).length}
					<details class="dc-expand">
						<summary>Config diff vs {configDiff.parent_id}</summary>
						<div class="dc-expand-body">
							<div class="dc-cdiff">
								{#each configDiff.changes.filter(ch => ch.old != null && ch.new != null) as ch}
									<div class="dc-cdiff-row">
										<span class="dc-cdiff-key">{ch.key}</span>
										<span class="dc-cdiff-old">{ch.old}</span>
										<span class="dc-cdiff-arr">&rarr;</span>
										<span class="dc-cdiff-new">{ch.new}</span>
									</div>
								{/each}
							</div>
						</div>
					</details>
				{/if}

				<!-- Expandable: Config -->
				{#if runConfig}
					<details class="dc-expand">
						<summary>Config</summary>
						<div class="dc-expand-body">
							<div class="dc-config-grid">
								{#each Object.entries(runConfig).filter(([k]) => k !== 'base_experiment') as [key, val]}
									<div class="dc-cfg-row">
										<span class="dc-cfg-key">{key}</span>
										<span class="dc-cfg-val">{typeof val === 'object' ? JSON.stringify(val) : val}</span>
									</div>
								{/each}
							</div>
							{#if runConfig.base_experiment}
								<div class="dc-cfg-base">Base: {runConfig.base_experiment}</div>
							{/if}
						</div>
					</details>
				{/if}

				<!-- Expandable: Diff -->
				{#if selectedExp.diff_text}
					<details class="dc-expand">
						<summary>Diff</summary>
						<div class="dc-expand-body dc-diff"><DiffViewer diff={selectedExp.diff_text} /></div>
					</details>
				{/if}
			</div>

			<!-- Fixed footer nav -->
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
		box-shadow: var(--shadow-lg); width: 360px;
		max-height: calc(100vh - 56px - 4rem);
		display: flex; flex-direction: column;
	}

	/* Fixed header */
	.dc-header {
		display: flex; justify-content: space-between; align-items: center;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}
	.dc-header-left { display: flex; align-items: center; gap: 0.5rem; min-width: 0; }
	.dc-badge {
		font-size: 0.58rem; font-weight: 700; text-transform: uppercase;
		letter-spacing: 0.05em; padding: 0.15rem 0.45rem; border-radius: 4px; flex-shrink: 0;
	}
	.dc-badge.keep { background: var(--green-bg); color: var(--green); }
	.dc-badge.discard { background: var(--red-bg); color: var(--red); }
	.dc-badge.crash { background: var(--amber-bg); color: var(--amber); }
	.dc-badge.replicate { background: var(--blue-bg); color: var(--blue); }
	.dc-iter {
		font-family: var(--font-mono); font-weight: 700; font-size: 0.82rem; color: var(--text);
		overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
	}
	.dc-commit { font-family: var(--font-mono); font-size: 0.65rem; color: var(--text-dim); flex-shrink: 0; }
	.dc-close {
		background: none; border: none; color: var(--text-dim);
		font-size: 1.1rem; cursor: pointer; width: 24px; height: 24px;
		display: flex; align-items: center; justify-content: center;
		border-radius: var(--radius-sm); line-height: 1; transition: all 0.15s ease; flex-shrink: 0;
	}
	.dc-close:hover { color: var(--text); background: var(--bg-hover); }

	/* Scrollable body */
	.dc-scroll { flex: 1; overflow-y: auto; min-height: 0; padding: 0.75rem 1rem; display: flex; flex-direction: column; gap: 0.6rem; }

	/* Result row */
	.dc-result { display: flex; align-items: baseline; gap: 0.35rem; }
	.dc-bpb-val { font-family: var(--font-mono); font-size: 1.4rem; font-weight: 700; color: var(--text); }
	.dc-delta { font-family: var(--font-mono); font-size: 0.78rem; font-weight: 600; }
	.dc-delta.good { color: var(--green); }
	.dc-delta.bad { color: var(--red); opacity: 0.7; }

	/* Description */
	.dc-desc { font-size: 0.8rem; color: var(--text-secondary); line-height: 1.4; }

	/* Hypothesis */
	.dc-hyp-text { font-size: 0.72rem; color: var(--text-secondary); line-height: 1.45; }
	.dc-hyp-pred { font-size: 0.68rem; color: var(--text-dim); font-style: italic; margin-top: 0.3rem; }

	/* Param change pills */
	.dc-pills { display: flex; flex-wrap: wrap; gap: 0.25rem; }
	.dc-pill {
		display: inline-flex; align-items: center; gap: 0.2rem;
		padding: 0.12rem 0.45rem; background: var(--bg-subtle); border: 1px solid var(--border);
		border-radius: 999px; font-size: 0.65rem; font-family: var(--font-mono);
	}
	.pill-k { color: var(--text-dim); font-weight: 500; }
	.pill-from { color: var(--red); opacity: 0.7; }
	.pill-arr { color: var(--text-dim); font-size: 0.55rem; }
	.pill-to { color: var(--accent); font-weight: 600; }

	/* Metrics */
	.dc-metrics {
		display: flex; flex-wrap: wrap; gap: 0.4rem;
		font-size: 0.7rem; color: var(--text-dim); font-family: var(--font-mono);
	}
	.dc-metrics span {
		padding: 0.1rem 0.4rem; background: var(--bg-hover); border-radius: 4px;
	}

	/* Expandable sections */
	.dc-expand {}
	.dc-expand summary {
		font-size: 0.68rem; font-weight: 600; color: var(--text-dim);
		cursor: pointer; padding: 0.2rem 0; text-transform: uppercase; letter-spacing: 0.06em;
		list-style: none;
		display: flex; align-items: center; gap: 0.3rem;
	}
	.dc-expand summary::-webkit-details-marker { display: none; }
	.dc-expand summary::before {
		content: '\203A'; font-size: 0.85rem; line-height: 1; transition: transform 0.15s ease;
		display: inline-block; color: var(--text-dim);
	}
	.dc-expand[open] summary::before { transform: rotate(90deg); }
	.dc-expand summary:hover { color: var(--text); }
	.dc-expand summary:hover::before { color: var(--text); }
	.dc-expand-body { margin-top: 0.3rem; }
	.dc-diff { max-height: 260px; overflow-y: auto; }

	/* Config diff */
	.dc-cdiff { display: flex; flex-direction: column; gap: 0.15rem; }
	.dc-cdiff-row { display: grid; grid-template-columns: 1fr auto auto auto; gap: 0.3rem; align-items: center; padding: 0.12rem 0; }
	.dc-cdiff-key { font-size: 0.65rem; color: var(--text-dim); font-family: var(--font-mono); }
	.dc-cdiff-old { font-size: 0.65rem; color: var(--red); font-family: var(--font-mono); opacity: 0.7; text-align: right; max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.dc-cdiff-arr { font-size: 0.55rem; color: var(--text-dim); }
	.dc-cdiff-new { font-size: 0.65rem; color: var(--green); font-family: var(--font-mono); font-weight: 600; max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	/* Config grid */
	.dc-config-grid { display: flex; flex-direction: column; gap: 0.1rem; }
	.dc-cfg-row { display: flex; justify-content: space-between; gap: 0.5rem; padding: 0.08rem 0; }
	.dc-cfg-key { font-size: 0.65rem; color: var(--text-dim); font-family: var(--font-mono); white-space: nowrap; }
	.dc-cfg-val { font-size: 0.65rem; color: var(--text); font-family: var(--font-mono); font-weight: 600; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px; }
	.dc-cfg-base { font-size: 0.62rem; color: var(--text-dim); font-style: italic; margin-top: 0.3rem; }

	/* Fixed footer nav */
	.dc-nav {
		display: flex; align-items: center; justify-content: space-between;
		padding: 0.5rem 1rem;
		border-top: 1px solid var(--border);
		flex-shrink: 0;
	}
	.dc-nav-btn {
		display: flex; align-items: center; gap: 0.3rem;
		background: none; border: 1px solid var(--border); border-radius: var(--radius-sm);
		padding: 0.25rem 0.5rem; font-size: 0.7rem; font-weight: 500;
		color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease;
	}
	.dc-nav-btn:hover { color: var(--text); background: var(--bg-hover); border-color: var(--border-strong); }
	.dc-nav-pos { font-family: var(--font-mono); font-size: 0.7rem; color: var(--text-dim); }
</style>
