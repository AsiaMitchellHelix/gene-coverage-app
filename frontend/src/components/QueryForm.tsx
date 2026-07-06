import React, { useState } from "react";
import styles from "./QueryForm.module.css";

interface Props {
  onSubmit: (identifiers: string[], email: string) => void;
  loading: boolean;
}

export default function QueryForm({ onSubmit, loading }: Props) {
  const [text, setText] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const identifiers = text
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (identifiers.length === 0) {
      setError("Enter at least one gene, rsID, or coordinate.");
      return;
    }
    if (!email) {
      setError("Email is required to receive the report.");
      return;
    }
    setError("");
    onSubmit(identifiers, email);
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <label className={styles.label}>
        Genes, rsIDs, or genomic coordinates
        <span className={styles.hint}>
          One per line, or comma-separated. e.g. BRCA1, rs429358, chr19:44908684-44908822
        </span>
      </label>
      <textarea
        className={styles.textarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={8}
        placeholder={"BRCA1\nrs429358\nchr19:44908684-44908822"}
        disabled={loading}
      />

      <label className={styles.label}>
        Email address
        <span className={styles.hint}>
          Results for novel queries will be emailed when the compute job completes.
        </span>
      </label>
      <input
        className={styles.input}
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        disabled={loading}
      />

      {error && <p className={styles.error}>{error}</p>}

      <button className={styles.button} type="submit" disabled={loading}>
        {loading ? "Running…" : "Get Coverage Stats"}
      </button>
    </form>
  );
}
