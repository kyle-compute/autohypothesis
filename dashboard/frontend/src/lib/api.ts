import type { Experiment, KarpathyOriginal } from './types';

export async function fetchExperiments(): Promise<Experiment[]> {
	const res = await fetch('/api/experiments');
	if (!res.ok) return [];
	const raw: any[] = await res.json();
	return raw.map((r, i) => ({
		...r,
		experiment_id: r.id,
		id: r.ordinal ?? i + 1,
	}));
}

export async function fetchExperiment(experimentId: string): Promise<Experiment | null> {
	const res = await fetch(`/api/experiments/${experimentId}`);
	if (!res.ok) return null;
	return res.json();
}

export async function fetchDiff(experimentId: string): Promise<string> {
	const res = await fetch(`/api/experiments/${experimentId}/diff`);
	if (!res.ok) return '';
	const data = await res.json();
	return data.diff || '';
}

export async function fetchKarpathyOriginal(): Promise<KarpathyOriginal[]> {
	const res = await fetch('/api/karpathy-original');
	if (!res.ok) return [];
	return res.json();
}
