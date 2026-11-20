export function OverviewPage() {
  return (
    <section id="overview" className="page">
      <h1>Executive governance dashboard</h1>
      <p className="subtitle" id="scope"></p>
      <section className="card"><h2>Risk trends</h2>
          <form id="trend-form">
            <div className="row">
              <label>Days <input name="days" type="number" min="1" max="366" defaultValue="90" required /></label>
              <label>Department ID <input name="department" /></label>
              <label>System or agent ID <input name="system" /></label>
              <label>Risk <select name="risk"><option value="">All risks</option><option>low</option><option>medium</option><option>high</option></select></label>
              <label>Decision <select name="disposition"><option value="">All decisions</option><option value="deny">Deny</option><option value="consider_after_review">Human review</option></select></label>
            </div>
            <button>Apply filters</button>
          </form>
          <p id="trend-count"></p><div id="trend-table"></div>
        </section>
        <div id="metrics" className="metrics"></div>
      <section className="card"><h2>Recent risk assessments</h2><div id="recent"></div></section>
    </section>
  );
}

export function OrganisationPage() {
  return (
    <section id="organisation" className="page" hidden>
      <h1>Organisation setup</h1>
      <section className="card"><form id="organisation-form" data-write="">
        <label>Organisation name <input name="name" maxLength="160" required /></label>
        <div className="row">
          <label>Sector <input name="sector" maxLength="160" required /></label>
          <label>Jurisdiction <input name="jurisdiction" maxLength="160" required /></label>
        </div>
        <label>Adoption stage <select name="adoption_stage"><option value="exploring">Exploring</option><option value="piloting">Piloting</option><option value="operating">Operating</option></select></label>
        <button>Save organisation</button>
      </form><p id="profile-read"></p></section>
    </section>
  );
}

export function InventoryPage() {
  return (
    <section id="inventory" className="page" hidden>
      <h1>AI systems &amp; agent inventory</h1>
      <div className="split">
        <section className="card">
          <div className="section-head"><h2>Registered systems</h2><input id="search" type="search" aria-label="Search loaded inventory" placeholder="Search inventory" /></div>
          <div id="entries"></div>
        </section>
        <section className="card" data-write="">
          <h2>Register a system</h2>
          <form id="inventory-form">
            <label>Record type <select name="kind" id="kind"><option value="tool">AI application</option><option value="agent">AI agent</option></select></label>
            <div className="row"><label>ID <input name="id" required pattern="[a-z0-9][a-z0-9_\-]{0,63}" /></label><label>Name <input name="name" maxLength="120" required /></label></div>
            <label id="parent" hidden>Parent application ID <input name="tool_id" disabled /></label>
            <label>Owner ID <input name="owner" required /></label>
            <label>Intended purpose IDs <input name="purposes" placeholder="ticket-summary" /></label>
            <label>Capability IDs <input name="capabilities" placeholder="summarisation" /></label>
            <button>Register</button>
          </form>
        </section>
      </div>
    </section>
  );
}

export function ReadinessPage() {
  return (
    <section id="readiness" className="page" hidden>
      <h1>AI readiness assessment</h1>
      <div className="split">
        <section className="card" data-write=""><form id="readiness-form"><label className="check"><input id="sensitive-readiness" type="checkbox" /> Handles sensitive data</label>
          <div id="questions"></div><button>Save assessment</button></form></section>
        <section className="card"><h2>Latest readiness result</h2><div id="readiness-result"></div></section>
      </div>
    </section>
  );
}

export function RiskPage() {
  return (
    <section id="risk" className="page" hidden>
      <h1>AI risk assessment</h1>
      <div className="split">
        <section className="card" data-write="">
          <h2>Simulate access</h2>
          <form id="risk-form">
            <div className="row"><label>Department ID <input name="department_id" required /></label><label>Role <input name="role" required /></label></div>
            <div className="row"><label>Agent ID <input name="agent_id" required /></label><label>Asset ID <input name="asset_id" required /></label></div>
            <div className="row"><label>Purpose ID <input name="purpose" required /></label><label>Action <select name="action"><option>read</option><option>write</option><option>delete</option><option>admin</option></select></label></div>
            <button>Assess and save report</button>
          </form>
        </section>
        <section className="card"><h2>Latest report</h2><div id="risk-result"></div></section>
      </div>
    </section>
  );
}

export function GeneratorPage() {
  return (
    <section id="generator" className="page" hidden>
      <h1>AI policy generator</h1>
      <div className="split">
        <section className="card" data-write="">
          <h2>Configure a template</h2>
          <form id="draft-form">
            <label>Template <select name="template_id" id="templates"></select></label>
            <label>Policy owner <input name="owner" required maxLength="160" /></label>
            <label>Scope <input name="scope" required maxLength="160" /></label>
            <label>Review interval in days <input name="review_days" required type="number" defaultValue="90" min="30" max="365" /></label>
            <label className="check"><input type="checkbox" name="applies_to_agents" id="agent-scope" /> Applies to agents</label>
            <label id="contact" hidden>Human oversight contact <input name="oversight_contact" maxLength="160" disabled /></label>
            <button>Generate and save draft</button>
          </form>
        </section>
        <section className="card"><h2>Draft preview</h2><div id="draft-preview">Select a saved draft from the policy library or generate a new one.</div></section>
      </div>
    </section>
  );
}

export function LibraryPage() {
  return (
    <section id="library" className="page" hidden><h1>Policy library</h1><div className="split"><section className="card"><h2>Saved drafts</h2><div id="drafts"></div></section><section className="card"><h2>Policy details</h2><div id="draft-detail">Select a draft to read its clauses.</div></section></div></section>
  );
}

export function PublishedPage() {
  return (
    <section id="published" className="page" hidden>
      <h1>Published policies</h1>
      <div className="split">
        <section className="card"><h2>Current policies</h2><div id="published-list"></div><h2>Review schedule</h2><div id="review-schedule"></div><h2>Due reminders</h2><div id="policy-reminders"></div></section>
        <section className="card"><h2>Policy details</h2><div id="published-detail">Select a published policy to read its clauses.</div></section>
      </div>
    </section>
  );
}

export function OperationsPage() {
  return (
    <section id="operations" className="page" hidden>
      <h1>Governance registers</h1>
      <div id="monitoring-summary" className="metrics"></div>
      <div className="split">
        <section className="card">
          <label>Register <select id="register-kind">
            <option value="risk">Risk</option><option value="incident">Incidents</option>
            <option value="vendor">Vendors</option><option value="training">Training</option>
            <option value="discovery">Discovered services</option><option value="signal">Monitoring signals</option>
            <option value="credential">Credential rotation</option><option value="framework_assessment">Framework assessments</option><option value="control_check">Control tests</option>
          </select></label>
          <div id="register-list"></div>
        </section>
        <section className="card" data-write="">
          <h2>Save a register record</h2>
          <form id="register-form">
            <label>Record ID <input name="id" pattern="[a-z0-9][a-z0-9_\-]{0,63}" required /></label>
            <label>Expected version (0 for a new record) <input name="version" type="number" min="0" required defaultValue="0" /></label>
            <label>Record JSON <textarea name="body" required spellCheck="false"></textarea></label>
            <p>See <a href="/docs">API documentation</a> for the selected register’s fields.</p>
            <button>Save record</button>
          </form>
        </section>
      </div>
    </section>
  );
}

export function AccessPage() {
  return (
    <section id="access" className="page" hidden>
      <h1>Access requests</h1>
      <div className="split">
        <section className="card"><h2>Requests and decisions</h2><div id="access-queue"></div></section>
        <section className="card" id="request-panel">
          <h2>Request access review</h2>
          <form id="request-form">
            <label>Identity group <input name="group" required /></label>
            <div className="row"><label>Department <input name="department_id" required /></label><label>Purpose <input name="purpose" required /></label></div>
            <div className="row"><label>Agent <input name="agent_id" required /></label><label>Asset <input name="asset_id" required /></label></div>
            <label>Action <select name="action"><option>read</option><option>write</option><option>delete</option><option>admin</option></select></label>
            <label>Business justification <textarea name="justification" maxLength="500" required></textarea></label>
            <button>Submit recommendation request</button>
          </form>
        </section>
      </div>
    </section>
  );
}

export function NotificationsPage() {
  return (
    <section id="notifications" className="page" hidden>
      <h1>Notifications</h1>
      <section className="card"><h2>Recent notifications</h2><div id="notification-list"></div></section>
      <section className="card" id="notification-preferences" hidden><h2>Outbound preferences</h2>
        <p id="notification-destinations"></p>
        <form id="notification-settings-form">
          <label className="check"><input name="channels" defaultValue="webhook" type="checkbox" /> Signed webhook</label>
          <label className="check"><input name="channels" defaultValue="smtp" type="checkbox" /> SMTP email</label>
          <label>Minimum priority <select name="minimum_priority"><option>info</option><option>attention</option><option>urgent</option></select></label>
          <label>Events (leave unselected for all supported events)
            <select id="notification-events" name="events" multiple size="6"></select>
          </label>
          <button>Save notification preferences</button>
        </form>
      </section>
    </section>
  );
}

export function SecurityPage() {
  return (
    <section id="security" className="page" hidden>
      <h1>Security findings</h1>
      <section className="card"><h2>Detection evidence</h2><div id="security-findings"></div>
        <button id="detect-now" type="button" data-write="">Run detections</button>
      </section>
      <section className="card"><h2>Temporary gate restrictions</h2><div id="containment-list"></div></section>
      <section className="card" data-write=""><h2>Propose containment</h2>
        <form id="containment-form">
          <label>Finding ID <input name="finding_id" required /></label>
          <label>Minutes <input name="minutes" type="number" min="1" max="60" defaultValue="15" required /></label>
          <button name="mode" value="preview">Preview restriction</button>
          <button name="mode" value="request">Request approval</button>
        </form>
      </section>
      <section className="card" id="containment-publisher" hidden><h2>Review and apply containment</h2>
        <form id="containment-transition">
          <label>Request ID <input name="id" required /></label>
          <label>Action <select name="action"><option>approve</option><option>execute</option><option>rollback</option></select></label>
          <button>Apply action</button>
        </form>
      </section>
    </section>
  );
}

export function ProvidersPage() {
  return (
    <section id="providers" className="page" hidden>
      <h1>Provider enforcement</h1>
      <section className="card"><h2>Coverage and verification</h2><div id="provider-coverage"></div>
        <div id="provider-evidence"></div></section>
      <section className="card" data-write=""><h2>Register a provider</h2>
        <form id="provider-form">
          <label>Provider ID <input name="id" required /></label>
          <label>Name <input name="name" required /></label>
          <label>Type <select name="provider_type">
            <option value="openai_compatible">OpenAI-compatible gateway</option>
            <option value="internal">Internal</option><option value="self_hosted">Self-hosted</option>
            <option value="azure_openai">Azure OpenAI</option><option value="anthropic">Anthropic</option>
            <option value="gemini">Gemini</option><option value="bedrock">Bedrock</option>
            <option value="copilot">Copilot</option><option value="mcp">MCP</option>
          </select></label>
          <label>HTTPS endpoint <input type="url" name="endpoint" required /></label>
          <label>Gateway member ID <input name="gateway_member" /></label>
          <label>Provider account ID (optional) <input name="account_id" /></label>
          <label>Registered models (comma separated) <input name="models" /></label>
          <button>Register provider</button>
        </form>
      </section>
      <section className="card" id="provider-publish" hidden><h2>Publish an allowlist</h2>
        <form id="provider-deploy">
          <label>Provider ID <input name="id" required /></label>
          <label>Expected version <input name="expected_version" type="number" min="0" defaultValue="0" required /></label>
          <label>Allowed models (comma separated) <input name="models" /></label>
          <label>Rollback to version (optional) <input name="rollback_to" type="number" min="1" /></label>
          <button>Publish or roll back</button>
        </form>
        <h2>Verify gateway decisions</h2>
        <form id="provider-verify">
          <label>Provider ID <input name="id" required /></label>
          <label>Allowed check ID <input name="allowed_check" required /></label>
          <label>Denied check ID <input name="denied_check" required /></label>
          <button>Record verification</button>
        </form>
      </section>
    </section>
  );
}

export function GuardrailsPage() {
  return (
    <section id="guardrails" className="page" hidden>
      <h1>Runtime guardrails</h1>
      <p className="subtitle">Deployments apply at the AIGovKit gate. Callers must stop on denial or failure.</p>
      <div className="split">
        <section className="card"><h2>Current gate states</h2><div id="gate-states"></div>
          <h2>Recent verifications</h2><div id="gate-verifications"></div>
        </section>
        <section className="card">
          <div id="gate-authoring" hidden><h2>Propose an exact rule</h2>
            <form id="rule-form">
              <label>Policy 1.1.0 scope JSON <textarea name="scope" required></textarea></label>
              <label>Decision <select name="decision"><option>deny</option><option>allow</option></select></label>
              <button>Propose rule</button>
            </form>
          </div>
          <div id="gate-publishing" hidden><h2>Change a gate deployment</h2>
            <form id="gate-form">
              <label>Agent ID <input name="agent_id" required /></label>
              <label>Operation <select name="operation"><option>deploy</option><option>rollback</option><option>suspend</option><option>resume</option></select></label>
              <label>Rule <select name="revision_id" id="gate-rule"></select></label>
              <label>Expected version <input name="version" type="number" min="0" required defaultValue="0" /></label>
              <button>Apply at gate</button>
            </form>
          </div>
          <h2>Proposed rules</h2><div id="gate-rules"></div>
        </section>
      </div>
    </section>
  );
}

export function DirectoryPage() {
  return (
    <section id="directory" className="page" hidden>
      <h1>Managed identity directory</h1>
      <div className="split">
        <section className="card"><h2>Members</h2><div id="managed-members"></div></section>
        <section className="card"><h2>Provision or update a member</h2>
          <form id="member-form">
            <label>Stable member ID <input name="id" required /></label>
            <label>Verified issuer subject <input name="subject" maxLength="255" required /></label>
            <label>Role <select name="role"><option>reader</option><option>editor</option><option>reviewer</option><option>publisher</option><option>auditor</option></select></label>
            <label>State <select name="state"><option>active</option><option>suspended</option></select></label>
            <label>Managed group IDs (comma separated) <input name="groups" /></label>
            <label>Expected version <input name="version" type="number" min="0" required defaultValue="0" /></label>
            <button>Save member</button>
          </form>
        </section>
      </div>
    </section>
  );
}

export function DiscoveryPage() {
  return (
    <section id="discovery" className="page" hidden>
      <h1>Connected discovery</h1>
      <p className="subtitle">Authorise the provider, preview read-only results, then enable scheduled sync.</p>
      <div id="connected-providers" className="split"></div>
      <section className="card"><h2>Discovery preview</h2><div id="connected-preview"><p>Select a provider to preview its findings.</p></div></section>
      <section className="card"><h2>Latest cloud evidence</h2><div id="connected-evidence"></div></section>
    </section>
  );
}

export function DevicesPage() {
  return (
    <section id="devices" className="page" hidden>
      <h1>Device inventory</h1>
      <p className="subtitle">Managed inventory and passive network observations. Source-only records may refer to the same device.</p>
      <section className="card"><div id="device-table"></div>
        <button type="button" id="device-newer" className="secondary" hidden>Previous page</button>
        <button type="button" id="device-older" className="secondary" hidden>Next page</button>
      </section>
    </section>
  );
}

export function ExecutivePage() {
  return (
    <section id="executive" className="page" hidden>
      <h1>Executive reports</h1>
      <section className="card" data-write="">
        <form id="board-form">
          <label>Period start <input name="start" type="date" required /></label>
          <label>Period end <input name="end" type="date" required /></label>
          <label>Department ID <input name="department" /></label>
          <label>Template <select name="template"><option value="board">Board</option><option value="risk">Risk</option><option value="security">Security</option><option value="operations">Operations</option></select></label>
          <button>Generate report</button>
        </form>
        <form id="board-schedule">
          <label className="check"><input name="enabled" type="checkbox" /> Generate a report daily</label>
          <label>Days to include <input name="days" type="number" min="1" max="366" defaultValue="30" required /></label>
          <button>Save schedule</button>
        </form>
      </section>
      <div id="board-list"></div>
      <section id="reassessment-panel" className="card" hidden><h2>Reassessments due</h2><div id="reassessment-list"></div></section>
      <section id="export-history-panel" className="card" hidden><h2>Audit export delivery</h2><div id="export-history"></div></section>
    </section>
  );
}

export function TrainingPage() {
  return (
    <section id="training" className="page" hidden>
      <h1>Training courses</h1>
      <section className="card" data-write="">
        <form id="learning-assign">
          <label>Course <select name="course_id" id="learning-course-select" required></select></label>
          <label>Learner member ID <input name="learner" required /></label>
          <label>Due date <input name="due" type="date" required /></label>
          <button id="learning-assign-button" disabled>Assign training</button>
        </form>
      </section>
      <section className="card" id="course-edit-panel" hidden>
        <h2>Course editor</h2>
        <form id="course-editor">
          <label>Course ID <input name="course_id" required /></label>
          <label>Draft revision <input name="revision" type="number" min="0" defaultValue="0" required /></label>
          <label>Course title <input name="title" maxLength="160" required /></label>
          <label>Lesson text <textarea name="lesson" required></textarea></label>
          <label>Quiz question <input name="question" required /></label>
          <label>First choice <input name="first" required /></label>
          <label>Second choice <input name="second" required /></label>
          <label>Correct choice <select name="correct_choice"><option value="0">First</option><option value="1">Second</option></select></label>
          <button>Save course draft</button>
        </form>
      </section>
      <div id="course-drafts"></div>
      <section className="card" id="enrolment-panel" hidden>
        <h2>Automatic enrolment</h2>
        <form id="enrolment-rule">
          <label>Rule ID <input name="id" required /></label>
          <label>Course version <select name="course_id" id="enrolment-course" required></select></label>
          <label>Member role <select name="role"><option value="reader">Reader</option><option value="editor">Editor</option><option value="reviewer">Reviewer</option><option value="publisher">Publisher</option><option value="auditor">Auditor</option></select></label>
          <label>Directory group (optional) <input name="group" /></label>
          <label>Days to complete <input name="due_days" type="number" min="1" max="365" defaultValue="14" required /></label>
          <label>Refresher interval in days (optional) <input name="refresher_days" type="number" min="1" max="3650" /></label>
          <label className="check"><input name="enabled" type="checkbox" defaultChecked /> Enable rule</label>
          <button>Save enrolment rule</button>
        </form>
        <div id="enrolment-rules"></div>
      </section>
      <div id="learning-assignments"></div>
      <div id="course-list"></div>
      <section className="card" id="training-completion" hidden><h2>Record course completion</h2>
        <form id="training-form"><label>Assignment ID <input name="id" required /></label>
          <button>Attest completion</button>
        </form>
      </section>
    </section>
  );
}

export function AuditPage() {
  return (
    <section id="audit" className="page" hidden>
      <h1>Governance audit</h1>
      <section className="card"><h2>Recorded changes</h2><div id="audit-events"></div>
        <button id="audit-more" type="button" className="secondary" hidden>View older events</button>
        <button id="audit-newest" type="button" className="secondary" hidden>View newest events</button>
      </section>
    </section>
  );
}

export function ControlsPage() {
  return (
    <section id="controls" className="page" hidden><h1>Control catalogue</h1><section className="card"><div id="control-list"></div></section></section>
  );
}
