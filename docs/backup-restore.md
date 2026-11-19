# Back up and restore

Back up PostgreSQL and deployment configuration. Database dumps contain
tenant data. Encrypt them and restrict access. Back up tenant credentials,
the device hashing secret, the audit signing key and SSO configuration
through your secret manager. Rotate or revoke exposed credentials. Preserve
the device hashing key to keep historical correlation IDs stable.

## Take a backup

From the deployment checkout, use the same environment and Compose project
used to start the service. Keep the export off the server in approved storage.

```sh
umask 077
docker compose exec -T db pg_dump -U aigovkit -d aigovkit -Fc > aigovkit.dump
pg_restore --list aigovkit.dump
```

The Compose database uses PostgreSQL 16. Use a compatible `pg_restore` client
for inspection. The database dump includes the tenant schemas and managed
directory. Role passwords and operating system or proxy configuration are
managed separately.

## Verify a restore in isolation

Provision an empty PostgreSQL database in a separate test environment running
the same application revision. Confirm its connection string and permissions
before writing to it. A restore into an existing target requires a separate
operator decision.

```sh
pg_restore --exit-on-error --single-transaction --no-owner --no-privileges \
  --dbname="$AIGOVKIT_RESTORE_DATABASE_URL" aigovkit.dump
```

Start a separate app instance on the restored copy with approved recovery
credentials. Keep provider sync and schedulers paused. Verify profiles,
inventory, policy versions, acknowledgements, audit events and tenant
isolation. Record the restore result and elapsed time before considering the
backup usable. Restore into an isolated environment before any production
cutover. Have the operator approve that cutover.
