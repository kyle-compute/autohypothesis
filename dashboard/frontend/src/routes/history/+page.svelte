<script lang="ts">
	import { onMount } from 'svelte';
	import type { Experiment, KarpathyOriginal } from '$lib/types';
	import { fetchExperiments, fetchDiff, fetchKarpathyOriginal } from '$lib/api';
	import { connectSSE } from '$lib/stores.svelte';
	import DiffViewer from '$lib/components/DiffViewer.svelte';
	import HyperparamDiff from '$lib/components/HyperparamDiff.svelte';
	// import RunGraph from '$lib/components/RunGraph.svelte';

	let experiments: Experiment[] = $state([]);
	let karpathyRuns: KarpathyOriginal[] = $state([]);
	let selectedExp: Experiment | null = $state(null);
	let filterStatus: 'all' | 'keep' | 'discard' | 'crash' = $state('all');
	let diffText: string = $state('');
	let chartHoveredIdx: number | null = $state(null);
	let chartEl: SVGSVGElement | undefined = $state();

	onMount(async () => {
		[experiments, karpathyRuns] = await Promise.all([fetchExperiments(), fetchKarpathyOriginal()]);
		const ownKept = experiments.filter(e => e.status === 'keep' && !isBenchmark(e) && !isKarpathyRun(e));
		if (ownKept.length > 0) selectedExp = ownKept.reduce((a, b) => a.val_bpb < b.val_bpb ? a : b);
		const disconnect = connectSSE((exp) => { experiments = [...experiments, exp]; });
		return disconnect;
	});

	$effect(() => {
		if (selectedExp) fetchDiff(selectedExp.experiment_id).then(d => { diffText = d; });
		else diffText = '';
	});

	// ── Data helpers ──
	function isBenchmark(e: Experiment): boolean { return e.experiment_id === 'exp-001-upstream-benchmark'; }
	function isBaseline(e: Experiment): boolean { return e.experiment_id === 'exp-000-baseline'; }
	function isKarpathyRun(e: Experiment): boolean { return e.experiment_id.startsWith('karpathy-'); }
	function isOwnExperiment(e: Experiment): boolean { return !isBenchmark(e) && !isKarpathyRun(e); }

	let ownExperiments = $derived(experiments.filter(e => isOwnExperiment(e)));
	let karpathyExps = $derived(experiments.filter(e => isKarpathyRun(e)));
	let baselineExp = $derived(experiments.find(e => isBaseline(e)));
	let baselineBpb = $derived(baselineExp?.val_bpb ?? null);

	let filtered = $derived(
		filterStatus === 'all'
			? experiments.filter(e => !isKarpathyRun(e))  // Don't show karpathy runs in list
			: experiments.filter(e => e.status === filterStatus && !isKarpathyRun(e))
	);
	let sorted = $derived([...filtered].sort((a, b) => a.id - b.id));

	let ownBestBpb = $derived.by(() => {
		const kept = ownExperiments.filter(e => e.status === 'keep');
		return kept.length > 0 ? Math.min(...kept.map(e => e.val_bpb)) : null;
	});
	// Karpathy's best = his published best-known config (exp-001 upstream benchmark on our hw)
	let karpathyBenchmarkExp = $derived(experiments.find(e => isBenchmark(e)));
	let karpathyBestBpb = $derived(karpathyBenchmarkExp?.val_bpb ?? null);
	let keptCount = $derived(ownExperiments.filter(e => e.status === 'keep').length);
	let discardCount = $derived(ownExperiments.filter(e => e.status === 'discard').length);
	let crashCount = $derived(ownExperiments.filter(e => e.status === 'crash').length);
	let beatsKarpathy = $derived(ownBestBpb != null && karpathyBestBpb != null && ownBestBpb < karpathyBestBpb);

	// First experiment to beat Karpathy's best
	let firstBeatExp = $derived.by((): Experiment | null => {
		if (karpathyBestBpb == null) return null;
		const sorted = [...ownExperiments].sort((a, b) => a.id - b.id);
		for (const e of sorted) {
			if (e.status === 'keep' && e.val_bpb < karpathyBestBpb) return e;
		}
		return null;
	});

	// ── Chart: dual trajectory ──
	const CHART_PAD = { top: 24, right: 20, bottom: 44, left: 68 };
	let chartW = $state(800);
	const chartH = 280;
	let innerW = $derived(chartW - CHART_PAD.left - CHART_PAD.right);
	const innerH = chartH - CHART_PAD.top - CHART_PAD.bottom;

	let chartOwnExps = $derived([...ownExperiments].sort((a, b) => a.id - b.id));

	// Karpathy trajectories:
	// - karpathyOriginal: his 125 runs on his machine (from TSV)
	// - karpathyRepro: his config steps reproduced on OUR machine (karpathy-k* in jsonl)
	let karpathyReproSorted = $derived(
		[...karpathyExps].sort((a, b) => a.id - b.id)
	);
	let karpathyTrajectory = $derived.by(() => {
		if (karpathyRuns.length === 0) return [] as { x: number; bpb: number }[];
		return karpathyRuns.map((r, i) => ({ x: i, bpb: r.best_so_far }));
	});
	// Repro best-so-far (on our hw)
	let karpathyReproBestPath = $derived.by(() => {
		if (karpathyReproSorted.length === 0) return '';
		let best = Infinity;
		const pts: string[] = [];
		karpathyReproSorted.forEach((e, i) => {
			if (e.status === 'keep' && e.val_bpb < best) best = e.val_bpb;
			if (best < Infinity) pts.push(`${xScaleK(i)},${yScale(best)}`);
		});
		return pts.length > 1 ? `M${pts.join(' L')}` : '';
	});

	// Combined Y domain — use our experiments + karpathy repro (same hardware)
	let yDomain = $derived.by(() => {
		const allBpbs: number[] = [];
		for (const e of chartOwnExps) if (e.val_bpb > 0) allBpbs.push(e.val_bpb);
		for (const e of karpathyReproSorted) if (e.val_bpb > 0) allBpbs.push(e.val_bpb);
		if (allBpbs.length === 0) return { min: 0.96, max: 1.03 };
		const sorted = [...allBpbs].sort((a, b) => a - b);
		const p2 = sorted[Math.floor(sorted.length * 0.01)];
		const p98 = sorted[Math.floor(sorted.length * 0.99)];
		const pad = (p98 - p2) * 0.1 || 0.005;
		return { min: p2 - pad, max: p98 + pad };
	});

	function yScale(val: number): number {
		const clamped = Math.max(yDomain.min, Math.min(yDomain.max, val));
		return CHART_PAD.top + ((clamped - yDomain.min) / (yDomain.max - yDomain.min)) * innerH;
	}
	function inYRange(val: number): boolean {
		return val >= yDomain.min && val <= yDomain.max;
	}
	// Shared X-axis: both use same "experiment #" scale
	// Karpathy repro has ~23 steps, we have ~71 — we span the full width
	let maxXRuns = $derived(Math.max(chartOwnExps.length, karpathyReproSorted.length, 1) + 1);
	function xScale(idx: number): number {
		return (idx / (maxXRuns - 1)) * innerW;
	}
	// Keep aliases for clarity
	function xScaleOwn(idx: number): number { return xScale(idx); }
	function xScaleK(idx: number): number { return xScale(idx); }

	let yTicks = $derived.by(() => {
		const range = yDomain.max - yDomain.min;
		const step = range > 0.04 ? 0.01 : range > 0.015 ? 0.005 : 0.002;
		const ticks: number[] = [];
		let v = Math.ceil(yDomain.min / step) * step;
		while (v <= yDomain.max) { ticks.push(v); v += step; }
		return ticks;
	});

	// Our best-so-far path
	let ourBestPath = $derived.by(() => {
		if (chartOwnExps.length === 0) return '';
		let best = Infinity;
		const pts: string[] = [];
		chartOwnExps.forEach((e, i) => {
			if (e.status === 'keep' && e.val_bpb < best) best = e.val_bpb;
			if (best < Infinity) pts.push(`${xScaleOwn(i)},${yScale(best)}`);
		});
		return pts.length > 1 ? `M${pts.join(' L')}` : '';
	});

	// Karpathy best-so-far path (reproduced on OUR hardware)
	let karpathyBestPath = $derived.by(() => {
		return karpathyReproBestPath;
	});

	// First beat index in our experiments
	let firstBeatOwnIdx = $derived.by((): number | null => {
		if (!firstBeatExp) return null;
		return chartOwnExps.findIndex(e => e.id === firstBeatExp!.id);
	});

	function onChartMouseMove(e: MouseEvent) {
		if (!chartEl) return;
		const rect = chartEl.getBoundingClientRect();
		const mx = e.clientX - rect.left - CHART_PAD.left;
		const my = e.clientY - rect.top;
		if (mx < 0 || mx > innerW || chartOwnExps.length === 0) { chartHoveredIdx = null; return; }
		// Find nearest experiment by pixel distance to the actual dot position
		let bestIdx = -1;
		let bestDist = Infinity;
		for (let i = 0; i < chartOwnExps.length; i++) {
			const px = xScaleOwn(i);
			const py = yScale(chartOwnExps[i].val_bpb);
			const dist = Math.sqrt((mx - px) ** 2 + (my - py) ** 2);
			if (dist < bestDist) { bestDist = dist; bestIdx = i; }
		}
		chartHoveredIdx = bestDist < 30 ? bestIdx : null;
	}
	function onChartMouseLeave() { chartHoveredIdx = null; }
	function onChartClick() {
		if (chartHoveredIdx != null && chartOwnExps[chartHoveredIdx]) selectExp(chartOwnExps[chartHoveredIdx]);
	}

	function selectExp(exp: Experiment) { selectedExp = exp; }
	// ── Detail panel helpers ──
	// Find parent experiment by commit
	let parentExp = $derived.by((): Experiment | null => {
		if (!selectedExp?.parent_commit) return null;
		const pc = selectedExp.parent_commit;
		return experiments.find(e => e.commit === pc || e.commit.startsWith(pc) || pc.startsWith(e.commit)) ?? null;
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

	function fmt(val: number | null | undefined, decimals: number = 1, unit: string = ''): string {
		if (val == null || val === 0) return '—';
		const s = decimals === 0 ? val.toLocaleString() : val.toFixed(decimals);
		return unit ? `${s}${unit}` : s;
	}

	function fmtTime(seconds: number): string {
		if (!seconds) return '—';
		const m = Math.floor(seconds / 60);
		const s = Math.round(seconds % 60);
		return m > 0 ? `${m}m ${s}s` : `${s}s`;
	}

	// Track best-so-far at each experiment to mark "new best" milestones
	let bestSoFarMap = $derived.by(() => {
		const map = new Map<number, number>();
		let best = Infinity;
		const sorted = [...ownExperiments].sort((a, b) => a.id - b.id);
		for (const e of sorted) {
			if (e.status === 'keep' && e.val_bpb < best) best = e.val_bpb;
			if (best < Infinity) map.set(e.id, best);
		}
		return map;
	});
	function bestSoFarAt(id: number): number | undefined {
		return bestSoFarMap.get(id);
	}

	let listScrollEl: HTMLDivElement | undefined = $state();
	$effect(() => {
		if (selectedExp && listScrollEl) {
			const row = listScrollEl.querySelector(`[data-id="${selectedExp.id}"]`);
			if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
		}
	});
</script>

<div class="page">
	<!-- ── Top: Summary + Viz ── -->
	<div class="top-section">
		<div class="summary-row">
			<div class="chips">
				<div class="chip">
					<span class="chip-val accent">{ownBestBpb?.toFixed(4) ?? '—'}</span>
					<span class="chip-lbl">Our Best</span>
				</div>
				{#if karpathyBestBpb != null}
					<div class="chip">
						<span class="chip-val karp-c">{karpathyBestBpb.toFixed(4)}</span>
						<span class="chip-lbl">Karpathy best (125 runs)</span>
					</div>
				{/if}
				{#if ownBestBpb != null && karpathyBestBpb != null}
					<div class="chip">
						{#if beatsKarpathy}
							<span class="chip-val good">{(karpathyBestBpb - ownBestBpb).toFixed(4)}</span>
							<span class="chip-lbl beat">Beating Karpathy</span>
						{:else}
							<span class="chip-val bad">{(ownBestBpb - karpathyBestBpb).toFixed(4)}</span>
							<span class="chip-lbl">Behind Karpathy</span>
						{/if}
					</div>
				{/if}
				{#if firstBeatExp}
					<div class="chip">
						<span class="chip-val good">Run #{firstBeatExp.id}</span>
						<span class="chip-lbl">First beat (vs 125)</span>
					</div>
				{/if}
				{#if ownBestBpb != null && baselineBpb != null}
					<div class="chip">
						<span class="chip-val good">{((1 - ownBestBpb / baselineBpb) * 100).toFixed(1)}%</span>
						<span class="chip-lbl">Improvement</span>
					</div>
				{/if}
				<div class="chip-sep"></div>
				<div class="chip"><span class="chip-val">{ownExperiments.length}</span><span class="chip-lbl">Runs</span></div>
				<div class="chip"><span class="chip-val keep-c">{keptCount}</span><span class="chip-lbl">Kept</span></div>
				<div class="chip"><span class="chip-val discard-c">{discardCount}</span><span class="chip-lbl">Discarded</span></div>
				{#if crashCount > 0}<div class="chip"><span class="chip-val crash-c">{crashCount}</span><span class="chip-lbl">Crashed</span></div>{/if}
			</div>
			<div class="viz-tabs"></div>
		</div>

		<div class="viz-area">
				<div class="chart-container" bind:clientWidth={chartW}>
					<svg bind:this={chartEl} width={chartW} height={chartH} class="bpb-chart"
						onmousemove={onChartMouseMove} onmouseleave={onChartMouseLeave} onclick={onChartClick}
						role="img" aria-label="BPB trajectory chart">
						<defs>
							<linearGradient id="ourFill" x1="0" x2="0" y1="0" y2="1">
								<stop offset="0%" stop-color="var(--green)" stop-opacity="0.08" />
								<stop offset="100%" stop-color="var(--green)" stop-opacity="0.01" />
							</linearGradient>
							<linearGradient id="kFill" x1="0" x2="0" y1="0" y2="1">
								<stop offset="0%" stop-color="#3B82F6" stop-opacity="0.06" />
								<stop offset="100%" stop-color="#3B82F6" stop-opacity="0.01" />
							</linearGradient>
						</defs>

						<g transform="translate({CHART_PAD.left}, 0)">
							<!-- Grid -->
							{#each yTicks as tick}
								<line x1="0" x2={innerW} y1={yScale(tick)} y2={yScale(tick)} stroke="var(--border)" stroke-width="1" />
								<text x="-10" y={yScale(tick)} dy="3.5" text-anchor="end" class="ax-text">{tick.toFixed(3)}</text>
							{/each}

							<!-- Karpathy's published best benchmark line -->
							{#if karpathyBestBpb != null}
								<line x1="0" x2={innerW} y1={yScale(karpathyBestBpb)} y2={yScale(karpathyBestBpb)} stroke="#3B82F6" stroke-width="1.5" stroke-dasharray="8,4" opacity="0.45" />
								<rect x={innerW - 150} y={yScale(karpathyBestBpb) - 10} width="150" height="14" rx="3" fill="#3B82F6" opacity="0.1" />
								<text x={innerW - 4} y={yScale(karpathyBestBpb) - 1} text-anchor="end" class="ax-text" style="fill: #3B82F6; font-weight: 600; font-size: 9px">Karpathy best: {karpathyBestBpb.toFixed(4)}</text>
							{/if}

							<!-- ── Karpathy's search reproduced on OUR hardware (blue) ── -->
							<!-- Karpathy repro best-so-far fill + line -->
							{#if karpathyBestPath}
								{@const lastKX = xScaleK(karpathyReproSorted.length - 1)}
								<path d="{karpathyBestPath} L{lastKX},{yScale(yDomain.max)} L{xScaleK(0)},{yScale(yDomain.max)} Z" fill="url(#kFill)" />
								<path d={karpathyBestPath} fill="none" stroke="#3B82F6" stroke-width="2" opacity="0.6" />
							{/if}
							<!-- Karpathy repro individual data points -->
							{#each karpathyReproSorted as exp, i}
								{#if inYRange(exp.val_bpb)}
									{@const cx = xScaleK(i)}
									{@const cy = yScale(exp.val_bpb)}
									{#if exp.status === 'keep'}
										<circle {cx} {cy} r="3.5" fill="#3B82F6" opacity="0.55" />
									{:else}
										<circle {cx} {cy} r="2" fill="none" stroke="#93C5FD" stroke-width="1.2" opacity="0.35" />
									{/if}
								{/if}
							{/each}

							<!-- ── Our 72 runs (green, in front) ── -->
							<!-- Our best-so-far fill + line -->
							{#if ourBestPath}
								{@const lastOwnX = xScaleOwn(chartOwnExps.length - 1)}
								<path d="{ourBestPath} L{lastOwnX},{yScale(yDomain.max)} L{xScaleOwn(0)},{yScale(yDomain.max)} Z" fill="url(#ourFill)" />
								<path d={ourBestPath} fill="none" stroke="var(--green)" stroke-width="2.5" opacity="0.8" />
							{/if}
							<!-- Our individual data points -->
							{#each chartOwnExps as exp, i}
								{@const cx = xScaleOwn(i)}
								{@const cy = yScale(exp.val_bpb)}
								{@const isKeep = exp.status === 'keep'}
								{@const isCrash = exp.status === 'crash'}
								{@const active = chartHoveredIdx === i || selectedExp?.id === exp.id}
								{#if isKeep}
									<circle {cx} {cy} r={active ? 6 : 4} fill="var(--green)" opacity={active ? 1 : 0.85} class="dot" />
								{:else if isCrash}
									<polygon points="{cx},{cy - (active ? 6 : 4)} {cx + (active ? 5.5 : 3.5)},{cy + (active ? 3.5 : 2.5)} {cx - (active ? 5.5 : 3.5)},{cy + (active ? 3.5 : 2.5)}"
										fill="var(--amber)" opacity={active ? 1 : 0.6} class="dot" />
								{:else}
									<circle {cx} {cy} r={active ? 4 : 2.5} fill="var(--bg-card)" stroke="var(--border-strong)" stroke-width="1.5" opacity={active ? 1 : 0.5} class="dot" />
								{/if}
								{#if selectedExp?.id === exp.id}
									<circle {cx} {cy} r="10" fill="none" stroke="var(--accent)" stroke-width="2" opacity="0.5" />
								{/if}
							{/each}

							<!-- "Beat Karpathy" annotation -->
							{#if firstBeatOwnIdx != null && firstBeatExp}
								{@const fbx = xScaleOwn(firstBeatOwnIdx)}
								{@const fby = yScale(firstBeatExp.val_bpb)}
								<line x1={fbx} x2={fbx} y1={fby - 8} y2={CHART_PAD.top + 2} stroke="var(--green)" stroke-width="1" stroke-dasharray="3,2" opacity="0.5" />
								<g transform="translate({fbx},{CHART_PAD.top - 2})">
									<rect x="-58" y="-13" width="116" height="16" rx="8" fill="var(--green)" opacity="0.12" />
									<text x="0" y="0" text-anchor="middle" class="milestone-text">beat Karpathy @ #{firstBeatExp.id}</text>
								</g>
							{/if}

							<!-- Hover tooltip -->
							{#if chartHoveredIdx != null && chartOwnExps[chartHoveredIdx]}
								{@const hExp = chartOwnExps[chartHoveredIdx]}
								{@const hx = xScaleOwn(chartHoveredIdx)}
								{@const hy = yScale(hExp.val_bpb)}
								<line x1={hx} x2={hx} y1={CHART_PAD.top} y2={CHART_PAD.top + innerH} stroke="var(--text-dim)" stroke-width="1" opacity="0.2" stroke-dasharray="3,3" />
								{@const ty = hy < CHART_PAD.top + 60 ? hy + 15 : hy - 52}
								{@const tx = hx > innerW - 110 ? hx - 170 : hx + 10}
								<g transform="translate({tx},{ty})">
									<rect x="0" y="0" width="160" height="44" rx="6" fill="var(--text)" opacity="0.93" />
									<text x="8" y="16" class="tt-text" fill="white" font-weight="700">{hExp.val_bpb.toFixed(6)} bpb</text>
									<text x="8" y="32" class="tt-sub" fill="rgba(255,255,255,0.65)">#{hExp.id} {hExp.experiment_id.replace(/^exp-\d+-/, '')} · {hExp.status}</text>
								</g>
							{/if}

							<!-- "Karpathy's search ends here" marker (he only had 23 incremental steps) -->
							{#if karpathyReproSorted.length > 0 && karpathyReproSorted.length < maxXRuns - 1}
								{@const endX = xScaleK(karpathyReproSorted.length - 1)}
								<line x1={endX} x2={endX} y1={CHART_PAD.top} y2={CHART_PAD.top + innerH} stroke="#3B82F6" stroke-width="1" stroke-dasharray="4,3" opacity="0.25" />
								<text x={endX} y={CHART_PAD.top + innerH + 14} text-anchor="middle" class="ax-text" style="fill: #3B82F6; font-weight: 600">{karpathyReproSorted.length} Karpathy</text>
							{/if}

							<!-- X axis + ticks -->
							<line x1="0" x2={innerW} y1={CHART_PAD.top + innerH} y2={CHART_PAD.top + innerH} stroke="var(--border)" stroke-width="1" />
							{#each [0, 10, 20, 30, 40, 50, 60, 70].filter(t => t <= maxXRuns) as tick}
								{@const tx = xScale(tick)}
								<line x1={tx} x2={tx} y1={CHART_PAD.top + innerH} y2={CHART_PAD.top + innerH + 4} stroke="var(--border-strong)" stroke-width="1" />
								<text x={tx} y={CHART_PAD.top + innerH + 14} text-anchor="middle" class="ax-text">{tick}</text>
							{/each}
						</g>

						<!-- Legend -->
						<g transform="translate({CHART_PAD.left + 8}, {chartH - 22})">
							<line x1="0" x2="16" y1="-3" y2="-3" stroke="var(--green)" stroke-width="2.5" opacity="0.8" />
							<circle cx="8" cy="-3" r="3" fill="var(--green)" />
							<text x="22" y="0" class="leg-text">Our autonomous search ({ownExperiments.length} runs)</text>
							<line x1="230" x2="246" y1="-3" y2="-3" stroke="#3B82F6" stroke-width="2" opacity="0.6" />
							<circle cx="238" cy="-3" r="2.5" fill="#3B82F6" opacity="0.5" />
							<text x="252" y="0" class="leg-text">Karpathy's search ({karpathyReproSorted.length} kept steps, same hardware)</text>
						</g>

						<!-- Y label -->
						<!-- Axis labels -->
						<text x="14" y={CHART_PAD.top + innerH / 2} text-anchor="middle" class="ax-label" transform="rotate(-90, 14, {CHART_PAD.top + innerH / 2})">val_bpb (↑ lower = better)</text>
						<text x={CHART_PAD.left + innerW / 2} y={chartH - 2} text-anchor="middle" class="ax-label">experiment #</text>
					</svg>
				</div>
		</div>
	</div>

	<!-- ── Bottom: List + Detail ── -->
	<div class="browser">
		<div class="list-panel">
			<div class="list-header">
				<div class="filter-tabs">
					<button class="ftab" class:active={filterStatus === 'all'} onclick={() => filterStatus = 'all'}>All <span class="fc">{ownExperiments.length}</span></button>
					<button class="ftab" class:active={filterStatus === 'keep'} onclick={() => filterStatus = 'keep'}>Kept <span class="fc">{keptCount}</span></button>
					<button class="ftab" class:active={filterStatus === 'discard'} onclick={() => filterStatus = 'discard'}>Discarded <span class="fc">{discardCount}</span></button>
					{#if crashCount > 0}
						<button class="ftab" class:active={filterStatus === 'crash'} onclick={() => filterStatus = 'crash'}>Crashed <span class="fc">{crashCount}</span></button>
					{/if}
				</div>
			</div>
			<div class="list-scroll" bind:this={listScrollEl}>
				{#each sorted as exp (exp.id)}
					{@const isSelected = selectedExp?.id === exp.id}
					{@const isBest = ownBestBpb != null && exp.val_bpb === ownBestBpb && exp.status === 'keep' && isOwnExperiment(exp)}
					{@const bench = isBenchmark(exp)}
					{@const isNewBest = exp.status === 'keep' && bestSoFarAt(exp.id) === exp.val_bpb && exp.id > 1}
					{@const beatsK = karpathyBestBpb != null && exp.val_bpb < karpathyBestBpb && exp.status === 'keep' && !bench}
					<button class="exp-row" class:selected={isSelected} class:is-best={isBest} class:is-bench={bench} class:is-new-best={isNewBest && !isBest} data-id={exp.id} onclick={() => selectExp(exp)}>
						<div class="row-left">
							{#if bench}
								<span class="row-badge bench">K</span>
							{:else if exp.status === 'keep'}
								<span class="row-badge keep">{isNewBest ? '★' : '✓'}</span>
							{:else if exp.status === 'crash'}
								<span class="row-badge crash">!</span>
							{:else}
								<span class="row-badge discard">×</span>
							{/if}
							<div class="row-info">
								<span class="row-name">
									<span class="row-num">#{exp.id}</span>
									{exp.experiment_id.replace(/^exp-\d+-/, '')}
								</span>
								<span class="row-desc">{exp.description}</span>
							</div>
						</div>
						<div class="row-right">
							<span class="row-bpb">{exp.val_bpb.toFixed(4)}</span>
							{#if beatsK}
								<span class="row-beat-k">▼K</span>
							{:else if isBest}
								<span class="row-best-tag">BEST</span>
							{:else if isNewBest && !bench}
								<span class="row-newbest-tag">NEW BEST</span>
							{/if}
						</div>
					</button>
				{/each}
			</div>
		</div>

		<!-- Right: detail panel -->
		<div class="detail-panel">
			{#if selectedExp}
				{@const exp = selectedExp}
				{@const isBest = ownBestBpb != null && exp.val_bpb === ownBestBpb && exp.status === 'keep' && isOwnExperiment(exp)}
				{@const bench = isBenchmark(exp)}

				<!-- 1. Header -->
				<div class="d-header">
					<div class="d-title-row">
						{#if bench}<span class="d-badge bench">benchmark</span>
						{:else}<span class="d-badge {exp.status}">{exp.status}</span>{/if}
						<h2 class="d-title">{exp.experiment_id}</h2>
						{#if isBest}<span class="best-tag">BEST</span>{/if}
						{#if bench}<span class="bench-tag">KARPATHY REFERENCE</span>{/if}
					</div>
					<div class="d-meta">
						<code>{exp.commit.slice(0, 7)}</code>
						<span class="sep">·</span>
						<span>{new Date(exp.timestamp).toLocaleString()}</span>
						{#if exp.gpu_name}<span class="sep">·</span><span>{exp.gpu_name}</span>{/if}
					</div>
				</div>

				<!-- 2. Hypothesis (FIRST — sets context) -->
				{#if exp.rationale}
					<div class="d-sec">
						<div class="d-sec-head">
							<span class="d-sec-num">1</span>
							<h3>Hypothesis</h3>
							{#if exp.hypothesis_id}<span class="htag">{exp.hypothesis_id}</span>{/if}
						</div>
						<p class="d-hypothesis">{exp.rationale}</p>
					</div>
				{/if}

				<!-- 3. What Changed (only show when both child AND parent have hyperparameters for a real diff) -->
				{#if exp.hyperparameters && Object.keys(exp.hyperparameters).length > 0 && parentExp?.hyperparameters && Object.keys(parentExp.hyperparameters).length > 0}
					<div class="d-sec">
						<div class="d-sec-head">
							<span class="d-sec-num">2</span>
							<h3>What Changed</h3>
						</div>
						<HyperparamDiff params={exp.hyperparameters} parentParams={parentExp.hyperparameters} />
					</div>
				{/if}

				<!-- 4. Result -->
				<div class="d-sec">
					<div class="d-sec-head">
						<span class="d-sec-num">{exp.hyperparameters && Object.keys(exp.hyperparameters).length > 0 ? '3' : '2'}</span>
						<h3>Result</h3>
					</div>
					<div class="result-hero" class:hero-bench={bench}>
						<div class="hero-bpb">
							<span class="hero-value">{exp.val_bpb.toFixed(6)}</span>
							<span class="hero-label">val_bpb</span>
						</div>
						{#if exp.delta !== 0}
							<div class="hero-delta {deltaClass(exp.delta)}">
								<span class="dv">{exp.delta > 0 ? '+' : ''}{exp.delta.toFixed(6)}</span>
								{#if baselineBpb && !bench}
									<span class="dp">{((1 - exp.val_bpb / baselineBpb) * 100).toFixed(2)}% vs baseline</span>
								{/if}
							</div>
						{/if}
						{#if !bench && karpathyBestBpb != null}
							<div class="hero-vs-k">
								{#if exp.val_bpb < karpathyBestBpb}
									<span class="vs-k good">beats Karpathy by {(karpathyBestBpb - exp.val_bpb).toFixed(4)}</span>
								{:else}
									<span class="vs-k dim">behind Karpathy by {(exp.val_bpb - karpathyBestBpb).toFixed(4)}</span>
								{/if}
							</div>
						{/if}
					</div>

					<div class="metrics">
						<div class="m"><span class="mv">{fmt(exp.num_steps, 0)}</span><span class="ml">steps</span></div>
						<div class="m"><span class="mv">{fmtTime(exp.training_seconds)}</span><span class="ml">train</span></div>
						<div class="m"><span class="mv">{fmtTime(exp.total_seconds)}</span><span class="ml">total</span></div>
						<div class="m"><span class="mv">{fmt(exp.peak_vram_gb, 1, 'GB')}</span><span class="ml">VRAM</span></div>
						<div class="m"><span class="mv">{fmt(exp.num_params_M, 1, 'M')}</span><span class="ml">params</span></div>
						<div class="m"><span class="mv">{fmt(exp.total_tokens_M, 1, 'M')}</span><span class="ml">tokens</span></div>
						{#if exp.mfu_percent}<div class="m"><span class="mv">{fmt(exp.mfu_percent, 1, '%')}</span><span class="ml">MFU</span></div>{/if}
					</div>
				</div>

				<!-- 5. Analysis -->
				{@const notesText = formatNotes(exp.notes)}
				{#if notesText}
					<div class="d-sec">
						<div class="d-sec-head">
							<span class="d-sec-num">{exp.hyperparameters && Object.keys(exp.hyperparameters).length > 0 ? '4' : '3'}</span>
							<h3>Analysis</h3>
						</div>
						<p class="d-text">{notesText}</p>
					</div>
				{/if}

				<!-- 6. Collapsibles -->
				{#if exp.decision_markdown}
					<details class="d-sec collapsible">
						<summary><h3>Full Decision Write-up</h3></summary>
						<div class="md-body">
							{#each exp.decision_markdown.split('\n') as line}
								{#if line.startsWith('# ')}<h4 class="md-h1">{line.slice(2)}</h4>
								{:else if line.startsWith('## ')}<h5 class="md-h2">{line.slice(3)}</h5>
								{:else if line.startsWith('- ')}<p class="md-li">{@html line.slice(2).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')}</p>
								{:else if line.trim()}<p class="md-p">{@html line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')}</p>
								{/if}
							{/each}
						</div>
					</details>
				{/if}

				{#if diffText}
					<details class="d-sec collapsible">
						<summary><h3>Code Diff</h3></summary>
						<div class="diff-wrap"><DiffViewer diff={diffText} /></div>
					</details>
				{/if}
			{:else}
				<div class="empty"><p>Select an experiment to view details</p></div>
			{/if}
		</div>
	</div>
</div>

<style>
	.page { display: flex; flex-direction: column; height: calc(100vh - 56px - 3rem); gap: 0.75rem; overflow: hidden; }

	/* Top section */
	.top-section { flex-shrink: 0; background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-sm); overflow: hidden; }
	.summary-row { display: flex; align-items: center; justify-content: space-between; padding: 0.55rem 1rem; border-bottom: 1px solid var(--border); }
	.chips { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
	.chip { display: flex; flex-direction: column; gap: 0.02rem; }
	.chip-val { font-family: var(--font-mono); font-size: 0.92rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }
	.chip-val.accent { color: var(--accent); }
	.chip-val.good { color: var(--green); }
	.chip-val.bad { color: var(--red); }
	.chip-lbl { font-size: 0.55rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 500; }
	.chip-lbl.beat { color: var(--green); font-weight: 700; }
	.chip-sep { width: 1px; height: 24px; background: var(--border); }
	.keep-c { color: var(--green); } .discard-c { color: var(--red); } .crash-c { color: var(--amber); } .karp-c { color: #3B82F6; }

	.viz-tabs { display: flex; gap: 0.25rem; }
	.viz-tab { padding: 0.3rem 0.6rem; border-radius: var(--radius-sm); border: 1px solid transparent; background: none; font-size: 0.72rem; font-weight: 500; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease; font-family: var(--font-body); }
	.viz-tab:hover { background: var(--bg-hover); }
	.viz-tab.active { background: var(--accent-light); color: var(--accent); border-color: var(--accent-medium); }

	/* Chart */
	.viz-area { height: 280px; }
	.chart-container { width: 100%; height: 100%; cursor: crosshair; }
	.bpb-chart { display: block; }
	.bpb-chart :global(.ax-text) { font-family: var(--font-mono); font-size: 10px; fill: var(--text-dim); }
	.bpb-chart :global(.ax-label) { font-family: var(--font-body); font-size: 10px; fill: var(--text-dim); }
	.bpb-chart :global(.tt-text) { font-family: var(--font-mono); font-size: 11px; }
	.bpb-chart :global(.tt-sub) { font-family: var(--font-mono); font-size: 9px; }
	.bpb-chart :global(.leg-text) { font-family: var(--font-body); font-size: 9.5px; fill: var(--text-dim); }
	.bpb-chart :global(.milestone-text) { font-family: var(--font-mono); font-size: 9px; fill: var(--green); font-weight: 600; }
	.bpb-chart :global(.dot) { cursor: pointer; }

	/* Browser */
	.browser { flex: 1; min-height: 0; display: grid; grid-template-columns: 340px 1fr; gap: 0.75rem; }

	/* List */
	.list-panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-sm); display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
	.list-header { padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); flex-shrink: 0; }
	.filter-tabs { display: flex; gap: 0.2rem; }
	.ftab { display: flex; align-items: center; gap: 0.25rem; padding: 0.28rem 0.5rem; border-radius: var(--radius-sm); border: 1px solid transparent; background: none; font-size: 0.7rem; font-weight: 500; color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease; font-family: var(--font-body); }
	.ftab:hover { background: var(--bg-hover); }
	.ftab.active { background: var(--accent-light); color: var(--accent); border-color: var(--accent-medium); font-weight: 600; }
	.fc { font-family: var(--font-mono); font-size: 0.62rem; opacity: 0.7; }
	.list-scroll { flex: 1; overflow-y: auto; min-height: 0; }

	.exp-row { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 0.5rem 0.6rem; border: none; border-bottom: 1px solid var(--border); background: none; cursor: pointer; transition: all 0.1s ease; text-align: left; font-family: var(--font-body); border-left: 3px solid transparent; }
	.exp-row:hover { background: var(--bg-hover); }
	.exp-row.selected { background: var(--accent-light); border-left-color: var(--accent); }
	.exp-row.is-best { background: var(--green-bg); }
	.exp-row.is-best.selected { background: var(--accent-light); border-left-color: var(--green); }
	.exp-row.is-bench { background: rgba(59,130,246,0.05); }
	.exp-row.is-bench.selected { background: var(--accent-light); border-left-color: #3B82F6; }
	.row-left { display: flex; align-items: center; gap: 0.4rem; min-width: 0; flex: 1; }
	.row-badge { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.58rem; font-weight: 700; flex-shrink: 0; }
	.row-badge.keep { background: var(--green-bg); color: var(--green); }
	.row-badge.discard { background: var(--red-bg); color: var(--red); }
	.row-badge.crash { background: var(--amber-bg); color: var(--amber); }
	.row-badge.bench { background: rgba(59,130,246,0.1); color: #3B82F6; }
	.row-info { display: flex; flex-direction: column; gap: 0.04rem; min-width: 0; }
	.row-name { font-size: 0.73rem; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.row-num { font-family: var(--font-mono); color: var(--text-dim); font-weight: 500; margin-right: 0.15rem; }
	.row-desc { font-size: 0.62rem; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.row-hyp { font-size: 0.6rem; color: var(--accent); font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.exp-row.is-new-best { border-left-color: var(--green); background: rgba(22, 163, 74, 0.04); }
	.row-right { display: flex; align-items: center; gap: 0.4rem; flex-shrink: 0; padding-left: 0.35rem; }
	.row-bpb { font-family: var(--font-mono); font-size: 0.78rem; font-weight: 600; color: var(--text); }
	.row-beat-k { font-size: 0.55rem; font-weight: 700; color: var(--green); background: var(--green-bg); padding: 0.1rem 0.3rem; border-radius: 3px; letter-spacing: 0.03em; }
	.row-best-tag { font-size: 0.5rem; font-weight: 700; color: white; background: var(--green); padding: 0.1rem 0.3rem; border-radius: 3px; letter-spacing: 0.04em; }
	.row-newbest-tag { font-size: 0.5rem; font-weight: 700; color: var(--green); background: var(--green-bg); padding: 0.1rem 0.3rem; border-radius: 3px; letter-spacing: 0.04em; }

	/* Detail panel */
	.detail-panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-sm); overflow-y: auto; padding: 1.25rem; min-height: 0; }

	.d-header { margin-bottom: 1rem; }
	.d-title-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem; flex-wrap: wrap; }
	.d-badge { font-size: 0.58rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; padding: 0.16rem 0.45rem; border-radius: 999px; }
	.d-badge.keep { background: var(--green-bg); color: var(--green); }
	.d-badge.discard { background: var(--red-bg); color: var(--red); }
	.d-badge.crash { background: var(--amber-bg); color: var(--amber); }
	.d-badge.bench { background: var(--amber-bg); color: var(--amber); }
	.d-title { font-family: var(--font-mono); font-size: 0.95rem; font-weight: 600; color: var(--text); }
	.best-tag { font-size: 0.52rem; font-weight: 700; letter-spacing: 0.08em; background: var(--green); color: white; padding: 0.1rem 0.4rem; border-radius: 999px; }
	.bench-tag { font-size: 0.52rem; font-weight: 700; letter-spacing: 0.06em; background: var(--amber); color: white; padding: 0.1rem 0.4rem; border-radius: 999px; }
	.d-meta { display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; font-size: 0.68rem; color: var(--text-secondary); }
	.d-meta code { font-family: var(--font-mono); font-size: 0.65rem; background: var(--bg-hover); padding: 0.06rem 0.28rem; border-radius: 3px; }
	.sep { color: var(--border-strong); }

	/* Sections with step numbers */
	.d-sec { margin-bottom: 1rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border); }
	.d-sec:last-child { border-bottom: none; margin-bottom: 0; }
	.d-sec-head { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.45rem; }
	.d-sec-num { width: 18px; height: 18px; border-radius: 50%; background: var(--accent-light); color: var(--accent); font-size: 0.6rem; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
	.d-sec h3 { font-size: 0.62rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; display: inline; }
	.htag { font-family: var(--font-mono); font-size: 0.62rem; background: var(--accent-light); color: var(--accent); padding: 0.1rem 0.4rem; border-radius: 999px; }
	.d-hypothesis { font-size: 0.82rem; color: var(--text-secondary); line-height: 1.55; font-style: italic; margin-top: 0.15rem; }
	.d-text { font-size: 0.8rem; color: var(--text-secondary); line-height: 1.55; }

	/* Result hero */
	.result-hero { display: flex; align-items: baseline; gap: 0.85rem; flex-wrap: wrap; padding: 0.75rem 0.9rem; margin-bottom: 0.75rem; background: var(--bg-subtle); border: 1px solid var(--border); border-radius: var(--radius); }
	.result-hero.hero-bench { border-color: var(--amber); border-style: dashed; background: var(--amber-bg); }
	.hero-bpb { display: flex; align-items: baseline; gap: 0.2rem; }
	.hero-value { font-family: var(--font-mono); font-size: 1.5rem; font-weight: 700; color: var(--text); letter-spacing: -0.03em; }
	.hero-label { font-size: 0.65rem; color: var(--text-dim); text-transform: uppercase; }
	.hero-delta { display: flex; flex-direction: column; gap: 0.04rem; }
	.hero-delta .dv { font-family: var(--font-mono); font-size: 0.9rem; font-weight: 600; }
	.hero-delta.good .dv { color: var(--green); } .hero-delta.bad .dv { color: var(--red); } .hero-delta.neutral .dv { color: var(--text-dim); }
	.dp { font-size: 0.62rem; color: var(--text-dim); }
	.hero-vs-k { font-size: 0.72rem; font-family: var(--font-mono); }
	.vs-k.good { color: var(--green); font-weight: 600; } .vs-k.dim { color: var(--text-dim); }
	.dim { opacity: 0.6; }

	/* Metrics */
	.metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(88px, 1fr)); gap: 0.35rem; }
	.m { display: flex; flex-direction: column; gap: 0.08rem; padding: 0.45rem 0.55rem; background: var(--bg-subtle); border: 1px solid var(--border); border-radius: var(--radius-sm); }
	.mv { font-family: var(--font-mono); font-size: 0.85rem; font-weight: 600; color: var(--text); }
	.mv :global(small) { font-size: 0.62rem; font-weight: 500; color: var(--text-secondary); }
	.ml { font-size: 0.55rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; }

	/* Collapsible */
	.collapsible summary { cursor: pointer; user-select: none; padding: 0.2rem 0; list-style: none; }
	.collapsible summary::before { content: '▸'; display: inline-block; margin-right: 0.3rem; font-size: 0.6rem; color: var(--text-dim); transition: transform 0.15s ease; }
	.collapsible[open] summary::before { transform: rotate(90deg); }
	.collapsible summary::-webkit-details-marker { display: none; }

	.md-body { margin-top: 0.5rem; font-size: 0.76rem; color: var(--text-secondary); line-height: 1.55; }
	.md-h1 { font-size: 0.85rem; font-weight: 700; color: var(--text); margin: 0.5rem 0 0.25rem; }
	.md-h2 { font-size: 0.76rem; font-weight: 600; color: var(--text); margin: 0.4rem 0 0.2rem; text-transform: uppercase; letter-spacing: 0.04em; }
	.md-p { margin: 0.15rem 0; }
	.md-p :global(strong) { color: var(--text); }
	.md-li { padding-left: 0.8rem; margin: 0.1rem 0; }
	.md-li::before { content: '•'; display: inline-block; margin-left: -0.6rem; margin-right: 0.3rem; color: var(--text-dim); }
	.md-li :global(strong) { color: var(--text); }

	.diff-wrap { margin-top: 0.5rem; }
	.empty { display: flex; align-items: center; justify-content: center; height: 100%; }
	.empty p { color: var(--text-dim); font-size: 0.82rem; }
</style>
