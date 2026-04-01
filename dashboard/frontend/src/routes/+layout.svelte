<script>
	import '../app.css';
	let { children } = $props();
</script>

<nav>
	<div class="nav-inner">
		<a href="/" class="logo">
			<span class="logo-mark">ah</span>
			<span class="logo-text">autohypothesis</span>
		</a>
		<div class="nav-links">
			<a href="/" class="nav-link">
				<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="8" cy="8" r="6"/><polyline points="8,4 8,8 11,10"/>
				</svg>
				History
			</a>
			<a href="/tree" class="nav-link">
				<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="8" cy="3" r="2"/><circle cx="4" cy="12" r="2"/><circle cx="12" cy="12" r="2"/>
					<line x1="8" y1="5" x2="4" y2="10"/><line x1="8" y1="5" x2="12" y2="10"/>
				</svg>
				Tree
			</a>
			<a href="https://github.com/kyle-compute/autohypothesis/tree/main" target="_blank" rel="noopener noreferrer" class="nav-link">
				<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
					<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
				</svg>
				GitHub
			</a>
		</div>
	</div>
</nav>

<main>
	{@render children()}
</main>

<style>
	nav {
		background: var(--bg-card);
		border-bottom: 1px solid var(--border);
		position: sticky;
		top: 0;
		z-index: 100;
		box-shadow: var(--shadow-sm);
	}
	.nav-inner {
		max-width: 1400px;
		margin: 0 auto;
		padding: 0 2rem;
		height: 56px;
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.logo {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--text);
	}
	.logo:hover { text-decoration: none; }
	.logo-mark {
		font-family: var(--font-mono);
		font-weight: 600;
		font-size: 0.8rem;
		letter-spacing: -0.02em;
		background: var(--accent);
		color: white;
		width: 28px;
		height: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 7px;
	}
	.logo-text {
		font-family: var(--font-mono);
		font-weight: 500;
		font-size: 0.9rem;
		letter-spacing: -0.01em;
		color: var(--text);
	}
	.nav-links {
		display: flex;
		gap: 0.25rem;
	}
	.nav-link {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--text-secondary);
		font-size: 0.85rem;
		font-weight: 500;
		padding: 0.4rem 0.75rem;
		border-radius: var(--radius-sm);
		transition: all 0.15s ease;
	}
	.nav-link:hover {
		color: var(--text);
		background: var(--bg-hover);
		text-decoration: none;
	}
	main {
		max-width: 1400px;
		margin: 0 auto;
		padding: 1.5rem 2rem 3rem;
	}

	@media (max-width: 768px) {
		.nav-inner { padding: 0 1rem; height: 48px; }
		.logo-text { display: none; }
		.nav-link { padding: 0.35rem 0.5rem; font-size: 0.8rem; }
		main { padding: 0.75rem 0.75rem 2rem; }
	}
</style>
