import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";

import { initializeWorkspace } from "./workspace-controller.js";
import {
  OverviewPage,
  OrganisationPage,
  InventoryPage,
  ReadinessPage,
  RiskPage,
  GeneratorPage,
  LibraryPage,
  PublishedPage,
  OperationsPage,
  AccessPage,
  NotificationsPage,
  SecurityPage,
  ProvidersPage,
  GuardrailsPage,
  DirectoryPage,
  DiscoveryPage,
  DevicesPage,
  ExecutivePage,
  TrainingPage,
  AuditPage,
  ControlsPage,
} from "./workspace-pages.jsx";

function Workspace() {
  return (
    <>
      <aside className="sidebar">
        <a className="brand" href="#overview"><span aria-hidden="true">◆</span> AIGovKit</a>
        <nav aria-label="Workspace">
          <a href="#overview">Governance dashboard</a>
          <a href="#executive" id="executive-link" hidden>Executive reports</a>
          <a href="#organisation">Organisation setup</a>
          <a href="#inventory">AI systems &amp; agents</a>
          <a href="#readiness">Readiness assessment</a>
          <a href="#risk">Risk assessment</a>
          <a href="#generator">AI policy generator</a>
          <a href="#library">Policy library</a>
          <a href="#published">Published policies</a>
          <a href="#controls">Control catalogue</a>
          <a href="#operations">Governance registers</a>
          <a href="#discovery">Connected discovery</a>
          <a href="#devices">Devices</a>
          <a href="#training">Training courses</a>
          <a href="#access">Access requests</a>
          <a href="#guardrails">Runtime guardrails</a>
          <a href="#providers">Provider enforcement</a>
          <a href="#security">Security findings</a>
          <a href="#notifications">Notifications</a>
          <a href="#directory" id="directory-link" hidden>Identity directory</a>
          <a href="#audit" id="audit-link" hidden>Audit events</a>
        </nav>
        <div className="sidebar-footer"><a href="/docs">API documentation ↗</a></div>
      </aside>
      <main>
        <header><span>Governance workspace</span><button id="signout" type="button" hidden>Sign out</button></header>
        <div id="content">
          <section className="card" id="login">
            <h1>Sign in to AIGovKit</h1>
            <p>Use an organisation API key or an access token issued for the AIGovKit API. Reloading clears it.</p>
            <form id="login-form">
              <label>Credential type <select name="credential" id="credential-type">
                <option value="api_key">API key</option><option value="oidc">OIDC access token</option>
              </select></label>
              <label><span id="credential-label">Organisation API key</span><input name="key" type="password" maxLength="256" required autoComplete="off" /></label>
              <button type="submit">Open workspace</button>
            </form>
            <p><a href="/v1/sso/start" id="sso-link" hidden>Sign in with your identity provider</a></p>
          </section>
          <p id="notice" role="status" aria-live="polite"></p>
          <div id="workspace" hidden>
            <OverviewPage />
            <OrganisationPage />
            <InventoryPage />
            <ReadinessPage />
            <RiskPage />
            <GeneratorPage />
            <LibraryPage />
            <PublishedPage />
            <OperationsPage />
            <AccessPage />
            <NotificationsPage />
            <SecurityPage />
            <ProvidersPage />
            <GuardrailsPage />
            <DirectoryPage />
            <DiscoveryPage />
            <DevicesPage />
            <ExecutivePage />
            <TrainingPage />
            <AuditPage />
            <ControlsPage />
          </div>
        </div>
      </main>
    </>
  );
}

const root = createRoot(document.getElementById("workspace-root"));
flushSync(() => root.render(<Workspace />));
initializeWorkspace();
