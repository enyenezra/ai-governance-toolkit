import { useState } from "react";
import { createRoot } from "react-dom/client";

const likelihoodRatings = ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"];
const impactRatings = ["Negligible", "Minor", "Moderate", "Major", "Severe"];
const initialAssessment = { status: "idle" };

function Rating({ name, label, ratings }) {
  return (
    <label>
      {label}
      <select name={name} defaultValue="" required>
        <option value="">Select a rating</option>
        {ratings.map((rating, index) => (
          <option key={rating} value={index + 1}>{index + 1} · {rating}</option>
        ))}
      </select>
    </label>
  );
}

function AssessmentResult({ assessment }) {
  const { status, result } = assessment;
  return (
    <section aria-labelledby="result-title">
      <h2 id="result-title">Assessment result</h2>
      <div aria-live="polite">
        {status === "complete" ? (
          <>
            <p id="score">{result.score} / 25 · {result.risk_level} risk</p>
            <p id="review">{result.review_required ? "Human review required" : "No review triggers"}</p>
            {result.review_reasons.length > 0 && (
              <ul>
                {result.review_reasons.map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            )}
          </>
        ) : (
          <p id="empty">
            {status === "pending" ? "Assessing risk…" : "Your score and review guidance will appear here."}
          </p>
        )}
      </div>
    </section>
  );
}

function Assessment() {
  const [assessment, setAssessment] = useState(initialAssessment);

  async function submit(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setAssessment({ status: "pending" });

    try {
      const response = await fetch("/assessments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          likelihood: Number(fields.get("likelihood")),
          impact: Number(fields.get("impact")),
          uses_personal_data: fields.has("uses_personal_data"),
          affects_high_stakes_decisions: fields.has("affects_high_stakes_decisions"),
        }),
      });
      if (!response.ok) throw new Error("Assessment request failed.");
      setAssessment({ status: "complete", result: await response.json() });
    } catch {
      setAssessment({ status: "error" });
    }
  }

  return (
    <>
      <header>
        <span>AI Governance Toolkit</span>
        <div><a href="/workspace">Governance workspace</a> · <a href="/docs">API docs</a></div>
      </header>
      <main>
        <h1>Risk assessment</h1>
        <p className="intro">Rate an AI use case to see its risk score and whether it needs human review.</p>
        <div className="layout">
          <form onSubmit={submit}>
            <div className="ratings">
              <Rating name="likelihood" label="Likelihood" ratings={likelihoodRatings} />
              <Rating name="impact" label="Impact" ratings={impactRatings} />
            </div>
            <fieldset>
              <legend>Review triggers</legend>
              <label className="check"><input type="checkbox" name="uses_personal_data" /> Uses personal data</label>
              <label className="check">
                <input type="checkbox" name="affects_high_stakes_decisions" /> Affects high-stakes decisions
              </label>
            </fieldset>
            <button type="submit" disabled={assessment.status === "pending"}>Assess risk</button>
            <p id="error" role="alert" hidden={assessment.status !== "error"}>
              The assessment could not be completed. Try again.
            </p>
          </form>
          <AssessmentResult assessment={assessment} />
        </div>
        <p className="note">Scores support initial triage. Apply your organisation’s governance criteria when making decisions.</p>
      </main>
    </>
  );
}

createRoot(document.getElementById("assessment-root")).render(<Assessment />);
