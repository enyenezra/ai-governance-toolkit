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

function authHeaders() {
  if (!secret) return {};
  return credentialType === "oidc" ? { Authorization: "Bearer " + secret } : { "X-API-Key": secret };
}

async function request(path, method = "GET", data) {
  const response = await fetch("/v1" + path, {
    method,
    cache: "no-store",
    headers: {
      ...authHeaders(),
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
    const previous = versions.find((entry) => entry.version < selected);
    if (previous) {
      const compare = node("button", `Compare with revision ${previous.version}`, "secondary");
      const result = node("div");
      compare.addEventListener("click", () => runPolicyAction(async () => {
        const redline = await request(`/policy-drafts/${draft.id}/compare?from_version=${previous.version}&to_version=${selected}`);
        result.replaceChildren(...(redline.changes.length ? redline.changes.map((change) => {
          const line = node("p");
          line.append(node("strong", change.clause_id), document.createTextNode(" "),
            node("del", change.before), document.createTextNode(" "), node("ins", change.after));
          return line;
        }) : [node("p", "No clause text changed.")]));
      }));
      target.append(compare, result);
    }
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
  const downloads = node("p");
  for (const format of ["md", "docx", "pdf"]) {
    const button = node("button", "Download " + (format === "md" ? "Markdown" : format.toUpperCase()), "secondary");
    button.addEventListener("click", () => runPolicyAction(async () => {
      const response = await fetch(`/v1/published-policies/${draftId}/${version}/export/${format}`, {
        cache: "no-store", headers: authHeaders(),
      });
      if (!response.ok) throw new Error("The policy could not be exported.");
      const address = URL.createObjectURL(await response.blob());
      const link = node("a");
      link.href = address;
      link.download = `policy-${draftId}-${version}.${format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(address), 1000);
    }));
    downloads.append(button, document.createTextNode(" "));
  }
  target.append(downloads);
  if (session.member_id && ["auditor", "publisher"].includes(session.role)) {
    const summary = await request(`/published-policies/${draftId}/${version}/acknowledgement-summary`);
    target.append(node("p", `Acknowledgements: ${summary.acknowledged} of ${summary.active_members} active members`));
  }
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
    await loadTrend();
    const [profile, tools, agents, reports, adaptive, legacy] = await Promise.all([
      request("/organisation"), request("/inventory?kind=tool&limit=100"),
      request("/inventory?kind=agent&limit=100"), request("/reports?limit=10"),
      request("/readiness/adaptive/results?limit=1"), request("/readiness/assessments?limit=1"),
    ]);
    const readiness = adaptive.length ? adaptive : legacy;
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
    const form = byId("organisation-form");
    form.hidden = true;
    const profile = await request("/organisation");
    form.reset();
    if (profile) {
      for (const [key, value] of Object.entries(profile)) form.elements.namedItem(key).value = value;
    }
    form.hidden = session.role !== "editor";
    byId("profile-read").textContent = session.role !== "editor"
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
    const params = "?handles_sensitive_data=" + byId("sensitive-readiness").checked;
    const [questionnaire, results] = await Promise.all([
      request("/readiness/adaptive" + params), request("/readiness/adaptive/results?limit=1"),
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
    const [policies, schedule, reminders] = await Promise.all([
      request("/published-policies"), request("/policy-review-schedule"), request("/review-reminders"),
    ]);
    table("review-schedule", ["Policy", "Due date", "Status"], schedule.map((policy) => [
      policy.title, policy.due_date, policy.due ? "Due" : "Scheduled",
    ]), "No reviews scheduled.");
    table("policy-reminders", ["Policy", "Revision", "Due date"], reminders.map((item) => [item.title, item.version, item.due_date]), "No queued reminders.");
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
  async operations() {
    const metrics = await request("/monitoring");
    const labels = { open_incidents: "Open incidents", high_residual_risks: "High residual risks",
      rotations_due: "Rotations due", failed_control_checks: "Failed control tests" };
    byId("monitoring-summary").replaceChildren(...Object.entries(labels).map(([key, label]) => {
      const card = node("section", undefined, "card metric");
      card.append(node("strong", metrics[key]), node("span", label));
      return card;
    }));
    const kind = byId("register-kind").value;
    const items = await request("/registers/" + encodeURIComponent(kind));
    table("register-list", ["ID", "Title", "Status", "Version"], items.map((item) => [
      item.id, item.title, item.status ?? item.result ?? "Recorded", item.version,
    ]));
  },
  async access() {
    byId("request-panel").hidden = !session.member_id;
    if (!session.member_id) {
      byId("access-queue").replaceChildren(node("p", "Sign in as a named member to use access requests."));
      return;
    }
    const requests = await request("/access-requests");
    byId("access-queue").replaceChildren(...(requests.length ? requests.map(renderAccessRequest)
      : [node("p", "No access requests yet.")]));
  },
  async security() {
    const [findings, restrictions] = await Promise.all([request("/security-findings"), request("/containment")]);
    byId("containment-publisher").hidden = !session.member_id || session.role !== "publisher";
    table("security-findings", ["Finding ID", "Rule", "Agent", "Severity", "Evidence IDs"], findings.map((item) => [
      item.id, item.rule.replaceAll("_", " "), item.agent_id, item.severity, item.evidence_ids.join(", "),
    ]));
    table("containment-list", ["Request ID", "Agent", "Status", "Expires"], restrictions.map((item) => [
      item.id, item.agent_id, item.status, item.expires_at || item.approval_expires_at,
    ]));
  },
  async providers() {
    const rows = await request("/providers");
    byId("provider-publish").hidden = !session.member_id || session.role !== "publisher";
    table("provider-coverage", ["Provider", "Status", "Controls supported at gateway", "Version", "Last verified"], rows.map((row) => [
      row.name, row.status.replaceAll("_", " "), Object.keys(row.capabilities).filter((key) => row.capabilities[key] === "gateway").join(", "),
      row.deployment?.version, row.verification ? new Date(row.verification.verified_at).toLocaleString() : "—",
    ]));
    const evidence = byId("provider-evidence");
    evidence.replaceChildren();
    if (session.member_id && ["auditor", "publisher"].includes(session.role) && rows.length) {
      const label = node("label", "Provider for check evidence");
      const select = node("select");
      select.append(new Option("Select provider", ""), ...rows.map((row) => new Option(row.name, row.id)));
      const results = node("div");
      results.id = "provider-evidence-table";
      label.append(select);
      evidence.append(label, results);
      select.addEventListener("change", () => runPolicyAction(async () => {
        if (!select.value) { results.replaceChildren(); return; }
        const checks = await request("/provider-checks/" + encodeURIComponent(select.value));
        table(results.id, ["Check ID", "Revision", "Model", "Decision"], checks.map((check) => [
          check.id, check.version, check.model, check.decision,
        ]));
      }));
    }
  },
  async guardrails() {
    const [states, rules, checks] = await Promise.all([
      request("/guardrails"), request("/guardrail-rules"), request("/guardrail-verifications"),
    ]);
    byId("gate-authoring").hidden = session.role !== "editor" || !session.member_id;
    byId("gate-publishing").hidden = session.role !== "publisher" || !session.member_id;
    byId("gate-rule").replaceChildren(new Option("No rule (suspend or resume)", ""),
      ...rules.map((rule) => new Option(`${rule.scope.agent_id} · ${rule.decision} · ${rule.id}`, rule.id)));
    table("gate-states", ["Agent", "State", "Rule", "Version"], states.map((state) => [
      state.agent_id, state.suspended ? "Suspended" : state.revision_id ? "Rule active" : "Default deny",
      state.revision_id, state.version,
    ]));
    table("gate-rules", ["Agent", "Decision", "Rule ID"], rules.map((rule) => [
      rule.scope.agent_id, rule.decision, rule.id,
    ]));
    table("gate-verifications", ["Agent", "Version", "Result"], checks.map((check) => [
      check.agent_id, check.deployment_version, check.matched ? "Matched" : "Mismatch",
    ]));
  },
  async directory() {
    const members = await request("/identity/members");
    table("managed-members", ["Member", "Role", "Status", "Groups", "Version"], members.map((member) => [
      member.member_id, member.role, member.state, member.groups.join(", "), member.version,
    ]));
  },
  async discovery() {
    const [connections, evidence] = await Promise.all([
      request("/workspace-discovery/connections"), request("/workspace-discovery/evidence"),
    ]);
    table("connected-evidence", ["Finding", "Source", "Evidence", "Collected", "Coverage"], evidence.map((item) => [
      item.name, item.source, item.interpretation, new Date(item.collected_at).toLocaleString(),
      item.partial ? "Partial" : "Complete within selected sources",
    ]), "No cloud evidence collected yet.");
    const names = { microsoft365: "Microsoft 365", "google-workspace": "Google Workspace" };
    byId("connected-providers").replaceChildren(...connections.map((connection) => {
      const card = node("section", undefined, "card");
      const admin = node("a", "Open administrator portal");
      admin.href = connection.admin_portal;
      admin.target = "_blank";
      admin.rel = "noopener noreferrer";
      card.append(node("h2", names[connection.provider]), admin, node("p",
        connection.configured ? (connection.disconnected ? "Disconnected" : connection.scheduled ? "Scheduled sync enabled" : "Configured for manual sync")
          : "Administrator authorisation and deployment configuration required."));
      if (connection.enabled_sources.length) card.append(node("p", "Configured sources: " + connection.enabled_sources.join(", ")));
      if (connection.last_attempt) {
        const attempt = connection.last_attempt;
        card.append(node("p", `Latest attempt ${new Date(attempt.at).toLocaleString()} · ${attempt.status}`));
      }
      if (connection.last_result) {
        const result = connection.last_result;
        card.append(node("p", `Last successful sync ${new Date(result.synced_at).toLocaleString()} · ${result.new_findings} new findings · ${result.devices_observed} devices${result.partial ? " · Partial coverage" : ""}`));
      }
      if (session.role !== "editor" || !session.member_id || !connection.configured) return card;
      const base = "/workspace-discovery/" + connection.provider;
      const action = (title, operation) => {
        const button = node("button", title, "secondary");
        button.addEventListener("click", () => runPolicyAction(async () => {
          button.disabled = true;
          try { await operation(); } finally { button.disabled = false; }
        }));
        card.append(button, document.createTextNode(" "));
      };
      action(connection.disconnected ? "Reconnect" : "Disconnect", async () => {
        await request(base + "/connection", "PUT", { enabled: connection.disconnected });
        await load.discovery();
      });
      if (connection.disconnected) return card;
      action("Preview", async () => {
        const result = await request(base + "/preview", "POST");
        byId("connected-preview").replaceChildren(
          node("p", `Sources: ${result.sources.join(", ")} · ${result.partial ? "Partial coverage" : "Provider page complete"}`),
          list([...result.applications.map((item) => `${item.name} · ${item.source}`),
            ...result.devices.map((item) => `${item.name} · ${item.source}`)]),
        );
      });
      action("Sync now", async () => {
        const result = await request(base + "/sync", "POST");
        await load.discovery();
        showNotice(`Discovered ${result.new_findings} new review items and observed ${result.devices_observed} devices.`);
      });
      action(connection.scheduled ? "Disable scheduled sync" : "Enable scheduled sync", async () => {
        await request(base + "/schedule", "PUT", { enabled: !connection.scheduled });
        await load.discovery();
      });
      return card;
    }));
  },
  devices: () => loadDevices(0),
  async training() {
    const courses = await request("/training/courses");
    byId("training-completion").hidden = !session.member_id;
    byId("course-list").replaceChildren(...courses.map((course) => {
      const section = node("section", undefined, "card");
      section.append(node("h2", course.title), node("p", `Version ${course.version}`), list(course.lessons));
      return section;
    }));
  },
  audit: () => loadAudit(),
  async controls() {
    const controls = await request("/controls");
    table("control-list", ["Control", "Description", "Status"], controls.map((control) => [
      control.id, control.description, control.status,
    ]));
  },
};

function renderAccessRequest(item) {
  const entry = node("section", undefined, "card");
  entry.append(node("h3", `${item.request.simulation.agent_id} · ${item.request.simulation.action}`),
    node("p", `${item.requester} · ${item.status}`), node("p", item.request.justification),
    list(item.assessment.reasons));
  const canReview = session.role === "reviewer" && item.requester !== session.member_id && item.status === "pending";
  const canRenew = item.requester === session.member_id && item.status === "approved";
  if (!canReview && !canRenew) return entry;
  const form = node("form");
  const label = node("label", canReview ? "Decision rationale" : "Recertification justification");
  const note = node("textarea");
  note.required = true;
  note.maxLength = 500;
  label.append(note);
  form.append(label);
  for (const [action, title] of (canReview ? [["approved", "Approve recommendation"], ["denied", "Deny"]]
    : [["renew", "Request recertification"]])) {
    if (action === "approved" && item.assessment.disposition === "deny") continue;
    const button = node("button", title);
    button.value = action;
    form.append(button);
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const button = event.submitter;
    if (!button) return;
    button.disabled = true;
    runPolicyAction(async () => {
      try {
        if (canReview) await request("/access-decisions", "POST", {
          request_id: item.id, decision: button.value, rationale: note.value,
        });
        else await request("/access-recertifications", "POST", { request_id: item.id, justification: note.value });
        await load.access();
      } finally {
        button.disabled = false;
      }
    });
  });
  entry.append(form);
  return entry;
}

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
  await enterWorkspace();
});

async function enterWorkspace() {
  for (const element of document.querySelectorAll("[data-write]")) element.hidden = session.role !== "editor";
  byId("audit-link").hidden = session.role !== "auditor";
  byId("directory-link").hidden = session.role !== "identity_admin";
  byId("login").hidden = true;
  byId("workspace").hidden = false;
  byId("signout").hidden = false;
  await navigate();
}
byId("signout").addEventListener("click", async () => {
  const result = await fetch("/v1/sso/logout", { method: "POST" });
  if (result.ok) location.reload();
  else showNotice("Sign-out could not finish. Try again.");
});
fetch("/v1/sso/status", { cache: "no-store" })
  .then((response) => response.json()).then((value) => { byId("sso-link").hidden = !value.available; })
  .catch(() => {});
request("/session").then((value) => {
  session = value;
  return enterWorkspace();
}).catch(() => {});
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
  const params = "?handles_sensitive_data=" + byId("sensitive-readiness").checked;
  renderReadiness(await request("/readiness/adaptive" + params, "POST", { answers }));
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

byId("register-kind").addEventListener("change", () => runPolicyAction(() => load.operations()));
onSubmit("register-form", async (data) => {
  const kind = byId("register-kind").value;
  const body = JSON.parse(data.body);
  await request(`/registers/${kind}/${encodeURIComponent(data.id)}?expected_version=${Number(data.version)}`,
    "PUT", { ...body, kind });
  await load.operations();
  showNotice("Register entry saved.");
});
onSubmit("request-form", async ({ group, justification, ...simulation }) => {
  await request("/access-requests", "POST", {
    group, justification, simulation: { ...simulation, role: group, policy_version: "1.1.0" },
  });
  await load.access();
  showNotice("Access review requested.");
});

byId("sensitive-readiness").addEventListener("change", () => runPolicyAction(() => load.readiness()));
onSubmit("rule-form", async ({ scope, decision }) => {
  await request("/guardrail-rules", "POST", { scope: JSON.parse(scope), decision });
  await load.guardrails();
  showNotice("Rule proposed.");
});
onSubmit("gate-form", async ({ agent_id, operation, revision_id, version }) => {
  await request("/guardrail-deployments", "POST", {
    agent_id, operation, revision_id: revision_id || null, expected_version: Number(version),
  });
  await load.guardrails();
  showNotice("Gate deployment updated.");
});
onSubmit("member-form", async ({ id, subject, role, state, groups, version }) => {
  await request("/identity/members/" + encodeURIComponent(id), "PUT", {
    subject, role, state, groups: groups.split(",").map((value) => value.trim()).filter(Boolean),
    expected_version: Number(version),
  });
  await load.directory();
  showNotice("Member saved.");
});

async function loadTrend() {
  const data = new FormData(byId("trend-form"));
  const filters = new URLSearchParams([...data].filter(([, value]) => value));
  const report = await request("/executive-report?" + filters);
  byId("trend-count").textContent = `${report.report_count} saved assessments match.`;
  table("trend-table", ["Day (UTC)", "Risk", "Reports"],
    report.trend.map((row) => [row.day, row.risk, row.total]), "No reports match these filters.");
}
onSubmit("trend-form", loadTrend);
onSubmit("training-form", async ({ id }) => {
  await request(`/training/assignments/${encodeURIComponent(id)}/complete`, "POST");
  showNotice("Course completion recorded.");
});

async function loadDevices(offset) {
  const devices = await request(`/devices?offset=${offset}&limit=50`);
  table("device-table", ["Device", "Status", "Sources", "Last seen", "Correlation"], devices.map((item) => [
    Object.values(item.sources).find((source) => source.name)?.name || item.id.slice(0, 12),
    item.managed ? (item.network_seen ? "Managed · seen on network" : "Managed source") : "Network only",
    Object.keys(item.sources).join(", "), new Date(item.last_seen).toLocaleString(),
    item.match === "exact_mac" ? "Exact MAC" : "Source only",
  ]), "No devices observed.");
  byId("device-newer").hidden = offset === 0;
  byId("device-older").hidden = devices.length < 50;
  byId("device-newer").onclick = () => runPolicyAction(() => loadDevices(Math.max(0, offset - 50)));
  byId("device-older").onclick = () => runPolicyAction(() => loadDevices(offset + 50));
}

const providerModels = (value) => value.split(",").map((item) => item.trim()).filter(Boolean);
onSubmit("provider-form", async ({ id, models, gateway_member, account_id, ...fields }) => {
  await request("/providers/" + encodeURIComponent(id), "POST", {
    ...fields, gateway_member: gateway_member || null, account_id: account_id || null, available_models: providerModels(models),
  });
  await load.providers();
  showNotice("Provider registered.");
});
onSubmit("provider-deploy", async ({ id, expected_version, models, rollback_to }) => {
  await request("/provider-deployments/" + encodeURIComponent(id), "POST", {
    expected_version: Number(expected_version), allowed_models: providerModels(models),
    rollback_to: rollback_to ? Number(rollback_to) : null,
  });
  await load.providers();
  showNotice("Allowlist deployed at the gateway. Verification is pending.");
});
onSubmit("provider-verify", async ({ id, ...evidence }) => {
  await request("/provider-verifications/" + encodeURIComponent(id), "POST", evidence);
  await load.providers();
  showNotice("Gateway verification recorded.");
});

byId("detect-now").addEventListener("click", () => runPolicyAction(async () => {
  const result = await request("/security-detections/run", "POST");
  await load.security();
  showNotice(`${result.findings_created} new findings · ${result.incidents_created} new incidents.`);
}));
byId("containment-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const mode = event.submitter?.value;
  if (!mode) return;
  const {finding_id, minutes} = Object.fromEntries(new FormData(event.currentTarget));
  runPolicyAction(async () => {
    const result = await request("/containment", "POST", {finding_id, minutes: Number(minutes), dry_run: mode === "preview"});
    await load.security();
    showNotice(result.status === "preview" ? `Preview: suspend ${result.agent_id} at the gate for ${result.minutes} minutes.` : "Containment approval requested.");
  });
});
onSubmit("containment-transition", async ({id, action}) => {
  const result = await request("/containment/" + encodeURIComponent(id) + "/transition", "POST", {action});
  await load.security();
  showNotice("Containment status: " + result.status.replaceAll("_", " "));
});
