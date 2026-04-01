<script lang="ts">
	import { html } from 'diff2html';
	import 'diff2html/bundles/css/diff2html.min.css';

	let { diff = '' }: { diff: string } = $props();

	let rendered = $derived(
		diff
			? html(diff, {
					drawFileList: false,
					matching: 'lines',
					outputFormat: 'side-by-side'
				})
			: '<p class="no-diff">No diff available</p>'
	);
</script>

<div class="diff-wrap">
	{@html rendered}
</div>

<style>
	.diff-wrap {
		overflow-x: auto;
		font-size: 0.78rem;
		font-family: var(--font-mono);
		background: var(--bg-subtle);
		border-radius: var(--radius-sm);
		border: 1px solid var(--border);
	}
	.diff-wrap :global(.d2h-wrapper) {
		background: transparent;
	}
	.diff-wrap :global(.d2h-file-header) {
		background: var(--bg-hover);
		border-color: var(--border);
		font-family: var(--font-mono);
	}
	.diff-wrap :global(.d2h-code-line) {
		color: var(--text);
		font-family: var(--font-mono);
	}
	.diff-wrap :global(.d2h-code-side-line) {
		font-family: var(--font-mono);
	}
	.diff-wrap :global(.no-diff) {
		padding: 1rem;
		color: var(--text-dim);
		font-family: var(--font-body);
	}
</style>
