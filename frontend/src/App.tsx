import { useState } from "react";
import JobStatus from "./components/JobStatus";
import QueryForm from "./components/QueryForm";
import ResultsTable from "./components/ResultsTable";
import type { CoverageRow, QueryResponse } from "./types";
import styles from "./App.module.css";

export default function App() {
  const [loading, setLoading] = useState(false);
  const [cacheHits, setCacheHits] = useState<CoverageRow[]>([]);
  const [unresolvable, setUnresolvable] = useState<string[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState("");
  const [apiError, setApiError] = useState("");

  async function handleSubmit(identifiers: string[], email: string) {
    setLoading(true);
    setApiError("");
    setCacheHits([]);
    setUnresolvable([]);
    setJobId(null);
    setUserEmail(email);

    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifiers, email }),
      });

      if (res.status === 401) {
        window.location.href = "/saml/login";
        return;
      }

      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }

      const data: QueryResponse = await res.json();
      setCacheHits(data.cache_hits);
      setUnresolvable(data.unresolvable);
      setJobId(data.job_id);
    } catch (e) {
      setApiError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Gene Coverage Statistics</h1>
        <p className={styles.subtitle}>
          Query per-gene coverage metrics across the cohort. Enter gene names,
          rsIDs, or genomic coordinates (e.g. <code>chr19:44908684-44908822</code>).
        </p>
      </header>

      <main className={styles.main}>
        <section className={styles.card}>
          <QueryForm onSubmit={handleSubmit} loading={loading} />
          {apiError && <p className={styles.apiError}>{apiError}</p>}
        </section>

        {(cacheHits.length > 0 || unresolvable.length > 0) && (
          <section className={styles.card}>
            <ResultsTable rows={cacheHits} unresolvable={unresolvable} />
          </section>
        )}

        {jobId && (
          <section className={styles.card}>
            <h2 className={styles.sectionHeading}>Compute Job</h2>
            <p className={styles.jobNote}>
              {cacheHits.length > 0
                ? "Some identifiers were not in the pre-computed database."
                : "None of the identifiers matched pre-computed data."}{" "}
              A coverage job has been submitted to Hcluster. You'll receive an
              email at <strong>{userEmail}</strong> when results are ready.
            </p>
            <JobStatus jobId={jobId} userEmail={userEmail} />
          </section>
        )}
      </main>
    </div>
  );
}
