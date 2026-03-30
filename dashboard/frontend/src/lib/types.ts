export interface Experiment {
	id: number;
	experiment_id: string;
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
	improvement_rate: number;

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

	// Rich context fields
	decision_markdown: string;
	rationale: string;
	notes: string | Record<string, unknown>;
	hypothesis_id: string;
	gpu_name: string;
	worker_id: string;
	execution_status: string;

	// Config fields (may be 0 if not explicitly set)
	model_dim: number;
	n_heads: number;
	head_dim: number;
	window_pattern: string;
	total_batch_size: number;
	device_batch_size: number;
	matrix_lr: number;
	embedding_lr: number;
	weight_decay: number;
	warmdown_ratio: number;
	adam_betas: number[];

	// Hyperparameters from metadata.json (rich config)
	hyperparameters: Record<string, string | number | number[]>;
}

export interface KarpathyComparison {
	experiment: string;
	karpathy_bpb: number;
	our_bpb: number;
	delta: string;
}

export interface KarpathyOriginal {
	commit: string;
	val_bpb: number;
	memory_gb: number;
	status: string;
	description: string;
	best_so_far: number;
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
