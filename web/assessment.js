const form = document.querySelector("#assessment");
const button = form.querySelector("button");
const error = document.querySelector("#error");
const empty = document.querySelector("#empty");
const details = document.querySelector("#details");
const score = document.querySelector("#score");
const review = document.querySelector("#review");
const reasons = document.querySelector("#reasons");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const fields = new FormData(form);
  const payload = {
    likelihood: Number(fields.get("likelihood")),
    impact: Number(fields.get("impact")),
    uses_personal_data: fields.has("uses_personal_data"),
    affects_high_stakes_decisions: fields.has("affects_high_stakes_decisions"),
  };

  button.disabled = true;
  error.hidden = true;
  details.hidden = true;
  empty.textContent = "Assessing risk…";
  empty.hidden = false;

  try {
    const response = await fetch("/assessments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error("Assessment request failed");

    const result = await response.json();
    score.textContent = `${result.score} / 25 · ${result.risk_level} risk`;
    review.textContent = result.review_required ? "Human review required" : "No review triggers";
    reasons.replaceChildren(...result.review_reasons.map((reason) => {
      const item = document.createElement("li");
      item.textContent = reason;
      return item;
    }));
    reasons.hidden = !result.review_reasons.length;
    empty.hidden = true;
    details.hidden = false;
  } catch {
    empty.textContent = "Your score and review guidance will appear here.";
    error.textContent = "The assessment could not be completed. Try again.";
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
});
