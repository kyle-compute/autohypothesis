import type { Experiment } from './types';

/**
 * Connect to the SSE stream. Calls onExperiment whenever
 * a new ExperimentRecord is appended to experiments.jsonl.
 * Returns a cleanup function.
 */
export function connectSSE(onExperiment: (exp: Experiment) => void): () => void {
	const es = new EventSource('/stream');
	es.onmessage = (e) => {
		try {
			const event = JSON.parse(e.data);
			if (event.type === 'new_experiment') {
				const { type, ...record } = event;
				onExperiment(record as Experiment);
			}
		} catch {
			// ignore malformed events
		}
	};
	return () => es.close();
}
