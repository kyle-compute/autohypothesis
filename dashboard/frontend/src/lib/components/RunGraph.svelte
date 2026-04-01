<script lang="ts">
	import type { Experiment, ParamChange } from '$lib/types';
	import { HYPERPARAM_KEYS } from '$lib/types';
	import type { LineageEdge } from '$lib/api';

	let { experiments = [], lineageEdges = [], onSelect = (_e: Experiment | null) => {}, focusId = null as string | null }: {
		experiments: Experiment[];
		lineageEdges?: LineageEdge[];
		onSelect?: (e: Experiment | null) => void;
		focusId?: string | null;
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
	let selectedId: string | null = $state(null);
	let hoveredId: string | null = $state(null);

	// --- Constants ---
	const PAD = 80;
	const R_KEEP = 36;
	const R_DISCARD = 26;
	const R_CRASH = 20;

	function shortLabel(id: string): string {
		const m = id.match(/^exp-(\d+)/);
		return m ? m[1].replace(/^0+/, '') || '0' : id.slice(0, 6);
	}

	// --- Graph data ---
	interface GNode {
		id: string;
		exp: Experiment;
		x: number;
		y: number;
		r: number;
		fill: string;
		stroke: string;
		paramChanges: ParamChange[];
	}

	interface GEdge {
		fromId: string;
		toId: string;
		path: string;
		kept: boolean;
		inferred: boolean;
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

		const count = experiments.length;
		const maxIndex = count - 1 || 1;

		const gw = Math.max(width * 1.2, count * 120);
		const gh = Math.max(height * 0.9, 500);

		return experiments.map((exp, index) => {
			const x = PAD + (index / maxIndex) * (gw - PAD * 2);
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
				id: exp.experiment_id,
				exp,
				x, y, r,
				fill: isKeep ? '#16A34A' : isCrash ? '#B45309' : 'rgba(220,38,38,0.12)',
				stroke: isKeep ? '#16A34A' : isCrash ? '#B45309' : 'rgba(220,38,38,0.45)',
				paramChanges,
			};
		});
	});

	let graphEdges = $derived.by((): GEdge[] => {
		const nodeById = new Map<string, GNode>();
		for (const n of graphNodes) {
			nodeById.set(n.id, n);
		}
		if (lineageEdges.length > 0) {
			return lineageEdges
				.filter(e => nodeById.has(e.from) && nodeById.has(e.to))
				.map(e => {
					const p = nodeById.get(e.from)!;
					const n = nodeById.get(e.to)!;
					const dx = n.x - p.x;
					const dy = n.y - p.y;
					return {
						fromId: p.id,
						toId: n.id,
						path: `M${p.x},${p.y} C${p.x + dx * 0.4},${p.y + dy * 0.1} ${n.x - dx * 0.4},${n.y - dy * 0.1} ${n.x},${n.y}`,
						kept: p.exp.status === 'keep' && n.exp.status === 'keep',
						inferred: e.type === 'inferred',
					};
				});
		}
		// Fallback: infer edges from parent_commit
		const nodeByCommit = new Map<string, GNode>();
		for (const n of graphNodes) nodeByCommit.set(n.exp.commit, n);
		const edges: GEdge[] = [];
		for (const n of graphNodes) {
			if (!n.exp.parent_commit) continue;
			const p = nodeByCommit.get(n.exp.parent_commit);
			if (!p || p.id === n.id) continue;
			const dx = n.x - p.x;
			edges.push({
				fromId: p.id,
				toId: n.id,
				path: `M${p.x},${p.y} C${p.x + dx * 0.5},${p.y} ${n.x - dx * 0.5},${n.y} ${n.x},${n.y}`,
				kept: n.exp.status === 'keep',
				inferred: false,
			});
		}
		return edges;
	});

	// Lineage set for highlighting — walk lineageEdges bidirectionally
	let lineageSet = $derived.by((): Set<string> => {
		const target = hoveredId ?? selectedId;
		if (target == null) return new Set();

		// Build adjacency from lineageEdges
		const children = new Map<string, string[]>();
		const parents = new Map<string, string[]>();
		for (const e of lineageEdges) {
			if (!children.has(e.from)) children.set(e.from, []);
			children.get(e.from)!.push(e.to);
			if (!parents.has(e.to)) parents.set(e.to, []);
			parents.get(e.to)!.push(e.from);
		}

		const set = new Set<string>();
		// Walk ancestors
		const aQueue = [target];
		while (aQueue.length) {
			const id = aQueue.shift()!;
			if (set.has(id)) continue;
			set.add(id);
			for (const p of parents.get(id) ?? []) aQueue.push(p);
		}
		// Walk descendants
		const dQueue = [target];
		while (dQueue.length) {
			const id = dQueue.shift()!;
			if (set.has(id) && id !== target) continue;
			set.add(id);
			for (const c of children.get(id) ?? []) {
				if (!set.has(c)) dQueue.push(c);
			}
		}
		return set;
	});

	let hasLineage = $derived(lineageSet.size > 0);

	// --- Auto-fit ---
	let didFit = false;
	$effect(() => {
		if (graphNodes.length > 0 && width > 0 && height > 0 && !didFit) {
			fitToView(1.5);
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

	function fitToView(zoom: number = 1) {
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
		sc = Math.min(width / cw, height / ch, 2) * zoom;
		const cx = (minX + maxX) / 2;
		const cy = (minY + maxY) / 2;
		tx = width / 2 - cx * sc;
		ty = height / 2 - cy * sc;
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
		if ((e.target as HTMLElement).closest('.graph-node, .watermark a')) return;
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
					stroke={edge.kept ? '#16A34A' : edge.inferred ? 'rgba(148,163,184,0.25)' : '#D1CEBF'}
					stroke-width={edge.kept ? 2.5 : edge.inferred ? 1 : 1.5}
					stroke-dasharray={edge.kept ? 'none' : edge.inferred ? '4,6' : '6,4'}
					opacity={hasLineage ? (inLineage ? 1 : 0.08) : edge.kept ? 0.8 : edge.inferred ? 0.3 : 0.6}
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
						fill={node.exp.status === 'keep' ? 'white' : '#A8A29E'}
						font-size={node.exp.status === 'keep' ? '14' : '11'}
						font-weight="700"
					>
						{shortLabel(node.exp.experiment_id)}
					</text>
					<text
						y={node.r + 16}
						text-anchor="middle"
						class="node-bpb"
						fill="#78716C"
						font-size="11"
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
				<span class="tt-iter">{tooltipNode.exp.experiment_id}</span>
				<span class="tt-badge {tooltipNode.exp.status}">{tooltipNode.exp.status}</span>
			</div>
			<div class="tt-commit">{tooltipNode.exp.commit.slice(0, 7)}</div>
			<div class="tt-bpb">
				{tooltipNode.exp.val_bpb.toFixed(6)}
				{#if tooltipNode.exp.delta !== 0}
					<span class="tt-delta" class:good={tooltipNode.exp.delta < 0} class:bad={tooltipNode.exp.delta > 0}>
						{tooltipNode.exp.delta >= 0 ? '+' : ''}{tooltipNode.exp.delta.toFixed(4)}
					</span>
				{/if}
			</div>
			{#if tooltipNode.exp.description}
				<div class="tt-desc">{tooltipNode.exp.description}</div>
			{/if}
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
		<a href="https://x.com/kylecompute" target="_blank" rel="noopener">@kylecompute</a>
		<a href="https://x.com/patrikkml" target="_blank" rel="noopener">@patrikkml</a>
		<a href="https://x.com/yimothysu" target="_blank" rel="noopener">@yimothysu</a>
	</div>

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
		max-width: 280px;
		box-shadow: 0 8px 24px rgba(0,0,0,0.3);
	}
	.tt-header { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.1rem; }
	.tt-iter { font-family: var(--font-mono); font-weight: 700; font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.tt-commit { font-family: var(--font-mono); font-size: 0.65rem; opacity: 0.4; margin-bottom: 0.25rem; }
	.tt-badge {
		font-size: 0.6rem; font-weight: 600; text-transform: uppercase;
		letter-spacing: 0.04em; padding: 0.1rem 0.35rem; border-radius: 4px; margin-left: auto; flex-shrink: 0;
	}
	.tt-badge.keep { background: rgba(22,163,74,0.2); color: #4ADE80; }
	.tt-badge.discard { background: rgba(220,38,38,0.2); color: #FCA5A5; }
	.tt-badge.crash { background: rgba(180,83,9,0.2); color: #FCD34D; }
	.tt-badge.replicate { background: rgba(96,165,250,0.2); color: #93C5FD; }
	.tt-bpb { font-family: var(--font-mono); font-size: 0.82rem; font-weight: 600; margin-bottom: 0.25rem; }
	.tt-delta { font-size: 0.72rem; font-weight: 500; margin-left: 0.35rem; }
	.tt-delta.good { color: #4ADE80; }
	.tt-delta.bad { color: #FCA5A5; }
	.tt-desc { font-size: 0.72rem; color: #D6D3D1; line-height: 1.35; white-space: normal; margin-bottom: 0.2rem; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
	.tt-params { display: flex; flex-wrap: wrap; gap: 0.25rem; margin-top: 0.25rem; }
	.tt-pill { font-family: var(--font-mono); font-size: 0.65rem; background: rgba(255,255,255,0.08); padding: 0.1rem 0.4rem; border-radius: 999px; color: #A8A29E; }
	.tt-flag { font-size: 0.68rem; color: #FCD34D; margin-top: 0.25rem; font-style: italic; }

	/* Watermark */
	.watermark {
		position: absolute; top: 12px; left: 12px; z-index: 10;
		display: flex; align-items: center; gap: 0.35rem;
		font-family: var(--font-mono); font-size: 0.72rem; font-weight: 500;
		color: var(--text-dim); opacity: 0.6;
		pointer-events: none;
	}
	.watermark a {
		color: var(--text-dim); text-decoration: none; transition: color 0.15s ease;
		pointer-events: auto;
	}
	.watermark a:hover { color: var(--text); opacity: 1; }
	.x-logo { flex-shrink: 0; }

</style>
