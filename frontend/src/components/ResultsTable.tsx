import type { CoverageRow } from "../types";
import styles from "./ResultsTable.module.css";

interface Props {
  rows: CoverageRow[];
  unresolvable: string[];
}

export default function ResultsTable({ rows, unresolvable }: Props) {
  if (rows.length === 0 && unresolvable.length === 0) return null;

  const threshold = rows[0]?.threshold ?? 20;

  return (
    <div className={styles.container}>
      {rows.length > 0 && (
        <>
          <h2 className={styles.heading}>
            Coverage Results
            <span className={styles.badge}>{rows.length} gene{rows.length !== 1 ? "s" : ""}</span>
          </h2>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Gene</th>
                  <th>Samples</th>
                  <th>Min Mean Cov</th>
                  <th>Max Mean Cov</th>
                  <th>Mean Mean Cov</th>
                  <th>Min % ≥{threshold}x</th>
                  <th>Mean % ≥{threshold}x</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.gene}>
                    <td className={styles.gene}>{row.gene}</td>
                    <td>{row.n_samples}</td>
                    <td>{row.min_mean_cov.toFixed(2)}</td>
                    <td>{row.max_mean_cov.toFixed(2)}</td>
                    <td>{row.mean_mean_cov.toFixed(2)}</td>
                    <td>
                      <PctCell value={row.min_pct_nx} />
                    </td>
                    <td>
                      <PctCell value={row.mean_pct_nx} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {unresolvable.length > 0 && (
        <div className={styles.warn}>
          <strong>Could not resolve:</strong>{" "}
          {unresolvable.join(", ")}
        </div>
      )}
    </div>
  );
}

function PctCell({ value }: { value: number }) {
  const color =
    value >= 90 ? "#276749" : value >= 70 ? "#744210" : "#742a2a";
  const bg =
    value >= 90 ? "#f0fff4" : value >= 70 ? "#fffff0" : "#fff5f5";
  return (
    <span style={{ color, background: bg, padding: "2px 6px", borderRadius: 4, fontWeight: 600 }}>
      {value.toFixed(1)}%
    </span>
  );
}
