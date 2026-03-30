<script lang="ts">
	import type { Experiment, Plateau } from '$lib/types';
	import { HYPERPARAM_KEYS } from '$lib/types';

	let { experiments = [], plateaus = [] }: { experiments: Experiment[]; plateaus: Plateau[] } = $props();

	let kept = $derived(experiments.filter(e => e.status === 'keep'));
	let discarded = $derived(experiments.filter(e => e.status === 'discard'));
	let crashed = $derived(experiments.filter(e => e.status === 'crash'));

	let keepRate = $derived(
		experiments.length > 0 ? ((kept.length / experiments.length) * 100).toFixed(0) : '-'
	);

	// Rolling rate (last 10)
	let recent = $derived([...experiments].sort((a, b) => b.id - a.id).slice(0, 10));
	let recentRate = $derived(
		recent.length > 0
			? ((recent.filter(e => e.status === 'keep').length / recent.length) * 100).toFixed(0)
			: '-'
	);

	// Attempts per breakthrough
	let attemptsPerBreakthrough = $derived.by(() =>
		plateaus.map(p => ({
			id: p.parent.id,
			attempts: p.children.length,
			found: p.children.some(c => c.exp.status === 'keep'),
		}))
	);

	let avgAttempts = $derived.by(() => {
		const w = attemptsPerBreakthrough.filter(a => a.found);
		if (w.length === 0) return '-';
		return (w.reduce((s, a) => s + a.attempts, 0) / w.length).toFixed(1);
	});

	// Strategy hit rates
	interface Strategy { name: string; kept: number; total: number; }

	let strategies = $derived.by((): Strategy[] => {
		const cats = new Map<string, { kept: number; total: number }>();
		for (const p of plateaus) {
			for (const child of p.children) {
				if (child.paramChanges.length === 0) continue;
				for (const ch of child.paramChanges) {
					const cat = ch.key === 'depth' ? 'architecture' : 'other';
					if (!cats.has(cat)) cats.set(cat, { kept: 0, total: 0 });
					const entry = cats.get(cat)!;
					entry.total++;
					if (child.exp.status === 'keep') entry.kept++;
				}
			}
		}
		return [...cats.entries()]
			.map(([name, { kept, total }]) => ({ name, kept, total }))
			.sort((a, b) => b.total - a.total);
	});

	// Still-improving alerts
	let stillImproving = $derived(
		experiments.filter(e => e.status === 'discard' && e.still_improving)
	);

	// Best BPB
	let bestBpb = $derived.by(() => {
		const vals = kept.map(e => e.val_bpb);
		return vals.length > 0 ? Math.min(...vals).toFixed(4) : '-';
	});

	// Total improvement
	let totalImprovement = $derived.by(() => {
		const sorted = [...kept].sort((a, b) => a.id - b.id);
		if (sorted.length < 2) return null;
		const first = sorted[0].val_bpb;
		const last = sorted[sorted.length - 1].val_bpb;
		const d = last - first;
		const pct = ((d / first) * 100).toFixed(1);
		return { delta: d.toFixed(4), pct };
	});
</script>

<div class="sidebar">
	<div class="section">
		<h4>Overview</h4>
		<div class="stat-row">
			<span class="stat-label">Best BPB</span>
			<span class="stat-value accent">{bestBpb}</span>
		</div>
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

	<div class="section">
		<h4>Keep Rate</h4>
		<div class="rate-bar-wrap">
			<div class="rate-bar">
				<div class="rate-fill" style="width: {keepRate === '-' ? 0 : keepRate}%"></div>
			</div>
			<span class="rate-label">{keepRate}%</span>
		</div>
		<div class="rate-detail">
			<span>{kept.length} kept</span>
			<span class="dim">/</span>
			<span>{experiments.length} total</span>
			{#if crashed.length > 0}
				<span class="dim">({crashed.length} crashed)</span>
			{/if}
		</div>
		{#if recent.length >= 3}
			<div class="rate-recent">Last {recent.length}: <strong>{recentRate}%</strong></div>
		{/if}
	</div>

	<div class="section">
		<h4>Breakthrough Velocity</h4>
		<div class="stat-row">
			<span class="stat-label">Avg attempts</span>
			<span class="stat-value">{avgAttempts}</span>
		</div>
		<div class="plateau-bars">
			{#each attemptsPerBreakthrough as p}
				<div class="plateau-bar-row" title="Plateau #{p.id}: {p.attempts} attempts">
					<span class="pb-label">#{p.id}</span>
					<div class="pb-bar">
						{#each { length: Math.min(p.attempts, 12) } as _, i}
							<span class="pb-dot" class:success={p.found && i === p.attempts - 1} class:fail={!(p.found && i === p.attempts - 1)}></span>
						{/each}
						{#if p.attempts > 12}<span class="pb-more">+{p.attempts - 12}</span>{/if}
					</div>
				</div>
			{/each}
		</div>
	</div>

	{#if strategies.length > 0}
		<div class="section">
			<h4>Strategy Hit Rate</h4>
			{#each strategies as strat}
				{@const rate = strat.total > 0 ? Math.round((strat.kept / strat.total) * 100) : 0}
				<div class="strat-row">
					<span class="strat-name">{strat.name}</span>
					<span class="strat-ratio">{strat.kept}/{strat.total}</span>
					<div class="strat-bar"><div class="strat-fill" style="width: {rate}%"></div></div>
				</div>
			{/each}
		</div>
	{/if}

	{#if stillImproving.length > 0}
		<div class="section">
			<h4>Still Improving (discarded)</h4>
			{#each stillImproving.slice(0, 5) as exp}
				<div class="improving-item">
					<span class="improving-id">#{exp.id}</span>
					<span class="improving-desc">{exp.description}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.sidebar { display: flex; flex-direction: column; gap: 0; }
	.section { padding: 1rem 0; border-bottom: 1px solid var(--border); }
	.section:first-child { padding-top: 0; }
	.section:last-child { border-bottom: none; }
	h4 { font-size: 0.65rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; margin-bottom: 0.6rem; }
	.stat-row { display: flex; justify-content: space-between; align-items: center; padding: 0.2rem 0; }
	.stat-label { font-size: 0.78rem; color: var(--text-secondary); }
	.stat-value { font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600; color: var(--text); }
	.stat-value.accent { color: var(--accent); }
	.stat-value.good { color: var(--green); }
	.rate-bar-wrap { display: flex; align-items: center; gap: 0.6rem; }
	.rate-bar { flex: 1; height: 6px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
	.rate-fill { height: 100%; background: var(--green); border-radius: 3px; transition: width 0.3s ease; }
	.rate-label { font-family: var(--font-mono); font-size: 0.85rem; font-weight: 700; color: var(--text); min-width: 2.5rem; text-align: right; }
	.rate-detail { font-size: 0.72rem; color: var(--text-dim); margin-top: 0.3rem; display: flex; gap: 0.25rem; }
	.dim { opacity: 0.5; }
	.rate-recent { font-size: 0.72rem; color: var(--text-dim); margin-top: 0.2rem; }
	.rate-recent strong { color: var(--text-secondary); }
	.plateau-bars { display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.4rem; }
	.plateau-bar-row { display: flex; align-items: center; gap: 0.4rem; }
	.pb-label { font-family: var(--font-mono); font-size: 0.68rem; color: var(--text-dim); width: 2rem; text-align: right; }
	.pb-bar { display: flex; gap: 0.2rem; align-items: center; }
	.pb-dot { width: 7px; height: 7px; border-radius: 50%; }
	.pb-dot.fail { background: rgba(220,38,38,0.3); }
	.pb-dot.success { background: var(--green); }
	.pb-more { font-size: 0.62rem; color: var(--text-dim); }
	.strat-row { display: grid; grid-template-columns: 1fr auto 50px; align-items: center; gap: 0.5rem; padding: 0.2rem 0; }
	.strat-name { font-size: 0.75rem; color: var(--text-secondary); text-transform: capitalize; }
	.strat-ratio { font-family: var(--font-mono); font-size: 0.7rem; color: var(--text-dim); }
	.strat-bar { height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
	.strat-fill { height: 100%; background: var(--accent); border-radius: 2px; }
	.improving-item { display: flex; gap: 0.4rem; align-items: baseline; padding: 0.2rem 0; }
	.improving-id { font-family: var(--font-mono); font-size: 0.72rem; font-weight: 600; color: var(--amber); }
	.improving-desc { font-size: 0.72rem; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
