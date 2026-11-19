"use strict";

const byId = (id) => document.getElementById(id);
const pages = [...document.querySelectorAll(".page")];
let apiKey = "";
let session;
let inventory = [];

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function showNotice(message = "") {
  byId("notice").textContent = message;
}

async function request(path, method = "GET", data) {
  const response = await fetch("/v1" + path, {
    method,
    cache: "no-store",
    headers: { "X-API-Key": apiKey, "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const value = await response.json();
  if (!response.ok) {
    const errors = Array.isArray(value.detail)
      ? value.detail.map((entry) => entry.loc.slice(1).join(".") + " · " + entry.msg).join("; ")
      : value.detail;
    throw new Error(errors || "Request failed.");
  }
  return value;
}

function onSubmit(id, action) {
  byId(id).addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    button.disabled = true;
    showNotice();
    try {
      await action(Object.fromEntries(new FormData(form)), form);
    } catch (error) {
      showNotice(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

function table(target, columns, rows, empty = "No records yet.") {
  if (!rows.length) {
    byId(target).replaceChildren(node("p", empty));
    return;
  }
  const wrapper = node("div", undefined, "table-scroll");
  const grid = node("table");
  const heading = grid.createTHead().insertRow();
  for (const title of columns) {
    const cell = node("th", title);
    cell.scope = "col";
    heading.append(cell);
  }
  const body = grid.createTBody();
  for (const values of rows) {
    const row = body.insertRow();
    for (const value of values) row.insertCell().textContent = value ?? "—";
  }
  wrapper.append(grid);
  byId(target).replaceChildren(wrapper);
}

function list(items) {
  const result = node("ul");
  for (const item of items) result.append(node("li", item));
  return result;
}

function renderAssessment(report) {
  const view = byId("risk-result");
  if (!report) {
    view.replaceChildren(node("p", "No saved assessments yet."));
    return;
  }
  view.replaceChildren(
    node("p", `${report.risk_score} / 100 · ${report.assessment.risk} risk`),
    node("p", report.assessment.disposition === "deny" ? "Deny in simulation" : "Consider after human review"),
    node("h3", "Findings"), list(report.assessment.reasons),
    node("h3", "Recommended controls"), list(report.assessment.controls),
  );
}

function renderReadiness(result) {
  byId("readiness-result").replaceChildren(...(result
    ? [node("p", `${result.score} / 100 · scoring ${result.scoring_version}`),
       result.gaps.length ? list(result.gaps.map((gap) => gap.task)) : node("p", "No gaps were reported.")]
    : [node("p", "No readiness assessments yet.")]));
}

function renderDraft(target, draft) {
  byId(target).replaceChildren(
    node("h3", draft.title),
    node("p", `Draft · ${draft.organisation.name} · Owner: ${draft.owner}`),
    node("p", `Scope: ${draft.scope} · Review every ${draft.review_days} days`),
    list(draft.clauses.map((clause) => `${clause.text} [${clause.control_id}]`)),
    node("p", "Requires human review before use."),
  );
}

function renderInventory() {
  const term = byId("search").value.toLowerCase().trim();
  const rows = inventory.filter((item) => [item.id, item.name, item.owner].some(
    (value) => value?.toLowerCase().includes(term),
  ));
  table("entries", ["Name", "Type", "ID", "Owner"], rows.map((item) => [
    item.name, item.kind === "tool" ? "Application" : "Agent", item.id, item.owner,
  ]), "No matching systems.");
}

const load = {
  async overview() {
    const [profile, tools, agents, reports, readiness] = await Promise.all([
      request("/organisation"), request("/inventory?kind=tool&limit=100"),
      request("/inventory?kind=agent&limit=100"), request("/reports?limit=10"),
      request("/readiness/assessments?limit=1"),
    ]);
    byId("scope").textContent = profile?.name || session.organisation_id || "Complete organisation setup to name this workspace.";
    const metric = (label, value) => {
      const card = node("section", undefined, "card metric");
      card.append(node("strong", value), node("span", label));
      return card;
    };
    const capped = (count) => count === 100 ? "100+" : count;
    byId("metrics").replaceChildren(
      metric("AI applications", capped(tools.length)),
      metric("AI agents", capped(agents.length)),
      metric("High risk in last 10 reports", reports.filter((report) => report.assessment.risk === "high").length),
      metric("Latest readiness", readiness.length ? `${readiness[0].score}%` : "—"),
    );
    table("recent", ["Agent", "Asset", "Action", "Risk", "Score"], reports.map((report) => [
      report.request.agent_id, report.request.asset_id, report.request.action,
      report.assessment.risk, report.risk_score,
    ]));
  },
  async organisation() {
    const profile = await request("/organisation");
    const form = byId("organisation-form");
    form.reset();
    if (profile) {
      for (const [key, value] of Object.entries(profile)) form.elements.namedItem(key).value = value;
    }
    byId("profile-read").textContent = session.role === "reader"
      ? profile ? `${profile.name} · ${profile.sector} · ${profile.jurisdiction} · ${profile.adoption_stage}`
        : "Organisation setup is incomplete."
      : "";
  },
  async inventory() {
    const [tools, agents] = await Promise.all([
      request("/inventory?kind=tool&limit=100"), request("/inventory?kind=agent&limit=100"),
    ]);
    inventory = [...tools, ...agents];
    renderInventory();
  },
  async readiness() {
    const [questionnaire, results] = await Promise.all([
      request("/readiness/questions"), request("/readiness/assessments?limit=1"),
    ]);
    const questions = Object.entries(questionnaire.questions).map(([key, prompt]) => {
      const label = node("label", prompt);
      const select = node("select");
      select.name = key;
      select.required = true;
      select.append(new Option("Select status", ""), new Option("In place", "in_place"),
        new Option("Partially in place", "partial"), new Option("Missing", "missing"));
      label.append(select);
      return label;
    });
    byId("questions").replaceChildren(...questions);
    renderReadiness(results[0]);
  },
  async risk() {
    const reports = await request("/reports?limit=1");
    renderAssessment(reports[0]);
  },
  async generator() {
    const templates = await request("/policy-templates");
    byId("templates").replaceChildren(...templates.map((entry) => new Option(entry.title, entry.id)));
  },
  async library() {
    const drafts = await request("/policy-drafts");
    const buttons = drafts.map((draft) => {
      const button = node("button", draft.title, "secondary");
      button.type = "button";
      button.addEventListener("click", () => renderDraft("draft-detail", draft));
      return node("p").appendChild(button).parentElement;
    });
    byId("drafts").replaceChildren(...(buttons.length ? buttons : [node("p", "No saved drafts yet.")]));
  },
  async controls() {
    const controls = await request("/controls");
    table("control-list", ["Control", "Description", "Status"], controls.map((control) => [
      control.id, control.description, control.status,
    ]));
  },
};

async function navigate() {
  if (!session) return;
  const hash = location.hash.slice(1);
  const active = Object.hasOwn(load, hash) ? hash : "overview";
  for (const page of pages) page.hidden = page.id !== active;
  for (const link of document.querySelectorAll("nav a")) {
    if (link.hash === "#" + active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  showNotice();
  try {
    await load[active]();
  } catch (error) {
    showNotice(error.message);
  }
}

onSubmit("login-form", async ({ key }, form) => {
  apiKey = key;
  form.reset();
  try {
    session = await request("/session");
  } catch (error) {
    apiKey = "";
    throw error;
  }
  for (const element of document.querySelectorAll("[data-write]")) element.hidden = session.role !== "editor";
  byId("login").hidden = true;
  byId("workspace").hidden = false;
  byId("signout").hidden = false;
  await navigate();
});
byId("signout").addEventListener("click", () => location.reload());
window.addEventListener("hashchange", navigate);
byId("search").addEventListener("input", renderInventory);

function toggleField(control, container, visible) {
  const field = byId(container);
  const input = field.querySelector("input");
  const change = () => {
    field.hidden = !visible(control);
    input.disabled = field.hidden;
    input.required = !field.hidden;
  };
  control.addEventListener("change", change);
  change();
}
toggleField(byId("kind"), "parent", (control) => control.value === "agent");
toggleField(byId("agent-scope"), "contact", (control) => control.checked);

onSubmit("organisation-form", async (data) => {
  await request("/organisation", "PUT", data);
  showNotice("Organisation saved.");
});
onSubmit("inventory-form", async (data) => {
  for (const key of ["purposes", "capabilities"]) data[key] = data[key].split(",").map((value) => value.trim()).filter(Boolean);
  await request(`/inventory/${encodeURIComponent(data.kind)}/${encodeURIComponent(data.id)}`, "PUT", data);
  await load.inventory();
  showNotice("Inventory entry saved.");
});
onSubmit("readiness-form", async (answers) => {
  renderReadiness(await request("/readiness/assessments", "POST", { answers }));
  showNotice("Readiness assessment saved.");
});
onSubmit("risk-form", async (data) => {
  renderAssessment(await request("/reports", "POST", { ...data, policy_version: "1.1.0" }));
  showNotice("Risk report saved.");
});
onSubmit("draft-form", async (data) => {
  data.review_days = Number(data.review_days);
  data.applies_to_agents = Boolean(data.applies_to_agents);
  renderDraft("draft-preview", await request("/policy-drafts", "POST", data));
  showNotice("Policy draft saved.");
});
