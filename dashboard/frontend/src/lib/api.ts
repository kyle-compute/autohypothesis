import type { Experiment } from './types';

export async function fetchExperiments(): Promise<Experiment[]> {
	const res = await fetch('/api/experiments');
	if (!res.ok) return [];
	return res.json();
}

export async function fetchExperiment(id: number): Promise<Experiment | null> {
	const res = await fetch(`/api/experiments/${id}`);
	if (!res.ok) return null;
	return res.json();
}

export async function fetchDiff(id: number): Promise<string> {
	const res = await fetch(`/api/experiments/${id}/diff`);
	if (!res.ok) return '';
	const data = await res.json();
	return data.diff || '';
}
