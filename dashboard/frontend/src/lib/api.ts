import type { Experiment, KarpathyOriginal, DecisionMarkdown, ResearchBrief, TopExperiment, StrategyHitRate } from './types';

export async function fetchExperiments(): Promise<Experiment[]> {
	const res = await fetch('/data/experiments.json');
	if (!res.ok) return [];
	const raw: any[] = await res.json();
	return raw.map((r, i) => ({
		...r,
		experiment_id: r.id,
		id: r.ordinal ?? i + 1,
	}));
}

export async function fetchExperiment(experimentId: string): Promise<Experiment | null> {
	const res = await fetch('/data/experiments.json');
	if (!res.ok) return null;
	const all: any[] = await res.json();
	return all.find(r => r.id === experimentId) ?? null;
}

export async function fetchDiff(experimentId: string): Promise<string> {
	const res = await fetch(`/data/diff/${experimentId}.json`);
	if (!res.ok) return '';
	const data = await res.json();
	return data.diff || '';
}

export async function fetchDecisionMarkdown(experimentId: string): Promise<DecisionMarkdown | null> {
	const res = await fetch(`/data/decision-md/${experimentId}.json`);
	if (!res.ok) return null;
	return res.json();
}

export async function fetchResearchBrief(): Promise<ResearchBrief | null> {
	const res = await fetch('/data/brief.json');
	if (!res.ok) return null;
	return res.json();
}

export async function fetchTop(): Promise<TopExperiment[]> {
	const res = await fetch('/data/top.json');
	if (!res.ok) return [];
	return res.json();
}

export async function fetchStrategies(): Promise<StrategyHitRate[]> {
	const res = await fetch('/data/strategies.json');
	if (!res.ok) return [];
	return res.json();
}

export async function fetchRunDetail(experimentId: string): Promise<Record<string, any> | null> {
	const res = await fetch(`/data/runs/${experimentId}.json`);
	if (!res.ok) return null;
	return res.json();
}

export interface ConfigDiff {
	has_diff: boolean;
	reason?: string;
	parent_id?: string;
	child_id?: string;
	changes?: { key: string; old: any; new: any }[];
}

export async function fetchConfigDiff(experimentId: string): Promise<ConfigDiff | null> {
	const res = await fetch(`/data/config-diff/${experimentId}.json`);
	if (!res.ok) return null;
	return res.json();
}

export interface LineageEdge {
	from: string;
	to: string;
	type: 'explicit' | 'inferred';
}

export async function fetchLineage(): Promise<LineageEdge[]> {
	const res = await fetch('/data/lineage.json');
	if (!res.ok) return [];
	return res.json();
}

export async function fetchKarpathyOriginal(): Promise<KarpathyOriginal[]> {
	const res = await fetch('/data/karpathy-original.json');
	if (!res.ok) return [];
	return res.json();
}
