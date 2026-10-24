### Sales Reports

Selling reports for ERPNext:

- **Sales Person Wise Sales Report** — allocated Sales Invoice performance by Sales Person, limited by role
- **Lead-to-Revenue Conversion Report** — Lead → Quotation → Customer → Sales Order → Sales Invoice

### Sales Person Wise Sales Report access

Who can see which rows is configured in **Sales Reports Settings** (a Single). A System Manager edits the three role tables in the desk. No deploy or `site_config` change is required. If a user has more than one of these roles, the broadest scope wins.

| Scope | Default role | What they see |
| --- | --- | --- |
| Own Only | Sales User | Only the Sales Person linked to them |
| Team | Sales Manager | That Sales Person plus its descendants in the Sales Person tree |
| See All | System Manager | Every Sales Person |

Administrator always sees every Sales Person, including when the See All list is empty. A role that is not in any of the three tables cannot run the report. Sales Manager is a Team role, not a See All role.

The tree is whatever is on the site (`lft` / `rgt` on Sales Person). Nothing about the hierarchy is hardcoded. A Sales User who is a parent node still sees only their own Sales Person.

Link each person like this:

1. Employee is **Active** and **User ID** is their login.
2. Sales Person is **enabled** and its **Employee** is that employee.
3. For a Team role, put the reps under that Sales Person in the tree.

Own Only and Team users with no linked Sales Person get an error. The Sales Person filter defaults to their own node, only offers people in their scope, and is read-only when that scope is a single Sales Person.

The first migrate seeds the default roles. `defaults_applied` then stops later migrates from overwriting the tables. The seed lists in `sales_reports/install.py` (`DEFAULT_ROLE_ROWS`) are only that initial fill.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app sales_reports
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/sales_reports
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
