<script lang="ts">
	import { onMount } from 'svelte';
	import type { Experiment } from '$lib/types';
	import { fetchExperiments } from '$lib/api';

	let experiments: Experiment[] = $state([]);
	let latest: Experiment | null = $state(null);

	onMount(async () => {
		experiments = await fetchExperiments();
		latest = experiments.length > 0
			? experiments.reduce((a, b) => a.id > b.id ? a : b)
			: null;
	});

	let keptCount = $derived(experiments.filter(e => e.status === 'keep').length);
	let bestBpb = $derived.by(() => {
		const kept = experiments.filter(e => e.status === 'keep');
		return kept.length > 0 ? Math.min(...kept.map(e => e.val_bpb)) : null;
	});
</script>

<div class="live-view">
	<!-- Summary bar -->
	<section class="status-bar">
		<div class="status-left">
			{#if latest}
				<span class="iteration">Latest: #{latest.id}</span>
				<span class="commit">{latest.commit}</span>
				<span class="badge {latest.status}">{latest.status}</span>
			{:else}
				<span class="iteration">No experiments yet</span>
				<span class="hint">Waiting for experiments.jsonl...</span>
			{/if}
		</div>
		<div class="status-right">
			{#if bestBpb != null}
				<span class="best-label">best</span>
				<span class="best-val">{bestBpb.toFixed(4)}</span>
				<span class="best-unit">bpb</span>
			{/if}
			<span class="count">{experiments.length} runs, {keptCount} kept</span>
		</div>
	</section>

	{#if latest}
		<!-- Latest experiment detail -->
		<section class="card">
			<h3>Experiment #{latest.id}</h3>
			<div class="desc">{latest.description}</div>

			<div class="result-row">
				<div class="result-primary">
					<span class="bpb-val">{latest.val_bpb.toFixed(6)}</span>
					<span class="bpb-label">val_bpb</span>
				</div>
				{#if latest.delta !== 0}
					<span class="delta" class:good={latest.delta < 0} class:bad={latest.delta > 0}>
						{latest.delta >= 0 ? '+' : ''}{latest.delta.toFixed(6)}
					</span>
				{/if}
				{#if latest.train_bpb != null}
					<div class="result-secondary">
						<span class="train-bpb">{latest.train_bpb.toFixed(6)} train</span>
						<span class="overfit-gap">gap: {(latest.val_bpb - latest.train_bpb).toFixed(4)}</span>
					</div>
				{/if}
			</div>
		</section>

		<!-- Convergence -->
		{#if latest.bpb_at_checkpoints?.length > 0}
			<section class="card">
				<h3>Convergence</h3>
				<div class="checkpoints">
					{#each latest.bpb_at_checkpoints as bpb, i}
						{@const minCp = Math.min(...latest.bpb_at_checkpoints)}
						{@const maxCp = Math.max(...latest.bpb_at_checkpoints)}
						{@const range = maxCp - minCp || 0.1}
						<div class="checkpoint">
							<div class="cp-bar-wrap">
								<div class="cp-bar" style="height: {20 + (1 - (bpb - minCp) / range) * 60}px"></div>
							</div>
							<span class="cp-val">{bpb.toFixed(3)}</span>
							<span class="cp-pct">{(i + 1) * 25}%</span>
						</div>
					{/each}
				</div>
				{#if latest.still_improving}
					<div class="improving-note">Loss was still decreasing — could benefit from longer budget</div>
				{/if}
			</section>
		{/if}

		<!-- Metrics -->
		<section class="stat-tiles">
			{#if latest.tokens_per_second != null}
				<div class="tile">
					<span class="tile-label">tok/sec</span>
					<span class="tile-value">{latest.tokens_per_second.toLocaleString()}</span>
				</div>
			{/if}
			<div class="tile">
				<span class="tile-label">steps</span>
				<span class="tile-value">{latest.num_steps}</span>
			</div>
			<div class="tile">
				<span class="tile-label">train time</span>
				<span class="tile-value">{latest.training_seconds.toFixed(0)}s</span>
			</div>
			<div class="tile">
				<span class="tile-label">total time</span>
				<span class="tile-value">{latest.total_seconds.toFixed(0)}s</span>
			</div>
			<div class="tile">
				<span class="tile-label">VRAM</span>
				<span class="tile-value">{latest.peak_vram_gb.toFixed(1)}GB</span>
			</div>
			<div class="tile">
				<span class="tile-label">params</span>
				<span class="tile-value">{latest.num_params_M.toFixed(1)}M</span>
			</div>
			<div class="tile">
				<span class="tile-label">tokens</span>
				<span class="tile-value">{latest.total_tokens_M.toFixed(1)}M</span>
			</div>
			{#if latest.mfu_percent > 0}
				<div class="tile">
					<span class="tile-label">MFU</span>
					<span class="tile-value">{latest.mfu_percent.toFixed(1)}%</span>
				</div>
			{/if}
			<div class="tile">
				<span class="tile-label">depth</span>
				<span class="tile-value">{latest.depth}</span>
			</div>
		</section>
	{/if}
</div>

<style>
	.live-view { display: flex; flex-direction: column; gap: 1rem; }

	.status-bar {
		display: flex; align-items: center; justify-content: space-between; gap: 1rem;
		padding: 1rem 1.25rem; background: var(--bg-card); border: 1px solid var(--border);
		border-radius: var(--radius); box-shadow: var(--shadow-sm); flex-wrap: wrap;
	}
	.status-left { display: flex; align-items: center; gap: 0.75rem; }
	.status-right { display: flex; align-items: center; gap: 0.75rem; }
	.iteration { font-size: 1.3rem; font-weight: 700; letter-spacing: -0.02em; color: var(--text); }
	.commit { font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-dim); background: var(--bg-hover); padding: 0.15rem 0.5rem; border-radius: var(--radius-sm); }
	.hint { color: var(--text-dim); font-size: 0.85rem; }
	.badge {
		padding: 0.2rem 0.6rem; border-radius: var(--radius-sm);
		font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
	}
	.badge.keep { background: var(--green-bg); color: var(--green); }
	.badge.discard { background: var(--red-bg); color: var(--red); }
	.badge.crash { background: var(--amber-bg); color: var(--amber); }
	.best-label { font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; }
	.best-val { font-family: var(--font-mono); font-size: 1rem; font-weight: 700; color: var(--green); }
	.best-unit { font-size: 0.7rem; color: var(--text-dim); }
	.count { font-size: 0.78rem; color: var(--text-dim); }

	.card {
		background: var(--bg-card); border: 1px solid var(--border);
		border-radius: var(--radius); padding: 1.25rem; box-shadow: var(--shadow-sm);
	}
	.card h3 {
		font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase;
		letter-spacing: 0.08em; font-weight: 600; margin-bottom: 0.75rem;
	}

	.desc { font-size: 0.9rem; color: var(--text); line-height: 1.5; margin-bottom: 0.75rem; }

	.result-row { display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
	.result-primary { display: flex; align-items: baseline; gap: 0.35rem; }
	.bpb-val { font-family: var(--font-mono); font-size: 1.5rem; font-weight: 700; color: var(--text); }
	.bpb-label { font-size: 0.75rem; color: var(--text-dim); }
	.delta { font-family: var(--font-mono); font-size: 0.9rem; font-weight: 600; }
	.delta.good { color: var(--green); }
	.delta.bad { color: var(--red); }
	.result-secondary { display: flex; gap: 0.75rem; font-size: 0.78rem; color: var(--text-dim); font-family: var(--font-mono); }

	.checkpoints { display: flex; gap: 1.5rem; align-items: flex-end; padding: 0.5rem 0; }
	.checkpoint { display: flex; flex-direction: column; align-items: center; gap: 0.25rem; }
	.cp-bar-wrap { display: flex; align-items: flex-end; }
	.cp-bar { width: 28px; background: var(--accent); border-radius: 4px 4px 0 0; opacity: 0.7; }
	.cp-val { font-family: var(--font-mono); font-size: 0.78rem; font-weight: 600; color: var(--text); }
	.cp-pct { font-size: 0.65rem; color: var(--text-dim); }
	.improving-note { font-size: 0.75rem; color: var(--amber); font-style: italic; margin-top: 0.5rem; }

	.stat-tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 0.75rem; }
	.tile {
		background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);
		padding: 0.85rem 1rem; display: flex; flex-direction: column; gap: 0.3rem;
		box-shadow: var(--shadow-sm); transition: box-shadow 0.15s ease;
	}
	.tile:hover { box-shadow: var(--shadow-md); }
	.tile-label { font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500; }
	.tile-value { font-family: var(--font-mono); font-size: 1.15rem; font-weight: 600; color: var(--text); letter-spacing: -0.02em; }
</style>
