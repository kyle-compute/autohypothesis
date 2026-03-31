<script>
	import '../app.css';
	let { children } = $props();
</script>

<nav>
	<div class="nav-inner">
		<a href="/" class="logo">
			<span class="logo-mark">ar</span>
			<span class="logo-text">autoresearch</span>
		</a>
		<div class="nav-links">
			<a href="/" class="nav-link">
				<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="8" cy="8" r="3"/>
					<path d="M8 1v2M8 13v2M1 8h2M13 8h2"/>
				</svg>
				Live
			</a>
			<a href="/history" class="nav-link">
				<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="3" cy="12" r="2"/><circle cx="8" cy="4" r="2"/><circle cx="13" cy="10" r="2"/><line x1="5" y1="10.5" x2="6.5" y2="5.5"/><line x1="9.5" y1="5.5" x2="11.5" y2="8.5"/>
				</svg>
				Decisions
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
</style>
