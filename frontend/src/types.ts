export interface CoverageRow {
  gene: string;
  n_samples: number;
  min_mean_cov: number;
  max_mean_cov: number;
  mean_mean_cov: number;
  min_pct_nx: number;
  mean_pct_nx: number;
  threshold: number;
}

export interface QueryResponse {
  cache_hits: CoverageRow[];
  job_id: string | null;
  unresolvable: string[];
}

export interface JobStatusResponse {
  job_id: string;
  status: "pending" | "running" | "done" | "failed";
  created_at: string;
  completed_at: string | null;
}
