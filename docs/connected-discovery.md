# Connected cloud and passive device discovery

AIGovKit can renew read-only cloud access automatically after the organisation
administrator approves the permissions and the deployment operator configures
credentials. Each AIGovKit tenant has its own connection configuration.

## Microsoft 365 and Entra

Register an application in the Microsoft tenant and grant only the application
permissions for the selected sources. Start with enterprise app inventory.
Enable sign-in and device sources separately.

| Source | Permission |
| --- | --- |
| Enterprise application inventory | `Application.Read.All` |
| Entra sign-in metadata | `AuditLog.Read.All` |
| Managed Intune devices | `DeviceManagementManagedDevices.Read.All` |

The sign-in source uses a seven-day window and relies on the tenant’s
available logs. The collector stores app identity metadata and aggregate
counts. It discards user records, sign-in details and location information.
Intune discovery requires the appropriate tenant service and licence.
[Application inventory](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list?view=graph-rest-1.0) · [Sign-in API](https://learn.microsoft.com/en-us/graph/api/signin-list?view=graph-rest-1.0) · [Intune devices](https://learn.microsoft.com/en-us/graph/api/intune-devices-manageddevice-list?view=graph-rest-1.0) · [Admin consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent)

## Google Workspace

Enable the relevant Admin SDK APIs for a Google Cloud service account.
Have a Workspace administrator authorise domain-wide delegation for the
specific read-only scopes you use. Configure a delegated account with
the corresponding reporting or device permissions. Use the exact Workspace
customer ID. Mount the authorised service account credential read-only.

| Source | OAuth scope suffix after `https://www.googleapis.com/auth/` |
| --- | --- |
| OAuth audit authorisation events | `admin.reports.audit.readonly` |
| Managed ChromeOS devices | `admin.directory.device.chromeos.readonly` |
| Managed mobile devices | `admin.directory.device.mobile.readonly` |

OAuth events show an authorisation observed in the last seven days. They
provide evidence for review and cannot establish current access or AI usage.
[Google service accounts and delegation](https://developers.google.com/identity/protocols/oauth2/service-account) · [OAuth audit events](https://developers.google.com/workspace/admin/reports/v1/appendix/activity/token) · [ChromeOS devices](https://developers.google.com/workspace/admin/directory/reference/rest/v1/chromeosdevices/list) · [Mobile devices](https://developers.google.com/workspace/admin/directory/reference/rest/v1/mobiledevices/list)

## Connect and schedule

Set `AIGOVKIT_DISCOVERY_CONNECTIONS` using the deployment secret manager. The
following shape uses placeholders. Mount the Google credential using a
deployment override at the path configured inside the container.

```json
{
  "your-aigovkit-tenant": {
    "microsoft365": {
      "tenant_id": "MICROSOFT_TENANT_GUID",
      "client_id": "APP_REGISTRATION_GUID",
      "client_secret": "DEPLOYMENT_SECRET",
      "applications": true,
      "sign_ins": false,
      "devices": true
    },
    "google_workspace": {
      "service_account_file": "/run/secrets/workspace-discovery.json",
      "delegated_admin": "reports-reader@example.invalid",
      "customer_id": "CUSTOMER_ID",
      "oauth_audit": true,
      "chromeos": true,
      "mobile": false
    }
  }
}
```

Generate `AIGOVKIT_DEVICE_HASH_KEY` from at least 32 random bytes and keep it
stable across deployments. Changing it changes correlation and discovery IDs.
Provide both variables to the API. In **Connected discovery**, open the
administrator portal if setup is needed. A named editor can preview results
without importing them, sync immediately, and enable or disable scheduled sync.
A successful preview is required before enabling a new provider configuration.
Run the existing [scheduled jobs command](release-extensions.md) for each
organisation using a scoped scheduler key. It reports per-provider failure and
retains the last successful sync separately from the latest failed or partial
attempt. The evidence table distinguishes app inventory, sign-ins and OAuth
authorisations. **Disconnect** stops local discovery, clears the schedule and
retains existing findings. Reconnect and preview again before scheduling.
Revoke consent separately in the provider portal if required.

Each sync reads up to three pages per enabled source. The preview reads one
page and displays up to twenty apps and twenty devices. Partial coverage is
reported. Apps enter the existing discovery review queue once per source and
provider ID. Imported device records appear under **Devices**.

## Passive network ingestion

Configure named observer credentials for an authorised DHCP, Wi-Fi, switch,
or network access control exporter. This release provides an intake API and
JSON Lines collector for normalised records. Device collection does not
scan networks or inspect packets.

Send observations to `POST /v1/device-observations` with a source, unicast
MAC and a recent observation time with timezone. The optional name should
be a device label. For example, the body for a DHCP observation has this shape:

```json
{"source":"dhcp","mac":"00:11:22:33:44:55","seen_at":"OBSERVED_RFC3339_TIMESTAMP"}
```

For optional DNS or proxy signals, set `AIGOVKIT_AI_SIGNAL_DOMAINS` to the
approved comma-separated domain suffixes. Submit only `source` (`dns` or
`proxy`), `mac`, `seen_at`, `domain` and `count` to
`POST /v1/device-domain-signals`. AIGovKit stores only the approved matching
suffix and the first submitted daily count for the source, device and suffix.
An observation is a signal to investigate. It cannot prove AI use, identity
or data disclosure.

Set `AIGOVKIT_PASSIVE_API` to your trusted HTTPS base URL and
`AIGOVKIT_PASSIVE_OBSERVER_KEY` to the observer credential, then pipe approved
normalised JSON Lines to `python -m aigovkit.passive_collector devices` or use
the `domains` mode for domain signals. The collector validates each record.

Universal MAC addresses are matched exactly within the tenant using a keyed
fingerprint. Locally administered addresses and records without reliable
MACs stay source-specific. Raw MACs, IPs, packet contents, full URLs and user
identities are excluded from the stored payload. Management status reflects
the sources that observed a record. It does not establish current enrolment.
