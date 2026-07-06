import { useEffect, useState } from "react";
import type { JobStatusResponse } from "../types";
import styles from "./JobStatus.module.css";

interface Props {
  jobId: string;
  userEmail: string;
}

const POLL_MS = 30_000;

export default function JobStatus({ jobId, userEmail }: Props) {
  const [status, setStatus] = useState<JobStatusResponse["status"]>("pending");
  const [error, setError] = useState("");

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const res = await fetch(`/api/status/${jobId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: JobStatusResponse = await res.json();
        setStatus(data.status);
        if (data.status !== "done" && data.status !== "failed") {
          timer = setTimeout(poll, POLL_MS);
        }
      } catch (e) {
        setError("Could not fetch job status. Will retry.");
        timer = setTimeout(poll, POLL_MS);
      }
    }

    poll();
    return () => clearTimeout(timer);
  }, [jobId]);

  const icon =
    status === "done" ? "✓" :
    status === "failed" ? "✗" :
    "⏳";

  return (
    <div className={`${styles.card} ${styles[status]}`}>
      <span className={styles.icon}>{icon}</span>
      <div>
        <p className={styles.title}>
          {status === "pending" && "Job queued — waiting for Hcluster…"}
          {status === "running" && "Coverage job running on Hcluster…"}
          {status === "done" && `Report sent to ${userEmail}`}
          {status === "failed" && "Job failed. Check with your admin."}
        </p>
        <p className={styles.sub}>Job ID: {jobId}</p>
        {error && <p className={styles.error}>{error}</p>}
        {(status === "pending" || status === "running") && (
          <p className={styles.sub}>Checking every 30 seconds…</p>
        )}
      </div>
    </div>
  );
}
