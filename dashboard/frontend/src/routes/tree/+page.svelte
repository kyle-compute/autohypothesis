<script lang="ts">
	import { onMount } from 'svelte';
	import type { Experiment } from '$lib/types';
	import { fetchExperiments } from '$lib/api';
	import RunGraph from '$lib/components/RunGraph.svelte';

	let experiments: Experiment[] = $state([]);
	let selectedExp: Experiment | null = $state(null);
	let showPanel = $state(false);

	function isKarpathyRun(e: Experiment): boolean { return e.experiment_id.startsWith('karpathy-'); }
	let treeExperiments = $derived(experiments.filter(e => !isKarpathyRun(e)));

	onMount(async () => {
		experiments = await fetchExperiments();
	});

	function onSelectNode(exp: Experiment | null) {
		selectedExp = exp;
		showPanel = exp != null;
	}

	function closePanel() {
		showPanel = false;
		selectedExp = null;
	}

	let parentExp = $derived.by((): Experiment | null => {
		if (!selectedExp?.parent_commit) return null;
		return experiments.find(e => e.commit === selectedExp!.parent_commit) ?? null;
	});

	function formatNotes(notes: string | Record<string, unknown>): string {
		if (typeof notes === 'string') return notes;
		if (notes && typeof notes === 'object') {
			const summary = (notes as any).summary || (notes as any).notes;
			if (typeof summary === 'string') return summary;
			return JSON.stringify(notes, null, 2);
		}
		return '';
	}

	function deltaClass(d: number): string { return d < -0.001 ? 'good' : d > 0.001 ? 'bad' : 'neutral'; }
</script>

<div class="tree-page">
	<div class="tree-graph" class:panel-open={showPanel}>
		<RunGraph experiments={treeExperiments} onSelect={onSelectNode} focusId={selectedExp?.id ?? null} />
	</div>

	{#if showPanel && selectedExp}
		{@const exp = selectedExp}
		{@const notesText = formatNotes(exp.notes)}
		<div class="panel">
			<!-- Header -->
			<div class="p-header">
				<div class="p-title">
					<span class="p-badge {exp.status}">{exp.status}</span>
					<h2>#{exp.id} {exp.experiment_id.replace(/^exp-\d+-/, '')}</h2>
				</div>
				<button class="p-close" onclick={closePanel}>&times;</button>
			</div>

			<div class="p-scroll">
				<!-- BPB result -->
				<div class="p-result">
					<span class="p-bpb">{exp.val_bpb.toFixed(6)}</span>
					<span class="p-bpb-label">val_bpb</span>
					{#if exp.delta !== 0}
						<span class="p-delta {deltaClass(exp.delta)}">{exp.delta > 0 ? '+' : ''}{exp.delta.toFixed(6)}</span>
					{/if}
				</div>

				<!-- Parent info -->
				{#if parentExp}
					<div class="p-sec p-parent">
						<h3>Based on</h3>
						<div class="p-parent-card">
							<span class="p-parent-badge {parentExp.status}">{parentExp.status}</span>
							<span class="p-parent-name">#{parentExp.id} {parentExp.experiment_id.replace(/^exp-\d+-/, '')}</span>
							<span class="p-parent-bpb">{parentExp.val_bpb.toFixed(4)}</span>
						</div>
					</div>
				{/if}

				<!-- Hypothesis -->
				{#if exp.rationale}
					<div class="p-sec">
						<h3>Hypothesis</h3>
						{#if exp.hypothesis_id}<span class="p-htag">{exp.hypothesis_id}</span>{/if}
						<p class="p-text">{exp.rationale}</p>
					</div>
				{/if}

				<!-- Decision write-up (the "diff" of decisions) -->
				{#if exp.decision_markdown}
					<div class="p-sec">
						<h3>Decision</h3>
						<div class="p-markdown">
							{#each exp.decision_markdown.split('\n') as line}
								{#if line.startsWith('# ')}<h4>{line.slice(2)}</h4>
								{:else if line.startsWith('## ')}<h5>{line.slice(3)}</h5>
								{:else if line.startsWith('- ')}<p class="md-li">{@html line.slice(2).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')}</p>
								{:else if line.trim()}<p>{@html line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')}</p>
								{/if}
							{/each}
						</div>
					</div>
				{/if}

				<!-- Analysis / Notes -->
				{#if notesText}
					<div class="p-sec">
						<h3>Analysis</h3>
						<p class="p-text">{notesText}</p>
					</div>
				{/if}

				<!-- Metrics -->
				{#if exp.num_steps}
					<div class="p-sec">
						<h3>Metrics</h3>
						<div class="p-metrics">
							<span>{exp.num_steps.toLocaleString()} steps</span>
							{#if exp.training_seconds}<span>{Math.floor(exp.training_seconds / 60)}m {Math.round(exp.training_seconds % 60)}s train</span>{/if}
							{#if exp.peak_vram_gb}<span>{exp.peak_vram_gb.toFixed(1)}GB VRAM</span>{/if}
							{#if exp.num_params_M}<span>{exp.num_params_M.toFixed(1)}M params</span>{/if}
							{#if exp.mfu_percent}<span>{exp.mfu_percent.toFixed(1)}% MFU</span>{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.tree-page {
		display: flex;
		height: calc(100vh - 56px);
		overflow: hidden;
		width: 100vw;
		margin-left: calc(-50vw + 50%);
		margin-top: -1.5rem;
	}
	.tree-graph {
		flex: 1;
		min-width: 0;
		transition: flex 0.2s ease;
	}
	.tree-graph.panel-open {
		flex: 0 0 55%;
	}

	/* Slide-out panel */
	.panel {
		flex: 0 0 45%;
		border-left: 1px solid var(--border);
		background: var(--bg-card);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	.p-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
	}
	.p-title {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.p-title h2 {
		font-family: var(--font-mono);
		font-size: 0.9rem;
		font-weight: 600;
		color: var(--text);
	}
	.p-badge {
		font-size: 0.55rem; font-weight: 600; text-transform: uppercase;
		letter-spacing: 0.04em; padding: 0.15rem 0.4rem; border-radius: 999px;
	}
	.p-badge.keep { background: var(--green-bg); color: var(--green); }
	.p-badge.discard { background: var(--red-bg); color: var(--red); }
	.p-badge.crash { background: var(--amber-bg); color: var(--amber); }
	.p-close {
		background: none; border: 1px solid var(--border); color: var(--text-dim);
		font-size: 1.1rem; cursor: pointer; width: 28px; height: 28px;
		display: flex; align-items: center; justify-content: center;
		border-radius: var(--radius-sm); transition: all 0.15s ease;
	}
	.p-close:hover { color: var(--text); background: var(--bg-hover); }

	.p-scroll {
		flex: 1;
		overflow-y: auto;
		padding: 0;
	}

	/* Result */
	.p-result {
		display: flex; align-items: baseline; gap: 0.4rem;
		padding: 0.75rem 1rem;
		background: var(--bg-subtle);
		border-bottom: 1px solid var(--border);
	}
	.p-bpb { font-family: var(--font-mono); font-size: 1.3rem; font-weight: 700; color: var(--text); }
	.p-bpb-label { font-size: 0.65rem; color: var(--text-dim); text-transform: uppercase; }
	.p-delta { font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600; }
	.p-delta.good { color: var(--green); }
	.p-delta.bad { color: var(--red); }
	.p-delta.neutral { color: var(--text-dim); }

	/* Parent */
	.p-parent-card {
		display: flex; align-items: center; gap: 0.4rem;
		padding: 0.4rem 0.6rem; background: var(--bg-hover);
		border-radius: var(--radius-sm); border: 1px solid var(--border);
		margin-top: 0.3rem;
	}
	.p-parent-badge {
		font-size: 0.5rem; font-weight: 600; text-transform: uppercase;
		padding: 0.1rem 0.3rem; border-radius: 999px;
	}
	.p-parent-badge.keep { background: var(--green-bg); color: var(--green); }
	.p-parent-badge.discard { background: var(--red-bg); color: var(--red); }
	.p-parent-name { font-family: var(--font-mono); font-size: 0.75rem; font-weight: 600; color: var(--text); }
	.p-parent-bpb { font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-dim); margin-left: auto; }

	/* Sections */
	.p-sec {
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border);
	}
	.p-sec:last-child { border-bottom: none; }
	.p-sec h3 {
		font-size: 0.6rem; color: var(--text-dim); text-transform: uppercase;
		letter-spacing: 0.08em; font-weight: 600; margin-bottom: 0.35rem;
	}
	.p-htag {
		display: inline-block; font-family: var(--font-mono); font-size: 0.62rem;
		background: var(--accent-light); color: var(--accent);
		padding: 0.1rem 0.4rem; border-radius: 999px; margin-bottom: 0.3rem;
	}
	.p-text {
		font-size: 0.8rem; color: var(--text-secondary); line-height: 1.55;
	}

	/* Markdown */
	.p-markdown { font-size: 0.78rem; color: var(--text-secondary); line-height: 1.55; }
	.p-markdown h4 { font-size: 0.85rem; font-weight: 700; color: var(--text); margin: 0.5rem 0 0.25rem; }
	.p-markdown h5 { font-size: 0.75rem; font-weight: 600; color: var(--text); margin: 0.4rem 0 0.2rem; text-transform: uppercase; letter-spacing: 0.04em; }
	.p-markdown p { margin: 0.15rem 0; }
	.p-markdown :global(strong) { color: var(--text); }
	.p-markdown .md-li { padding-left: 0.8rem; }
	.p-markdown .md-li::before { content: '•'; display: inline-block; margin-left: -0.6rem; margin-right: 0.3rem; color: var(--text-dim); }

	/* Metrics */
	.p-metrics {
		display: flex; flex-wrap: wrap; gap: 0.5rem;
		font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-secondary);
	}
</style>
