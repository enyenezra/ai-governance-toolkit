# Security

## Report a vulnerability

Use GitHub's private vulnerability reporting if it is enabled, or contact a
repository maintainer privately. Include the affected version, impact and a
minimal synthetic example. Keep credentials and organisational data out of
the report.

## Deployment boundaries

Run the API on a trusted network behind TLS. Give each organisation its own
instance, database and randomly generated API key. The shared key grants all
governance API privileges. Store it and the database connection string in a
secret manager. Rotate the key by replacing it and restarting the service.
Avoid logging request headers and bodies at your proxy.

Use a dedicated PostgreSQL runtime account with only the required table read
and write permissions. Use a separate operator connection for initial schema
creation. Protect backups and restrict access to the API and the database.
Set request size and rate limits at the proxy for exposed deployments.

Inventory represents operator declarations. Keep sensitive data contents out
of the registry. Recommendations have no enforcement effect and need a human
decision. The health endpoint, stateless demo and OpenAPI schema are unauthenticated.

Reports contain assessment inputs and outputs. Apply your inventory retention
and backup policies to reports. For the PostgreSQL verifier, use a separate
read-only login, scope its database access, set TLS verification as appropriate,
and avoid placing its connection URL in shell history or logs.
