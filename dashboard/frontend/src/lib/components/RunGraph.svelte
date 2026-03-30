<script lang="ts">
	import type { Experiment, ParamChange } from '$lib/types';
	import { HYPERPARAM_KEYS } from '$lib/types';

	let { experiments = [], onSelect = (_e: Experiment | null) => {}, focusId = null as number | null }: {
		experiments: Experiment[];
		onSelect?: (e: Experiment | null) => void;
		focusId?: number | null;
	} = $props();

	// --- Container & sizing ---
	let containerEl: HTMLDivElement;
	let width = $state(900);
	let height = $state(600);

	$effect(() => {
		if (!containerEl) return;
		const obs = new ResizeObserver(entries => {
			width = entries[0].contentRect.width;
			height = entries[0].contentRect.height;
		});
		obs.observe(containerEl);
		return () => obs.disconnect();
	});

	// --- Transform (pan & zoom) ---
	let tx = $state(0);
	let ty = $state(0);
	let sc = $state(1);
	let isPanning = $state(false);
	let panOrigin = { x: 0, y: 0, tx: 0, ty: 0 };

	// --- Interaction state ---
	let selectedId: number | null = $state(null);
	let hoveredId: number | null = $state(null);

	// --- Constants ---
	const PAD = 80;
	const R_KEEP = 26;
	const R_DISCARD = 15;
	const R_CRASH = 12;

	// --- Graph data ---
	interface GNode {
		id: number;
		exp: Experiment;
		x: number;
		y: number;
		r: number;
		fill: string;
		stroke: string;
		paramChanges: ParamChange[];
	}

	interface GEdge {
		fromId: number;
		toId: number;
		path: string;
		kept: boolean;
	}

	// Pre-build lookup maps for O(1) parent resolution
	let commitMap = $derived.by(() => {
		const map = new Map<string, Experiment>();
		for (const e of experiments) map.set(e.commit, e);
		return map;
	});
	let childrenMap = $derived.by(() => {
		const map = new Map<string, Experiment[]>();
		for (const e of experiments) {
			if (!e.parent_commit) continue;
			const arr = map.get(e.parent_commit) || [];
			arr.push(e);
			map.set(e.parent_commit, arr);
		}
		return map;
	});

	let graphNodes = $derived.by((): GNode[] => {
		if (experiments.length === 0) return [];

		const bpbs = experiments.map(e => e.val_bpb);
		const minBpb = Math.min(...bpbs);
		const maxBpb = Math.max(...bpbs);
		const bpbRange = maxBpb - minBpb || 0.1;
		const bpbPad = bpbRange * 0.15;

		const ids = experiments.map(e => e.id);
		const minId = Math.min(...ids);
		const maxId = Math.max(...ids);
		const idRange = maxId - minId || 1;

		const gw = Math.max(width * 1.2, (maxId - minId + 1) * 80);
		const gh = Math.max(height * 0.9, 500);

		return experiments.map(exp => {
			const x = PAD + ((exp.id - minId) / idRange) * (gw - PAD * 2);
			const y = PAD + ((exp.val_bpb - (minBpb - bpbPad)) / (bpbRange + bpbPad * 2)) * (gh - PAD * 2);

			const isKeep = exp.status === 'keep';
			const isCrash = exp.status === 'crash';
			const r = isKeep ? R_KEEP : isCrash ? R_CRASH : R_DISCARD;

			const parent = commitMap.get(exp.parent_commit);
			const paramChanges: ParamChange[] = [];
			if (parent) {
				for (const key of HYPERPARAM_KEYS) {
					const cv = exp[key];
					const pv = parent[key];
					if (cv != null && pv != null && String(cv) !== String(pv)) {
						paramChanges.push({ key, from: pv as string | number, to: cv as string | number });
					}
				}
			}

			return {
				id: exp.id,
				exp,
				x, y, r,
				fill: isKeep ? '#16A34A' : isCrash ? '#B45309' : 'rgba(220,38,38,0.12)',
				stroke: isKeep ? '#16A34A' : isCrash ? '#B45309' : 'rgba(220,38,38,0.45)',
				paramChanges,
			};
		});
	});

	let graphEdges = $derived.by((): GEdge[] => {
		const nodeByCommit = new Map<string, GNode>();
		for (const n of graphNodes) nodeByCommit.set(n.exp.commit, n);
		const edges: GEdge[] = [];
		for (const n of graphNodes) {
			if (!n.exp.parent_commit) continue;
			const p = nodeByCommit.get(n.exp.parent_commit);
			if (!p || p.id === n.id) continue; // skip self-referencing baseline
			const dx = n.x - p.x;
			edges.push({
				fromId: p.id,
				toId: n.id,
				path: `M${p.x},${p.y} C${p.x + dx * 0.5},${p.y} ${n.x - dx * 0.5},${n.y} ${n.x},${n.y}`,
				kept: n.exp.status === 'keep',
			});
		}
		return edges;
	});

	// Lineage set for highlighting (uses lookup maps for O(n) instead of O(n^2))
	let lineageSet = $derived.by((): Set<number> => {
		const target = hoveredId ?? selectedId;
		if (target == null) return new Set();
		const idMap = new Map<number, Experiment>();
		for (const e of experiments) idMap.set(e.id, e);
		const set = new Set<number>();
		// Walk ancestors
		let cur = idMap.get(target);
		while (cur) {
			set.add(cur.id);
			cur = cur.parent_commit ? commitMap.get(cur.parent_commit) : undefined;
		}
		// Walk descendants
		const start = idMap.get(target);
		if (!start) return set;
		const queue = [start];
		while (queue.length) {
			const e = queue.shift()!;
			set.add(e.id);
			for (const child of (childrenMap.get(e.commit) || [])) {
				if (!set.has(child.id)) {
					set.add(child.id);
					queue.push(child);
				}
			}
		}
		return set;
	});

	let hasLineage = $derived(lineageSet.size > 0);

	// --- Auto-fit ---
	let didFit = false;
	$effect(() => {
		if (graphNodes.length > 0 && width > 0 && height > 0 && !didFit) {
			fitToView();
			didFit = true;
		}
	});
	$effect(() => {
		experiments;
		didFit = false;
	});

	// --- Focus on node (smooth pan) ---
	let animFrame: number | null = null;

	function smoothPanTo(targetTx: number, targetTy: number) {
		if (animFrame != null) cancelAnimationFrame(animFrame);
		const startTx = tx, startTy = ty;
		const start = performance.now();
		const duration = 180;

		function tick(now: number) {
			const t = Math.min((now - start) / duration, 1);
			const ease = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
			tx = startTx + (targetTx - startTx) * ease;
			ty = startTy + (targetTy - startTy) * ease;
			if (t < 1) {
				animFrame = requestAnimationFrame(tick);
			} else {
				animFrame = null;
			}
		}
		animFrame = requestAnimationFrame(tick);
	}

	$effect(() => {
		if (focusId == null) return;
		const node = graphNodes.find(n => n.id === focusId);
		if (!node || width === 0 || height === 0) return;
		selectedId = focusId;
		smoothPanTo(width / 2 - node.x * sc, height / 2 - node.y * sc);
	});

	function fitToView() {
		if (graphNodes.length === 0) return;
		const xs = graphNodes.map(n => n.x);
		const ys = graphNodes.map(n => n.y);
		const pad = 60;
		const minX = Math.min(...xs) - pad;
		const maxX = Math.max(...xs) + pad;
		const minY = Math.min(...ys) - pad;
		const maxY = Math.max(...ys) + pad;
		const cw = maxX - minX;
		const ch = maxY - minY;
		sc = Math.min(width / cw, height / ch, 2);
		tx = (width - cw * sc) / 2 - minX * sc;
		ty = (height - ch * sc) / 2 - minY * sc;
	}

	// --- Interaction handlers ---
	function onWheel(e: WheelEvent) {
		e.preventDefault();
		const factor = e.deltaY > 0 ? 0.9 : 1.1;
		const newSc = Math.max(0.1, Math.min(5, sc * factor));
		const rect = containerEl.getBoundingClientRect();
		const cx = e.clientX - rect.left;
		const cy = e.clientY - rect.top;
		tx = cx - (cx - tx) * (newSc / sc);
		ty = cy - (cy - ty) * (newSc / sc);
		sc = newSc;
	}

	function onPointerDown(e: PointerEvent) {
		if (e.button !== 0) return;
		if ((e.target as HTMLElement).closest('.graph-node')) return;
		isPanning = true;
		panOrigin = { x: e.clientX, y: e.clientY, tx, ty };
		containerEl.setPointerCapture(e.pointerId);
	}

	function onPointerMove(e: PointerEvent) {
		if (!isPanning) return;
		tx = panOrigin.tx + (e.clientX - panOrigin.x);
		ty = panOrigin.ty + (e.clientY - panOrigin.y);
	}

	function onPointerUp(e: PointerEvent) {
		if (isPanning) {
			isPanning = false;
			containerEl.releasePointerCapture(e.pointerId);
		}
	}

	function onBgClick() {
		selectedId = null;
		onSelect(null);
	}

	function onNodeClick(node: GNode, e: Event) {
		e.stopPropagation();
		selectedId = selectedId === node.id ? null : node.id;
		onSelect(selectedId != null ? node.exp : null);
	}

	function onNodeEnter(node: GNode) { hoveredId = node.id; }
	function onNodeLeave() { hoveredId = null; }

	// Tooltip
	let tooltipNode = $derived(graphNodes.find(n => n.id === hoveredId) ?? null);
	let tooltipX = $derived(tooltipNode ? tooltipNode.x * sc + tx : 0);
	let tooltipY = $derived(tooltipNode ? tooltipNode.y * sc + ty : 0);

	function fmtParam(key: string, val: string | number): string {
		if (typeof val === 'number') {
			if (key.endsWith('_lr')) return val.toPrecision(3);
			if (key.endsWith('_ratio')) return val.toFixed(2);
			return String(val);
		}
		return String(val);
	}
</script>

<div
	class="graph-wrap"
	bind:this={containerEl}
	onwheel={onWheel}
	onpointerdown={onPointerDown}
	onpointermove={onPointerMove}
	onpointerup={onPointerUp}
	role="application"
	aria-label="Experiment graph"
>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<svg {width} {height} class="graph-svg" onclick={onBgClick}>
		<g transform="translate({tx},{ty}) scale({sc})">
			<!-- Edges -->
			{#each graphEdges as edge (edge.fromId + '-' + edge.toId)}
				{@const inLineage = hasLineage && lineageSet.has(edge.fromId) && lineageSet.has(edge.toId)}
				<path
					d={edge.path}
					fill="none"
					stroke={edge.kept ? '#16A34A' : '#D1CEBF'}
					stroke-width={edge.kept ? 2.5 : 1.5}
					stroke-dasharray={edge.kept ? 'none' : '6,4'}
					opacity={hasLineage ? (inLineage ? 1 : 0.1) : 0.6}
					class="graph-edge"
				/>
			{/each}

			<!-- Nodes -->
			{#each graphNodes as node (node.id)}
				{@const inLineage = !hasLineage || lineageSet.has(node.id)}
				{@const isSelected = selectedId === node.id}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<g
					class="graph-node"
					class:crash={node.exp.status === 'crash'}
					transform="translate({node.x},{node.y})"
					opacity={inLineage ? 1 : 0.15}
					onclick={(e) => onNodeClick(node, e)}
					onpointerenter={() => onNodeEnter(node)}
					onpointerleave={onNodeLeave}
					role="button"
					tabindex="0"
				>
					{#if node.exp.status === 'keep'}
						<circle r={node.r + 3} fill={node.fill} opacity="0.15" />
					{/if}
					<circle
						r={node.r}
						fill={node.fill}
						stroke={node.stroke}
						stroke-width={node.exp.status === 'keep' ? 3 : 1.5}
					/>
					<text
						y="1"
						text-anchor="middle"
						dominant-baseline="central"
						class="node-label"
						fill={node.exp.status === 'keep' ? 'white' : '#57534E'}
						font-size={node.exp.status === 'keep' ? '11' : '9'}
						font-weight="700"
					>
						{node.id}
					</text>
					<text
						y={node.r + 14}
						text-anchor="middle"
						class="node-bpb"
						fill="#78716C"
						font-size="10"
					>
						{node.exp.val_bpb.toFixed(3)}
					</text>
				</g>
			{/each}
		</g>

		<!-- Axis hints -->
		<text x="12" y={height / 2} fill="#A8A29E" font-size="10" transform="rotate(-90, 12, {height / 2})" text-anchor="middle" class="axis-label">
			val_bpb (lower = better)
		</text>
		<text x={width / 2} y={height - 8} fill="#A8A29E" font-size="10" text-anchor="middle" class="axis-label">
			experiment
		</text>
	</svg>

	<!-- Hover tooltip -->
	{#if tooltipNode && hoveredId !== selectedId}
		<div class="tooltip" style="left: {tooltipX}px; top: {tooltipY - tooltipNode.r * sc - 12}px;">
			<div class="tt-header">
				<span class="tt-iter">#{tooltipNode.id}</span>
				<span class="tt-id">{tooltipNode.exp.commit}</span>
				<span class="tt-badge {tooltipNode.exp.status}">{tooltipNode.exp.status}</span>
			</div>
			<div class="tt-bpb">
				{tooltipNode.exp.val_bpb.toFixed(6)}
				{#if tooltipNode.exp.delta !== 0}
					<span class="tt-delta" class:good={tooltipNode.exp.delta < 0} class:bad={tooltipNode.exp.delta > 0}>
						{tooltipNode.exp.delta >= 0 ? '+' : ''}{tooltipNode.exp.delta.toFixed(4)}
					</span>
				{/if}
			</div>
			<div class="tt-desc">{tooltipNode.exp.description}</div>
			{#if tooltipNode.paramChanges.length > 0}
				<div class="tt-params">
					{#each tooltipNode.paramChanges as ch}
						<span class="tt-pill">{ch.key}: {fmtParam(ch.key, ch.from)} → {fmtParam(ch.key, ch.to)}</span>
					{/each}
				</div>
			{/if}
			{#if tooltipNode.exp.still_improving}
				<div class="tt-flag">still improving at end of budget</div>
			{/if}
		</div>
	{/if}

	<!-- Watermark -->
	<div class="watermark">
		<svg class="x-logo" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
		<span>@kylecompute</span>
		<span>@patrikkml</span>
		<span>@yimothysu</span>
	</div>

	<!-- Fit button -->
	<button class="fit-btn" onclick={fitToView} title="Fit to view">
		<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
			<path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/>
		</svg>
	</button>
</div>

<style>
	.graph-wrap {
		position: relative;
		width: 100%;
		height: 100%;
		overflow: hidden;
		cursor: grab;
		background:
			radial-gradient(circle at 50% 50%, transparent 0%, var(--bg) 100%),
			linear-gradient(var(--border) 1px, transparent 1px),
			linear-gradient(90deg, var(--border) 1px, transparent 1px);
		background-size: 100% 100%, 60px 60px, 60px 60px;
		background-position: 0 0, -1px -1px, -1px -1px;
		border-radius: var(--radius);
		border: 1px solid var(--border);
	}
	.graph-wrap:active { cursor: grabbing; }
	.graph-svg { display: block; }
	.graph-edge { pointer-events: none; transition: opacity 0.2s ease; }
	.graph-node { cursor: pointer; transition: opacity 0.2s ease; }
	.graph-node:hover circle { filter: brightness(1.1); }
	.graph-node.crash circle:first-of-type { animation: pulse 2s ease-in-out infinite; }
	@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
	.node-label, .node-bpb { font-family: var(--font-mono); pointer-events: none; user-select: none; }
	.axis-label { font-family: var(--font-body); pointer-events: none; user-select: none; letter-spacing: 0.03em; }

	/* Tooltip */
	.tooltip {
		position: absolute;
		transform: translate(-50%, -100%);
		background: #1C1917;
		color: #FAFAF9;
		border: 1px solid #44403C;
		border-radius: 8px;
		padding: 0.6rem 0.8rem;
		font-size: 0.78rem;
		pointer-events: none;
		z-index: 50;
		max-width: 340px;
		box-shadow: 0 8px 24px rgba(0,0,0,0.3);
	}
	.tt-header { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.25rem; }
	.tt-iter { font-family: var(--font-mono); font-weight: 700; font-size: 0.85rem; }
	.tt-id { font-family: var(--font-mono); font-size: 0.7rem; opacity: 0.5; }
	.tt-badge {
		font-size: 0.6rem; font-weight: 600; text-transform: uppercase;
		letter-spacing: 0.04em; padding: 0.1rem 0.35rem; border-radius: 4px; margin-left: auto;
	}
	.tt-badge.keep { background: rgba(22,163,74,0.2); color: #4ADE80; }
	.tt-badge.discard { background: rgba(220,38,38,0.2); color: #FCA5A5; }
	.tt-badge.crash { background: rgba(180,83,9,0.2); color: #FCD34D; }
	.tt-bpb { font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600; margin-bottom: 0.25rem; }
	.tt-delta { font-size: 0.72rem; font-weight: 500; margin-left: 0.35rem; }
	.tt-delta.good { color: #4ADE80; }
	.tt-delta.bad { color: #FCA5A5; }
	.tt-desc { font-size: 0.75rem; color: #D6D3D1; line-height: 1.35; white-space: normal; margin-bottom: 0.2rem; }
	.tt-params { display: flex; flex-wrap: wrap; gap: 0.25rem; margin-top: 0.25rem; }
	.tt-pill { font-family: var(--font-mono); font-size: 0.65rem; background: rgba(255,255,255,0.08); padding: 0.1rem 0.4rem; border-radius: 999px; color: #A8A29E; }
	.tt-flag { font-size: 0.68rem; color: #FCD34D; margin-top: 0.25rem; font-style: italic; }

	/* Watermark */
	.watermark {
		position: absolute; top: 12px; left: 12px; z-index: 10;
		display: flex; align-items: center; gap: 0.6rem;
		font-family: var(--font-mono); font-size: 0.72rem; font-weight: 500;
		color: var(--text-dim); opacity: 0.6;
		pointer-events: none; user-select: none;
	}
	.x-logo { flex-shrink: 0; }

	/* Fit button */
	.fit-btn {
		position: absolute; bottom: 12px; right: 12px;
		background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-sm);
		width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
		cursor: pointer; color: var(--text-dim); box-shadow: var(--shadow-sm);
		transition: all 0.15s ease; z-index: 10;
	}
	.fit-btn:hover { color: var(--text); border-color: var(--border-strong); box-shadow: var(--shadow-md); }
</style>
