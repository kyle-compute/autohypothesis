export interface Experiment {
	id: number;
	commit: string;
	parent_commit: string;
	timestamp: string;
	status: 'keep' | 'discard' | 'crash';
	description: string;

	val_bpb: number;
	delta: number;

	train_bpb: number | null;
	bpb_at_checkpoints: number[];
	still_improving: boolean | null;

	num_steps: number;
	tokens_per_second: number | null;
	training_seconds: number;
	total_seconds: number;
	mfu_percent: number;
	total_tokens_M: number;

	peak_vram_gb: number;

	num_params_M: number;
	depth: number;

	diff_stat: string;
	diff_hash: string;
	diff_text: string;
}

export const HYPERPARAM_KEYS = ['depth'] as const;

export type HyperparamKey = (typeof HYPERPARAM_KEYS)[number];

export interface ParamChange {
	key: string;
	from: string | number;
	to: string | number;
}

export interface PlateauChild {
	exp: Experiment;
	paramChanges: ParamChange[];
}

export interface Plateau {
	parent: Experiment;
	children: PlateauChild[];
}
