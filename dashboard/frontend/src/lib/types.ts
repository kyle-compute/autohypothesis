export interface Experiment {
	id: number;
	experiment_id: string;
	commit: string;
	parent_commit: string;
	timestamp: string;
	status: 'keep' | 'discard' | 'crash' | 'replicate';
	description: string;

	val_bpb: number;
	delta: number;

	train_bpb: number | null;
	bpb_at_checkpoints: number[];
	still_improving: boolean | null;
	improvement_rate: number | null;

	num_steps: number;
	tokens_per_second: number | null;
	training_seconds: number;
	total_seconds: number;
	mfu_percent: number;
	total_tokens_M: number;

	peak_vram_gb: number;

	num_params_M: number;
	depth: number;
	ordinal: number | null;

	execution_status: string;
	decision_status: string;

	diff_stat: string;
	diff_hash: string;
	diff_text: string;

	decision_markdown_path: string;
	decision_markdown: string;

	worker_id: string;
	gpu_id: string;
	gpu_name: string;
	hypothesis_id: string;
	rationale: string;
	outcome: string;
	notes: string | Record<string, unknown>;

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

export const HYPERPARAM_KEYS = [
	'depth',
	'model_dim',
	'n_heads',
	'head_dim',
	'window_pattern',
	'total_batch_size',
	'device_batch_size',
	'matrix_lr',
	'embedding_lr',
	'weight_decay',
	'warmdown_ratio',
] as const;

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

export interface DecisionMarkdown {
	exists: boolean;
	path: string;
	content: string;
	commit: string;
	run_id?: string;
}

export interface ResearchBrief {
	objective: string;
	constraints: string[];
	current_config: Record<string, any>;
	best_result: {
		commit: string;
		val_bpb: number;
		memory_gb: number;
		status: string;
		description: string;
	};
}

export interface TopExperiment {
	id: string;
	val_bpb: number;
	delta: number;
	description: string;
	status: string;
	commit: string;
	hypothesis_title: string;
	hypothesis_rationale: string;
	prediction: string;
	changes_from_baseline: Record<string, any>;
	num_steps: number;
	training_seconds: number;
	mfu_percent: number;
	peak_vram_gb: number;
}

export interface StrategyHitRate {
	param: string;
	kept: number;
	discarded: number;
	crashed: number;
	total: number;
	keep_rate: number;
}
