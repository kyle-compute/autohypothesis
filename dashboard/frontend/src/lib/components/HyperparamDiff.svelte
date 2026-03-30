<script lang="ts">
	type HP = Record<string, string | number | number[]>;

	let { params = {} as HP, parentParams = null as HP | null }: {
		params: HP;
		parentParams: HP | null;
	} = $props();

	const DISPLAY_ORDER = [
		'DEPTH', 'ASPECT_RATIO', 'HEAD_DIM', 'TOTAL_BATCH_SIZE', 'DEVICE_BATCH_SIZE',
		'WINDOW_PATTERN', 'MATRIX_LR', 'EMBEDDING_LR', 'UNEMBEDDING_LR', 'SCALAR_LR',
		'WEIGHT_DECAY', 'WARMDOWN_RATIO', 'WARMUP_RATIO', 'FINAL_LR_FRAC',
		'init_scale', 'x0_lambdas_init', 'rotary_base', 'short_window_divisor',
		'lm_head_weight_decay', 'embedding_weight_decay', 'value_embeds_weight_decay',
		'muon_momentum_warmup_steps',
	];

	interface Change {
		key: string;
		from: string | number | number[];
		to: string | number | number[];
	}

	let changes = $derived.by((): Change[] => {
		if (!parentParams || Object.keys(parentParams).length === 0) return [];
		const result: Change[] = [];
		const allKeys = new Set([...Object.keys(params), ...Object.keys(parentParams)]);
		for (const key of allKeys) {
			const pv = parentParams[key];
			const cv = params[key];
			if (pv != null && cv != null && JSON.stringify(pv) !== JSON.stringify(cv)) {
				result.push({ key, from: pv, to: cv });
			}
		}
		return result.sort((a, b) => {
			const ai = DISPLAY_ORDER.indexOf(a.key);
			const bi = DISPLAY_ORDER.indexOf(b.key);
			return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
		});
	});

	let hasParams = $derived(Object.keys(params).length > 0);

	let sortedParams = $derived.by(() => {
		const entries = Object.entries(params);
		return entries.sort((a, b) => {
			const ai = DISPLAY_ORDER.indexOf(a[0]);
			const bi = DISPLAY_ORDER.indexOf(b[0]);
			return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
		});
	});

	function fmtVal(val: string | number | number[]): string {
		if (Array.isArray(val)) return `[${val.join(', ')}]`;
		if (typeof val === 'number') {
			if (val >= 1000) return val.toLocaleString();
			if (val < 0.01 && val > 0) return val.toExponential(2);
			if (Number.isInteger(val)) return String(val);
			return val.toPrecision(4);
		}
		return String(val);
	}
</script>

{#if changes.length > 0}
	<!-- Diff view: show what changed -->
	<div class="diff-table">
		{#each changes as ch}
			<div class="diff-row">
				<span class="diff-key">{ch.key}</span>
				<span class="diff-from">{fmtVal(ch.from)}</span>
				<span class="diff-arrow">→</span>
				<span class="diff-to">{fmtVal(ch.to)}</span>
			</div>
		{/each}
	</div>
{:else if hasParams}
	<!-- No parent to diff against: show current params as pills -->
	<div class="param-pills">
		{#each sortedParams as [key, val]}
			<span class="param-pill">
				<span class="pill-key">{key}</span>
				<span class="pill-val">{fmtVal(val)}</span>
			</span>
		{/each}
	</div>
{/if}

<style>
	.diff-table { display: flex; flex-direction: column; gap: 0.2rem; }
	.diff-row {
		display: grid; grid-template-columns: 1fr auto auto auto;
		gap: 0.4rem; align-items: center;
		padding: 0.3rem 0.5rem;
		background: var(--bg-subtle); border-radius: var(--radius-sm);
		font-family: var(--font-mono); font-size: 0.75rem;
	}
	.diff-row:nth-child(odd) { background: var(--bg-hover); }
	.diff-key { color: var(--text-secondary); font-weight: 500; }
	.diff-from { color: var(--text-dim); text-decoration: line-through; opacity: 0.7; text-align: right; }
	.diff-arrow { color: var(--text-dim); font-size: 0.65rem; }
	.diff-to { color: var(--accent); font-weight: 600; text-align: right; }

	.param-pills { display: flex; flex-wrap: wrap; gap: 0.3rem; }
	.param-pill {
		display: inline-flex; align-items: center; gap: 0.25rem;
		padding: 0.2rem 0.5rem;
		background: var(--bg-subtle); border: 1px solid var(--border);
		border-radius: 999px;
		font-family: var(--font-mono); font-size: 0.68rem;
	}
	.pill-key { color: var(--text-dim); font-weight: 500; }
	.pill-val { color: var(--text); font-weight: 600; }
</style>
