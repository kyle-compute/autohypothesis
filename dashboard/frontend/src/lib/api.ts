import type { Experiment, DecisionMarkdown, ResearchBrief, TopExperiment, StrategyHitRate } from './types';

export async function fetchExperiments(): Promise<Experiment[]> {
	const res = await fetch('/api/experiments');
	if (!res.ok) return [];
	return res.json();
}

export async function fetchExperiment(id: string): Promise<Experiment | null> {
	const res = await fetch(`/api/experiments/${id}`);
	if (!res.ok) return null;
	return res.json();
}

export async function fetchDiff(id: string): Promise<string> {
	const res = await fetch(`/api/experiments/${id}/diff`);
	if (!res.ok) return '';
	const data = await res.json();
	return data.diff || '';
}

export async function fetchDecisionMarkdown(id: string): Promise<DecisionMarkdown | null> {
	const res = await fetch(`/api/experiments/${id}/decision-md`);
	if (!res.ok) return null;
	return res.json();
}

export async function fetchResearchBrief(): Promise<ResearchBrief | null> {
	const res = await fetch('/api/research/brief');
	if (!res.ok) return null;
	return res.json();
}

export async function fetchTop(): Promise<TopExperiment[]> {
	const res = await fetch('/api/research/top');
	if (!res.ok) return [];
	return res.json();
}

export async function fetchStrategies(): Promise<StrategyHitRate[]> {
	const res = await fetch('/api/research/strategies');
	if (!res.ok) return [];
	return res.json();
}

export async function fetchRunDetail(id: string): Promise<Record<string, any> | null> {
	const res = await fetch(`/api/research/run/${id}`);
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

export async function fetchConfigDiff(id: string): Promise<ConfigDiff | null> {
	const res = await fetch(`/api/research/config-diff/${id}`);
	if (!res.ok) return null;
	return res.json();
}

export interface LineageEdge {
	from: string;
	to: string;
	type: 'explicit' | 'inferred';
}

export async function fetchLineage(): Promise<LineageEdge[]> {
	const res = await fetch('/api/research/lineage');
	if (!res.ok) return [];
	return res.json();
}
