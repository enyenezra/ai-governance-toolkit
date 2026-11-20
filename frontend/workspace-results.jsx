import { createRoot } from "react-dom/client";

const roots = new WeakMap();

// The controller provides data while React owns the contents of each result slot.
function render(container, content) {
  if (!roots.has(container)) roots.set(container, createRoot(container));
  roots.get(container).render(content);
}

export function releaseResult(container) {
  const root = roots.get(container);
  if (!root) return;
  root.unmount();
  roots.delete(container);
}

function ResultsTable({ columns, rows, empty }) {
  if (rows.length === 0) return <p>{empty}</p>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>{columns.map((title) => <th key={title} scope="col">{title}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((value, index) => <td key={columns[index]}>{String(value ?? "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Findings({ items }) {
  return <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul>;
}

function RiskResult({ report }) {
  if (!report) return <p>No saved assessments yet.</p>;
  const { assessment } = report;
  return (
    <>
      <p>{report.risk_score} / 100 · {assessment.risk} risk</p>
      <p>{assessment.disposition === "deny" ? "Deny in simulation" : "Consider after human review"}</p>
      <h3>Findings</h3>
      <Findings items={assessment.reasons} />
      <h3>Recommended controls</h3>
      <Findings items={assessment.controls} />
    </>
  );
}

function ReadinessResult({ result }) {
  if (!result) return <p>No readiness assessments yet.</p>;
  return (
    <>
      <p>{result.score} / 100 · scoring {result.scoring_version}</p>
      {result.gaps.length > 0 ? (
        <Findings items={result.gaps.map((gap) => gap.task)} />
      ) : (
        <p>No gaps were reported.</p>
      )}
    </>
  );
}

export function renderTable(container, columns, rows, empty) {
  render(container, <ResultsTable columns={columns} rows={rows} empty={empty} />);
}

export function renderRiskResult(container, report) {
  render(container, <RiskResult report={report} />);
}

export function renderReadinessResult(container, result) {
  render(container, <ReadinessResult result={result} />);
}
