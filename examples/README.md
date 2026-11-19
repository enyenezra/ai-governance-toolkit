# Synthetic example inventories

These examples describe a support assistant for a fictional organisation.
They contain generated metadata and work with the JSON import command in the
[project README](../README.md). Import into a demo database. Imports replace
existing records with the same kind and ID.

| File | What it demonstrates |
| --- | --- |
| [department-inventory.json](department-inventory.json) | Policy 1.1.0 with tool and agent owners, declared purposes and capabilities, and a department-specific role need. |
| [inventory.json](inventory.json) | The original policy 1.0.0 workflow with a tool, agent, assets, role need and declared connections. |

Try the department example with the `support` role, `customer-support`
department and `ticket-summary` purpose. The `helper` agent's read of
`tickets` is eligible for human review. Its ticket write is denied because
the role has no write need. Its payroll read is denied under the restricted
data rule. These outcomes are recommendations.
