<script lang="ts">
	import { onMount } from 'svelte';
	import type { Experiment, KarpathyOriginal } from '$lib/types';
	import { fetchExperiments, fetchDiff, fetchKarpathyOriginal } from '$lib/api';
	import DiffViewer from '$lib/components/DiffViewer.svelte';
	import HyperparamDiff from '$lib/components/HyperparamDiff.svelte';

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
	const CHART_PAD = { top: 36, right: 80, bottom: 52, left: 72 };
	let chartW = $state(800);
	const chartH = 340;
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
	// Karpathy connecting line through kept dots only
	let karpathyKeptPath = $derived.by(() => {
		const pts: string[] = [];
		karpathyReproSorted.forEach((e, i) => {
			if (e.status === 'keep') pts.push(`${xScaleK(i)},${yScale(e.val_bpb)}`);
		});
		return pts.length > 1 ? `M${pts.join(' L')}` : '';
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

	// Our connecting line through kept dots only
	let ourKeptPath = $derived.by(() => {
		const pts: string[] = [];
		chartOwnExps.forEach((e, i) => {
			if (e.status === 'keep') pts.push(`${xScaleOwn(i)},${yScale(e.val_bpb)}`);
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
	// Each series gets its own X scale so both span the full width
	// This compares convergence trajectories: "how did each search perform over its own run?"
	function xScaleOwn(idx: number): number {
		const max = Math.max(chartOwnExps.length - 1, 1);
		return (idx / max) * innerW;
	}
	function xScaleK(idx: number): number {
		const max = Math.max(karpathyReproSorted.length - 1, 1);
		return (idx / max) * innerW;
	}

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

	// Outperformance zone: shaded area where our best-so-far < Karpathy benchmark
	let outperformancePath = $derived.by(() => {
		if (karpathyBestBpb == null || chartOwnExps.length === 0) return '';
		const kY = yScale(karpathyBestBpb);
		let best = Infinity;
		const segments: { x: number; y: number }[] = [];
		chartOwnExps.forEach((e, i) => {
			if (e.status === 'keep' && e.val_bpb < best) best = e.val_bpb;
			if (best < karpathyBestBpb!) {
				segments.push({ x: xScaleOwn(i), y: yScale(best) });
			}
		});
		if (segments.length < 2) return '';
		const first = segments[0];
		const last = segments[segments.length - 1];
		const top = segments.map(s => `${s.x},${s.y}`).join(' L');
		return `M${top} L${last.x},${kY} L${first.x},${kY} Z`;
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
		// Find nearest own experiment by pixel distance
		let bestIdx = -1;
		let bestDist = Infinity;
		for (let i = 0; i < chartOwnExps.length; i++) {
			const px = xScaleOwn(i);
			const py = yScale(chartOwnExps[i].val_bpb);
			const dist = Math.sqrt((mx - px) ** 2 + (my - CHART_PAD.top - py + CHART_PAD.top) ** 2);
			if (dist < bestDist) { bestDist = dist; bestIdx = i; }
		}
		chartHoveredIdx = bestDist < 35 ? bestIdx : null;
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
								<stop offset="0%" stop-color="var(--green)" stop-opacity="0.12" />
								<stop offset="100%" stop-color="var(--green)" stop-opacity="0.02" />
							</linearGradient>
							<linearGradient id="kFill" x1="0" x2="0" y1="0" y2="1">
								<stop offset="0%" stop-color="#3B82F6" stop-opacity="0.06" />
								<stop offset="100%" stop-color="#3B82F6" stop-opacity="0.01" />
							</linearGradient>
							<linearGradient id="winZone" x1="0" x2="0" y1="0" y2="1">
								<stop offset="0%" stop-color="var(--green)" stop-opacity="0.18" />
								<stop offset="100%" stop-color="var(--green)" stop-opacity="0.06" />
							</linearGradient>
						</defs>

						<g transform="translate({CHART_PAD.left}, 0)">
							<!-- Grid -->
							{#each yTicks as tick}
								<line x1="0" x2={innerW} y1={yScale(tick)} y2={yScale(tick)} stroke="var(--border)" stroke-width="1" />
								<text x="-10" y={yScale(tick)} dy="3.5" text-anchor="end" class="ax-text">{tick.toFixed(3)}</text>
							{/each}

							<!-- Outperformance zone (shaded area where our best < Karpathy's) -->
							{#if outperformancePath}
								<path d={outperformancePath} fill="url(#winZone)" />
								<path d={outperformancePath} fill="none" stroke="var(--green)" stroke-width="0.5" opacity="0.2" />
							{/if}

							<!-- Karpathy's published best benchmark line -->
							{#if karpathyBestBpb != null}
								<line x1="0" x2={innerW} y1={yScale(karpathyBestBpb)} y2={yScale(karpathyBestBpb)} stroke="#3B82F6" stroke-width="2" stroke-dasharray="10,5" opacity="0.55" />
							{/if}

							<!-- ── Karpathy's search reproduced on OUR hardware (blue) ── -->
							<!-- Karpathy connecting line through kept dots -->
							{#if karpathyKeptPath}
								<path d={karpathyKeptPath} fill="none" stroke="#3B82F6" stroke-width="1.5" opacity="0.35" />
							{/if}
							<!-- Karpathy repro best-so-far fill + line -->
							{#if karpathyBestPath}
								{@const lastKX = xScaleK(karpathyReproSorted.length - 1)}
								<path d="{karpathyBestPath} L{lastKX},{yScale(yDomain.max)} L{xScaleK(0)},{yScale(yDomain.max)} Z" fill="url(#kFill)" />
								<path d={karpathyBestPath} fill="none" stroke="#3B82F6" stroke-width="2.5" opacity="0.7" />
							{/if}
							<!-- Karpathy repro individual data points -->
							{#each karpathyReproSorted as exp, i}
								{#if inYRange(exp.val_bpb)}
									{@const cx = xScaleK(i)}
									{@const cy = yScale(exp.val_bpb)}
									{#if exp.status === 'keep'}
										<circle {cx} {cy} r="5" fill="#3B82F6" opacity="0.65" />
									{:else}
										<circle {cx} {cy} r="3" fill="none" stroke="#93C5FD" stroke-width="1.5" opacity="0.45" />
									{/if}
								{/if}
							{/each}

							<!-- ── Our runs (green, in front) ── -->
							<!-- Our connecting line through kept dots -->
							{#if ourKeptPath}
								<path d={ourKeptPath} fill="none" stroke="var(--green)" stroke-width="1.5" opacity="0.25" />
							{/if}
							<!-- Our best-so-far fill + line -->
							{#if ourBestPath}
								{@const lastOwnX = xScaleOwn(chartOwnExps.length - 1)}
								<path d="{ourBestPath} L{lastOwnX},{yScale(yDomain.max)} L{xScaleOwn(0)},{yScale(yDomain.max)} Z" fill="url(#ourFill)" />
								<path d={ourBestPath} fill="none" stroke="var(--green)" stroke-width="3.5" opacity="0.9" />
							{/if}
							<!-- Our individual data points -->
							{#each chartOwnExps as exp, i}
								{@const cx = xScaleOwn(i)}
								{@const cy = yScale(exp.val_bpb)}
								{@const isKeep = exp.status === 'keep'}
								{@const isCrash = exp.status === 'crash'}
								{@const active = chartHoveredIdx === i || selectedExp?.id === exp.id}
								{#if isKeep}
									<circle {cx} {cy} r={active ? 7 : 5} fill="var(--green)" opacity={active ? 1 : 0.9} class="dot" />
								{:else if isCrash}
									<polygon points="{cx},{cy - (active ? 7 : 5)} {cx + (active ? 6.5 : 4.5)},{cy + (active ? 4 : 3)} {cx - (active ? 6.5 : 4.5)},{cy + (active ? 4 : 3)}"
										fill="var(--amber)" opacity={active ? 1 : 0.65} class="dot" />
								{:else}
									<circle {cx} {cy} r={active ? 5 : 3} fill="var(--bg-card)" stroke="var(--border-strong)" stroke-width="1.5" opacity={active ? 1 : 0.55} class="dot" />
								{/if}
								{#if selectedExp?.id === exp.id}
									<circle {cx} {cy} r="12" fill="none" stroke="var(--accent)" stroke-width="2.5" opacity="0.5" />
								{/if}
							{/each}

							<!-- "Beat Karpathy" annotation -->
							{#if firstBeatOwnIdx != null && firstBeatExp}
								{@const fbx = xScaleOwn(firstBeatOwnIdx)}
								{@const fby = yScale(firstBeatExp.val_bpb)}
								<line x1={fbx} x2={fbx} y1={fby - 10} y2={CHART_PAD.top + 2} stroke="var(--green)" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.6" />
								<g transform="translate({fbx},{CHART_PAD.top - 4})">
									<rect x="-72" y="-16" width="144" height="22" rx="11" fill="var(--green)" opacity="0.15" />
									<rect x="-72" y="-16" width="144" height="22" rx="11" fill="none" stroke="var(--green)" stroke-width="1" opacity="0.3" />
									<text x="0" y="-5" text-anchor="middle" dominant-baseline="central" class="milestone-text" style="font-size: 11px">beat Karpathy @ #{firstBeatExp.id}</text>
								</g>
							{/if}

							<!-- Hover tooltip -->
							{#if chartHoveredIdx != null && chartOwnExps[chartHoveredIdx]}
								{@const hExp = chartOwnExps[chartHoveredIdx]}
								{@const hx = xScaleOwn(chartHoveredIdx)}
								{@const hy = yScale(hExp.val_bpb)}
								<line x1={hx} x2={hx} y1={CHART_PAD.top} y2={CHART_PAD.top + innerH} stroke="var(--text-dim)" stroke-width="1" opacity="0.2" stroke-dasharray="3,3" />
								{@const ty = hy < CHART_PAD.top + 70 ? hy + 18 : hy - 60}
								{@const tx = hx > innerW - 130 ? hx - 200 : hx + 12}
								<g transform="translate({tx},{ty})">
									<rect x="0" y="0" width="190" height="52" rx="8" fill="var(--text)" opacity="0.95" />
									<text x="10" y="19" class="tt-text" fill="white" font-weight="700">{hExp.val_bpb.toFixed(6)} bpb</text>
									<text x="10" y="38" class="tt-sub" fill="rgba(255,255,255,0.65)">#{hExp.id} {hExp.experiment_id.replace(/^exp-\d+-/, '')} · {hExp.status}</text>
								</g>
							{/if}

							<!-- X axis + ticks (% of search) -->
							<line x1="0" x2={innerW} y1={CHART_PAD.top + innerH} y2={CHART_PAD.top + innerH} stroke="var(--border)" stroke-width="1" />
							{#each [0, 25, 50, 75, 100] as pct}
								{@const tx = (pct / 100) * innerW}
								<line x1={tx} x2={tx} y1={CHART_PAD.top + innerH} y2={CHART_PAD.top + innerH + 5} stroke="var(--border-strong)" stroke-width="1" />
								<text x={tx} y={CHART_PAD.top + innerH + 18} text-anchor="middle" class="ax-text">{pct}%</text>
							{/each}
						</g>

						<!-- Legend -->
						<g transform="translate({CHART_PAD.left + 12}, {chartH - 28})">
							<rect x="-8" y="-14" width="620" height="24" rx="6" fill="var(--bg-card)" opacity="0.85" />
							<line x1="0" x2="20" y1="-3" y2="-3" stroke="var(--green)" stroke-width="3.5" opacity="0.9" />
							<circle cx="10" cy="-3" r="4" fill="var(--green)" />
							<text x="28" y="1" class="leg-text" style="font-size: 11px; font-weight: 600; fill: var(--text-secondary)">Autonomous search ({ownExperiments.length} runs)</text>
							<line x1="260" x2="280" y1="-3" y2="-3" stroke="#3B82F6" stroke-width="2.5" opacity="0.7" />
							<circle cx="270" cy="-3" r="4" fill="#3B82F6" opacity="0.6" />
							<text x="288" y="1" class="leg-text" style="font-size: 11px; fill: var(--text-dim)">Karpathy's search ({karpathyReproSorted.length} runs, same hardware)</text>
						</g>

						<!-- Axis labels -->
						<text x="16" y={CHART_PAD.top + innerH / 2} text-anchor="middle" class="ax-label" style="font-size: 12px" transform="rotate(-90, 16, {CHART_PAD.top + innerH / 2})">val_bpb (lower = better)</text>
						<text x={CHART_PAD.left + innerW / 2} y={chartH - 4} text-anchor="middle" class="ax-label" style="font-size: 12px">search progress</text>
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
				{@const notesText = formatNotes(exp.notes)}

				<!-- Header: name + result together -->
				<div class="d-top">
					<div class="d-name-row">
						{#if bench}<span class="d-badge bench">benchmark</span>
						{:else}<span class="d-badge {exp.status}">{exp.status}</span>{/if}
						<h2 class="d-title">{exp.experiment_id.replace(/^exp-\d+-/, '')}</h2>
						{#if isBest}<span class="best-tag">BEST</span>{/if}
						{#if bench}<span class="bench-tag">KARPATHY REF</span>{/if}
					</div>
					<div class="d-result-row">
						<span class="d-bpb">{exp.val_bpb.toFixed(6)}</span>
						{#if exp.delta !== 0}
							<span class="d-delta {deltaClass(exp.delta)}">{exp.delta > 0 ? '+' : ''}{exp.delta.toFixed(6)}</span>
						{/if}
						{#if !bench && karpathyBestBpb != null}
							{#if exp.val_bpb < karpathyBestBpb}
								<span class="d-vs-k good">beats K by {(karpathyBestBpb - exp.val_bpb).toFixed(4)}</span>
							{:else}
								<span class="d-vs-k dim">+{(exp.val_bpb - karpathyBestBpb).toFixed(4)} vs K</span>
							{/if}
						{/if}
					</div>
					<div class="d-meta">
						<code>{exp.commit.slice(0, 7)}</code>
						<span>{new Date(exp.timestamp).toLocaleDateString()}</span>
						{#if exp.gpu_name}<span>{exp.gpu_name}</span>{/if}
						<span class="d-id">{exp.experiment_id}</span>
					</div>
				</div>

				<!-- Metrics: compact inline -->
				<div class="d-metrics">
					{#if exp.num_steps > 0}<span><strong>{fmt(exp.num_steps, 0)}</strong> steps</span>{/if}
					{#if exp.training_seconds}<span><strong>{fmtTime(exp.training_seconds)}</strong> train</span>{/if}
					{#if exp.peak_vram_gb}<span><strong>{fmt(exp.peak_vram_gb, 1)}</strong>GB</span>{/if}
					{#if exp.num_params_M}<span><strong>{fmt(exp.num_params_M, 1)}</strong>M params</span>{/if}
					{#if exp.total_tokens_M}<span><strong>{fmt(exp.total_tokens_M, 1)}</strong>M tok</span>{/if}
					{#if exp.mfu_percent}<span><strong>{fmt(exp.mfu_percent, 1)}</strong>% MFU</span>{/if}
				</div>

				<!-- Description -->
				{#if exp.description}
					<p class="d-desc">{exp.description}</p>
				{/if}

				<!-- Hypothesis -->
				{#if exp.rationale}
					<div class="d-block">
						<h3>Hypothesis</h3>
						<p class="d-quote">{exp.rationale}</p>
					</div>
				{/if}

				<!-- What Changed -->
				{#if exp.hyperparameters && Object.keys(exp.hyperparameters).length > 0 && parentExp?.hyperparameters && Object.keys(parentExp.hyperparameters).length > 0}
					<div class="d-block">
						<h3>Changes</h3>
						<HyperparamDiff params={exp.hyperparameters} parentParams={parentExp.hyperparameters} />
					</div>
				{/if}

				<!-- Analysis -->
				{#if notesText}
					<div class="d-block">
						<h3>Analysis</h3>
						<p class="d-text">{notesText}</p>
					</div>
				{/if}

				<!-- Collapsibles -->
				{#if exp.decision_markdown}
					<details class="d-collapse">
						<summary>Decision Write-up</summary>
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
					<details class="d-collapse">
						<summary>Code Diff</summary>
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
	.viz-area { height: 340px; }
	.chart-container { width: 100%; height: 100%; cursor: crosshair; }
	.bpb-chart { display: block; }
	.bpb-chart :global(.ax-text) { font-family: var(--font-mono); font-size: 11px; fill: var(--text-dim); }
	.bpb-chart :global(.ax-label) { font-family: var(--font-body); font-size: 12px; fill: var(--text-dim); }
	.bpb-chart :global(.tt-text) { font-family: var(--font-mono); font-size: 12px; }
	.bpb-chart :global(.tt-sub) { font-family: var(--font-mono); font-size: 10px; }
	.bpb-chart :global(.leg-text) { font-family: var(--font-body); font-size: 11px; fill: var(--text-dim); }
	.bpb-chart :global(.milestone-text) { font-family: var(--font-mono); font-size: 11px; fill: var(--green); font-weight: 700; }
	.bpb-chart :global(.dot) { cursor: pointer; transition: r 0.1s ease; }

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
	.detail-panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-sm); overflow-y: auto; min-height: 0; display: flex; flex-direction: column; }

	/* Top block: name + result + meta */
	.d-top { padding: 0.85rem 1rem 0.65rem; border-bottom: 1px solid var(--border); }
	.d-name-row { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.3rem; }
	.d-badge { font-size: 0.55rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; padding: 0.12rem 0.4rem; border-radius: 999px; flex-shrink: 0; }
	.d-badge.keep { background: var(--green-bg); color: var(--green); }
	.d-badge.discard { background: var(--red-bg); color: var(--red); }
	.d-badge.crash { background: var(--amber-bg); color: var(--amber); }
	.d-badge.bench { background: rgba(59,130,246,0.1); color: #3B82F6; }
	.d-title { font-family: var(--font-mono); font-size: 0.88rem; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.best-tag { font-size: 0.5rem; font-weight: 700; letter-spacing: 0.06em; background: var(--green); color: white; padding: 0.1rem 0.35rem; border-radius: 999px; flex-shrink: 0; }
	.bench-tag { font-size: 0.5rem; font-weight: 700; letter-spacing: 0.06em; background: #3B82F6; color: white; padding: 0.1rem 0.35rem; border-radius: 999px; flex-shrink: 0; }

	.d-result-row { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.35rem; }
	.d-bpb { font-family: var(--font-mono); font-size: 1.35rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }
	.d-delta { font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600; }
	.d-delta.good { color: var(--green); }
	.d-delta.bad { color: var(--red); opacity: 0.8; }
	.d-delta.neutral { color: var(--text-dim); }
	.d-vs-k { font-family: var(--font-mono); font-size: 0.7rem; font-weight: 500; }
	.d-vs-k.good { color: var(--green); }
	.d-vs-k.dim { color: var(--text-dim); opacity: 0.7; }

	.d-meta { display: flex; align-items: center; gap: 0.5rem; font-size: 0.65rem; color: var(--text-dim); flex-wrap: wrap; }
	.d-meta code { font-family: var(--font-mono); font-size: 0.62rem; background: var(--bg-hover); padding: 0.06rem 0.25rem; border-radius: 3px; color: var(--text-secondary); }
	.d-id { font-family: var(--font-mono); font-size: 0.6rem; opacity: 0.5; }

	/* Compact metrics row */
	.d-metrics { display: flex; flex-wrap: wrap; gap: 0.35rem 0.6rem; padding: 0.5rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.72rem; color: var(--text-dim); font-family: var(--font-mono); }
	.d-metrics span { white-space: nowrap; }
	.d-metrics strong { color: var(--text); font-weight: 600; }

	/* Description */
	.d-desc { padding: 0.55rem 1rem; font-size: 0.78rem; color: var(--text-secondary); line-height: 1.45; border-bottom: 1px solid var(--border); }

	/* Content blocks */
	.d-block { padding: 0.6rem 1rem; border-bottom: 1px solid var(--border); }
	.d-block:last-child { border-bottom: none; }
	.d-block h3 { font-size: 0.6rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600; margin-bottom: 0.35rem; }
	.htag { font-family: var(--font-mono); font-size: 0.58rem; background: var(--accent-light); color: var(--accent); padding: 0.08rem 0.35rem; border-radius: 999px; vertical-align: middle; }
	.d-quote { font-size: 0.78rem; color: var(--text-secondary); line-height: 1.5; font-style: italic; border-left: 2px solid var(--border-strong); padding-left: 0.6rem; }
	.d-text { font-size: 0.78rem; color: var(--text-secondary); line-height: 1.5; }

	/* Collapsibles */
	.d-collapse { padding: 0 1rem; border-bottom: 1px solid var(--border); }
	.d-collapse:last-child { border-bottom: none; }
	.d-collapse summary { cursor: pointer; user-select: none; padding: 0.5rem 0; list-style: none; font-size: 0.68rem; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; display: flex; align-items: center; gap: 0.3rem; }
	.d-collapse summary::before { content: '▸'; font-size: 0.55rem; display: inline-block; transition: transform 0.15s ease; }
	.d-collapse[open] summary::before { transform: rotate(90deg); }
	.d-collapse summary:hover { color: var(--text-secondary); }
	.d-collapse summary::-webkit-details-marker { display: none; }

	.md-body { padding-bottom: 0.6rem; font-size: 0.74rem; color: var(--text-secondary); line-height: 1.5; }
	.md-h1 { font-size: 0.82rem; font-weight: 700; color: var(--text); margin: 0.4rem 0 0.2rem; }
	.md-h2 { font-size: 0.74rem; font-weight: 600; color: var(--text); margin: 0.35rem 0 0.15rem; }
	.md-p { margin: 0.12rem 0; }
	.md-p :global(strong) { color: var(--text); }
	.md-li { padding-left: 0.8rem; margin: 0.1rem 0; }
	.md-li::before { content: '•'; display: inline-block; margin-left: -0.6rem; margin-right: 0.3rem; color: var(--text-dim); }
	.md-li :global(strong) { color: var(--text); }

	.diff-wrap { padding-bottom: 0.6rem; }
	.empty { display: flex; align-items: center; justify-content: center; height: 100%; }
	.empty p { color: var(--text-dim); font-size: 0.82rem; }
</style>
