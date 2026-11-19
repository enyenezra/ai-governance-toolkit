"use strict";

const byId = (id) => document.getElementById(id);
const pages = [...document.querySelectorAll(".page")];
let secret = "";
let credentialType = "api_key";
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
    headers: {
      ...(credentialType === "oidc" ? { Authorization: "Bearer " + secret } : { "X-API-Key": secret }),
      "Content-Type": "application/json",
    },
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

function renderDraft(target, draft, published = false) {
  byId(target).replaceChildren(
    node("h3", draft.title),
    node("p", `${published ? "Published" : "Draft"} · ${draft.organisation.name} · Owner: ${draft.owner}`),
    node("p", `Scope: ${draft.scope} · Review every ${draft.review_days} days`),
    list(draft.clauses.map((clause) => `${clause.text} [${clause.control_id}]`)),
    ...(!published ? [node("p", "Requires human review before use.")] : []),
  );
}

async function runPolicyAction(operation) {
  showNotice();
  try {
    await operation();
  } catch (error) {
    showNotice(error.message);
  }
}

async function openPolicy(draft, selectedVersion) {
  const base = `/policy-drafts/${draft.id}/revisions`;
  const versions = await request(base);
  const latest = versions[0]?.version;
  const selected = selectedVersion ?? latest;
  const current = selected ? await request(`${base}/${selected}`) : null;
  renderDraft("draft-detail", current?.body ?? draft);
  const target = byId("draft-detail");
  if (current) {
    const picker = node("select");
    for (const { version } of versions) picker.append(new Option(`Revision ${version}`, version));
    picker.value = selected;
    picker.addEventListener("change", () => runPolicyAction(() => openPolicy(draft, Number(picker.value))));
    const label = node("label", "Version history");
    label.append(picker);
    target.append(label, node("p", `Review status: ${current.status.replaceAll("_", " ")} · Author: ${current.author}`));
    if (current.events.length) target.append(list(current.events.map((event) =>
      `${event.action.replaceAll("_", " ")} · ${event.actor}${event.note ? " · " + event.note : ""}`)));
  }
  if (selected !== latest) return;
  if (!session.member_id) {
    target.append(node("p", "Use a named editor or reviewer key for policy revisions and decisions."));
    return;
  }

  const owned = current?.author === session.member_id;
  const open = current?.status === "draft";
  const pending = current?.status === "submitted";
  if (session.role === "editor" && (!current || (!pending && (!open || owned)))) {
    const form = node("form");
    for (const clause of (current?.body ?? draft).clauses) {
      const label = node("label", clause.id);
      const field = node("textarea");
      field.name = clause.id;
      field.value = clause.text;
      field.required = true;
      field.maxLength = 4000;
      label.append(field);
      form.append(label);
    }
    const save = node("button", "Save new revision");
    form.append(save);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      save.disabled = true;
      runPolicyAction(async () => {
        try {
          const clauseTexts = Object.fromEntries(new FormData(form));
          await request(base, "POST", { expected_version: latest ?? 0, clause_texts: clauseTexts });
          await openPolicy(draft);
          showNotice("Revision saved.");
        } finally {
          save.disabled = false;
        }
      });
    });
    target.append(form);
  }
  if (session.role === "editor" && owned && open) {
    const submit = node("button", "Submit revision for review", "secondary");
    submit.addEventListener("click", () => runPolicyAction(async () => {
      submit.disabled = true;
      try {
        await request(`${base}/${selected}/submit`, "POST");
        await openPolicy(draft);
        showNotice("Revision submitted.");
      } finally {
        submit.disabled = false;
      }
    }));
    target.append(submit);
  }
  if (current?.published_at) target.append(node("p", "This revision has been published."));
  if (session.role === "publisher" && current?.status === "approved" && !current.published_at
      && !owned && draft.created_by !== session.member_id
      && !current.events.some((event) => event.action === "approved" && event.actor === session.member_id)) {
    const publish = node("button", "Publish approved revision", "secondary");
    publish.addEventListener("click", () => runPolicyAction(async () => {
      publish.disabled = true;
      try {
        await request("/policy-publications", "POST", { draft_id: draft.id, version: selected });
        await openPolicy(draft);
        showNotice("Policy published for this organisation.");
      } finally {
        publish.disabled = false;
      }
    }));
    target.append(publish);
  }

  if (session.role === "reviewer" && pending && !owned && draft.created_by !== session.member_id) {
    const form = node("form");
    const label = node("label", "Decision rationale");
    const note = node("textarea");
    note.required = true;
    note.maxLength = 4000;
    label.append(note);
    form.append(label);
    const actions = [["approved", "Approve revision"], ["changes_requested", "Request changes"]];
    for (const [action, title] of actions) {
      const button = node("button", title);
      button.name = "decision";
      button.value = action;
      form.append(button);
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const button = event.submitter;
      if (!button) return;
      for (const action of form.querySelectorAll("button")) action.disabled = true;
      runPolicyAction(async () => {
        try {
          await request("/policy-reviews", "POST", {
            draft_id: draft.id, version: selected, action: button.value, note: note.value,
          });
          await openPolicy(draft);
          showNotice("Review decision recorded.");
        } finally {
          for (const action of form.querySelectorAll("button")) action.disabled = false;
        }
      });
    });
    target.append(form);
  }
}

async function openPublishedPolicy(draftId, version) {
  const policy = await request(`/published-policies/${draftId}/${version}`);
  renderDraft("published-detail", policy.body, true);
  const target = byId("published-detail");
  target.append(node("p", `Revision ${policy.version} · Published by ${policy.publisher}`));
  if (policy.acknowledged_at) {
    target.append(node("p", "You acknowledged this version."));
  } else if (policy.current && session.member_id) {
    const button = node("button", "Acknowledge this version");
    button.addEventListener("click", () => runPolicyAction(async () => {
      button.disabled = true;
      try {
        await request("/policy-acknowledgements", "POST", { draft_id: draftId, version });
        await openPublishedPolicy(draftId, version);
      } finally {
        button.disabled = false;
      }
    }));
    target.append(button);
  }
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
      button.addEventListener("click", () => runPolicyAction(() => openPolicy(draft)));
      const entry = node("p");
      entry.append(button);
      return entry;
    });
    byId("drafts").replaceChildren(...(buttons.length ? buttons : [node("p", "No saved drafts yet.")]));
  },
  async published() {
    const policies = await request("/published-policies");
    const entries = policies.map((policy) => {
      const entry = node("p");
      const button = node("button", policy.title, "secondary");
      button.type = "button";
      button.addEventListener("click", () => runPolicyAction(() => openPublishedPolicy(policy.draft_id, policy.version)));
      entry.append(button);
      return entry;
    });
    byId("published-list").replaceChildren(...(entries.length ? entries : [node("p", "No published policies yet.")]));
  },
  audit: () => loadAudit(),
  async controls() {
    const controls = await request("/controls");
    table("control-list", ["Control", "Description", "Status"], controls.map((control) => [
      control.id, control.description, control.status,
    ]));
  },
};

async function loadAudit(before) {
  const events = await request("/audit-events?limit=20" + (before ? "&before=" + before : ""));
  table("audit-events", ["Time", "Actor", "Credential", "Action", "Resource", "Revision"], events.map((event) => [
    new Date(event.occurred_at).toLocaleString(), event.actor_id ?? "Shared key", event.credential,
    event.action, `${event.resource_type} / ${event.resource_id}`, event.version,
  ]), "No more events.");
  byId("audit-more").hidden = events.length < 20;
  byId("audit-more").onclick = () => runPolicyAction(() => loadAudit(events.at(-1).event_id));
  byId("audit-newest").hidden = !before;
}
byId("audit-newest").addEventListener("click", () => runPolicyAction(() => loadAudit()));

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

byId("credential-type").addEventListener("change", (event) => {
  const oidc = event.target.value === "oidc";
  byId("credential-label").textContent = oidc ? "OIDC access token" : "Organisation API key";
  event.target.form.elements.namedItem("key").maxLength = oidc ? 8192 : 256;
});
onSubmit("login-form", async ({ key, credential }, form) => {
  secret = key.trim();
  credentialType = credential;
  form.elements.namedItem("key").value = "";
  try {
    session = await request("/session");
  } catch (error) {
    secret = "";
    throw error;
  }
  for (const element of document.querySelectorAll("[data-write]")) element.hidden = session.role !== "editor";
  byId("audit-link").hidden = session.role !== "auditor";
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
