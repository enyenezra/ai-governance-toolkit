# Pilot checklist

Use test tenants, a non-production protected route and an authorised
network exporter. Keep all integration credentials in your secret manager.

1. Follow [connected discovery](connected-discovery.md). Start with app metadata
   and the smallest set of scopes. Preview both Microsoft 365 and Google
   Workspace before enabling scheduled sync. Record enabled sources and
   expected record counts.
2. Feed a known non-production DHCP, Wi-Fi, switch or NAC observation. Check
   that a reliable MAC matches a known managed device and that a source-only
   observation does not produce an asserted match.
3. Compare evidence classifications and the reported coverage with the source
   admin consoles. Induce a safe credential failure in the test connector and
   verify that the failure is visible while the last successful result remains.
4. Rotate the credential, verify the next sync, then disconnect in the
   workspace. Confirm scheduled collection stops. Revoke provider consent
   separately if ending the pilot. Reconnect and re-preview before scheduling.
5. Deploy one narrowly scoped rule in a test app using the
   [external ASGI adapter](release-extensions.md#rules-and-external-enforcement).
   Confirm that allow reaches the operation and deny or gate failure does not.
   Verify a direct route around the adapter is inaccessible.
6. Restore a database dump in isolation before expanding scope. Record gaps
   in source coverage, audit attribution and operational ownership.

A local demo uses synthetic inventory and fixture-based connector tests.
It leaves provider consent, network access and deployment changes to the
pilot administrator.
