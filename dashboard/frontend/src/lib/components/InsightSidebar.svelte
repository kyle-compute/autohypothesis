<script lang="ts">
	import { onMount } from 'svelte';
	import type { Experiment, Plateau, TopExperiment } from '$lib/types';
	import { fetchTop } from '$lib/api';

	let { experiments = [], plateaus = [] }: { experiments: Experiment[]; plateaus: Plateau[] } = $props();

	let topExperiments: TopExperiment[] = $state([]);

	onMount(async () => {
		topExperiments = await fetchTop();
	});

	let kept = $derived(experiments.filter(e => e.status === 'keep'));
	let crashed = $derived(experiments.filter(e => e.status === 'crash'));

	let keepRate = $derived(
		experiments.length > 0 ? ((kept.length / experiments.length) * 100).toFixed(0) : '-'
	);

	let recent = $derived(
		[...experiments].sort((a, b) => String(b.id).localeCompare(String(a.id))).slice(0, 10)
	);
	let recentRate = $derived(
		recent.length > 0
			? ((recent.filter(e => e.status === 'keep').length / recent.length) * 100).toFixed(0)
			: '-'
	);

	let bestBpb = $derived.by(() => {
		const vals = kept.map(e => e.val_bpb);
		return vals.length > 0 ? Math.min(...vals) : null;
	});

	let bestExp = $derived.by(() => {
		if (bestBpb == null) return null;
		return kept.find(e => e.val_bpb === bestBpb) ?? null;
	});

	let totalImprovement = $derived.by(() => {
		const sorted = [...kept].sort((a, b) => String(a.id).localeCompare(String(b.id)));
		if (sorted.length < 2) return null;
		const first = sorted[0].val_bpb;
		const best = Math.min(...sorted.map(e => e.val_bpb));
		const d = best - first;
		const pct = ((d / first) * 100).toFixed(1);
		return { delta: d.toFixed(4), pct };
	});

	let stillImproving = $derived(
		experiments.filter(e => e.status === 'discard' && e.still_improving)
	);

</script>

<div class="sidebar">
	<!-- Overview -->
	<div class="section">
		<h4>Overview</h4>
		<div class="stat-row">
			<span class="stat-label">Best BPB</span>
			<span class="stat-value accent">{bestBpb != null ? bestBpb.toFixed(4) : '-'}</span>
		</div>
		{#if bestExp}
			<div class="best-name">{bestExp.description || bestExp.id}</div>
		{/if}
		{#if totalImprovement}
			<div class="stat-row">
				<span class="stat-label">Improvement</span>
				<span class="stat-value good">{totalImprovement.delta} ({totalImprovement.pct}%)</span>
			</div>
		{/if}
		<div class="stat-row">
			<span class="stat-label">Experiments</span>
			<span class="stat-value">{experiments.length}</span>
		</div>
		<div class="stat-row">
			<span class="stat-label">Plateaus</span>
			<span class="stat-value">{plateaus.length}</span>
		</div>
	</div>

	<!-- Keep Rate -->
	<div class="section">
		<h4>Keep Rate</h4>
		<div class="rate-bar-wrap">
			<div class="rate-bar">
				<div class="rate-fill" style="width: {keepRate === '-' ? 0 : keepRate}%"></div>
			</div>
			<span class="rate-label">{keepRate}%</span>
		</div>
		<div class="rate-detail">
			<span>{kept.length} kept / {experiments.length} total</span>
			{#if crashed.length > 0}
				<span class="dim">({crashed.length} crashed)</span>
			{/if}
		</div>
		{#if recent.length >= 3}
			<div class="rate-recent">Last {recent.length}: <strong>{recentRate}%</strong></div>
		{/if}
	</div>

	<!-- Top Experiments Leaderboard -->
	{#if topExperiments.length > 0}
		<div class="section">
			<h4>Leaderboard</h4>
			<div class="leaderboard">
				{#each topExperiments as exp, i}
					<div class="lb-row" class:lb-best={i === 0}>
						<span class="lb-rank">{i + 1}</span>
						<div class="lb-info">
							<span class="lb-name">{exp.description || exp.id}</span>
							{#if exp.hypothesis_title}
								<span class="lb-hyp">{exp.hypothesis_title}</span>
							{/if}
						</div>
						<span class="lb-bpb">{exp.val_bpb.toFixed(4)}</span>
					</div>
				{/each}
			</div>
		</div>
	{/if}


	<!-- Still Improving -->
	{#if stillImproving.length > 0}
		<div class="section">
			<h4>Still Improving (discarded)</h4>
			{#each stillImproving.slice(0, 5) as exp}
				<div class="improving-item">
					<span class="improving-id">{exp.id}</span>
					<span class="improving-bpb">{exp.val_bpb.toFixed(4)}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.sidebar { display: flex; flex-direction: column; gap: 0; }
	.section { padding: 0.8rem 0; border-bottom: 1px solid var(--border); }
	.section:first-child { padding-top: 0; }
	.section:last-child { border-bottom: none; }
	h4 { font-size: 0.65rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; margin-bottom: 0.5rem; }

	.stat-row { display: flex; justify-content: space-between; align-items: center; padding: 0.15rem 0; }
	.stat-label { font-size: 0.78rem; color: var(--text-secondary); }
	.stat-value { font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600; color: var(--text); }
	.stat-value.accent { color: var(--accent); }
	.stat-value.good { color: var(--green); }

	.best-name { font-size: 0.7rem; color: var(--text-dim); font-family: var(--font-mono); margin-top: -0.1rem; margin-bottom: 0.2rem; }

	.rate-bar-wrap { display: flex; align-items: center; gap: 0.6rem; }
	.rate-bar { flex: 1; height: 6px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
	.rate-fill { height: 100%; background: var(--green); border-radius: 3px; transition: width 0.3s ease; }
	.rate-label { font-family: var(--font-mono); font-size: 0.85rem; font-weight: 700; color: var(--text); min-width: 2.5rem; text-align: right; }
	.rate-detail { font-size: 0.72rem; color: var(--text-dim); margin-top: 0.3rem; }
	.dim { opacity: 0.5; }
	.rate-recent { font-size: 0.72rem; color: var(--text-dim); margin-top: 0.2rem; }
	.rate-recent strong { color: var(--text-secondary); }

	/* Leaderboard */
	.leaderboard { display: flex; flex-direction: column; gap: 0.15rem; }
	.lb-row {
		display: grid; grid-template-columns: 1.2rem 1fr auto; gap: 0.4rem; align-items: center;
		padding: 0.3rem 0.4rem; border-radius: 6px; transition: background 0.1s;
	}
	.lb-row:hover { background: var(--bg-hover); }
	.lb-best { background: rgba(34, 197, 94, 0.06); }
	.lb-rank { font-family: var(--font-mono); font-size: 0.68rem; font-weight: 700; color: var(--text-dim); text-align: center; }
	.lb-best .lb-rank { color: var(--green); }
	.lb-info { display: flex; flex-direction: column; min-width: 0; }
	.lb-name { font-size: 0.72rem; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.lb-hyp { font-size: 0.62rem; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.lb-bpb { font-family: var(--font-mono); font-size: 0.72rem; font-weight: 600; color: var(--text); white-space: nowrap; }
	.lb-best .lb-bpb { color: var(--green); }

	/* Strategy */
	.strat-row { display: grid; grid-template-columns: 1fr auto 40px auto; align-items: center; gap: 0.4rem; padding: 0.15rem 0; }
	.strat-name { font-size: 0.68rem; color: var(--text-secondary); font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.strat-ratio { font-family: var(--font-mono); font-size: 0.65rem; color: var(--text-dim); }
	.strat-bar { height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
	.strat-fill { height: 100%; background: var(--accent); border-radius: 2px; }
	.strat-pct { font-family: var(--font-mono); font-size: 0.65rem; color: var(--text-dim); text-align: right; min-width: 2rem; }

	/* Config */
	.config-grid { display: flex; flex-direction: column; gap: 0.1rem; }
	.cfg-row { display: flex; justify-content: space-between; gap: 0.5rem; padding: 0.1rem 0; }
	.cfg-key { font-size: 0.68rem; color: var(--text-dim); font-family: var(--font-mono); }
	.cfg-val { font-size: 0.68rem; color: var(--text); font-family: var(--font-mono); font-weight: 600; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100px; }
	.cfg-notes { font-size: 0.65rem; color: var(--text-dim); font-style: italic; margin-top: 0.4rem; }

	/* Still Improving */
	.improving-item { display: flex; justify-content: space-between; align-items: center; padding: 0.15rem 0; }
	.improving-id { font-family: var(--font-mono); font-size: 0.68rem; font-weight: 600; color: var(--amber); }
	.improving-bpb { font-family: var(--font-mono); font-size: 0.68rem; color: var(--text-dim); }
</style>
