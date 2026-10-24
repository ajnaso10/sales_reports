# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""Install / migrate handlers for Sales Reports."""

import frappe
from frappe.utils import cint

# Seed values for a new site. Runtime scope is the Sales Reports Settings single,
# which a System Manager can edit without a code change. These tuples are not
# read when the report runs.
DEFAULT_ROLE_ROWS = (
	("own_only_roles", "Sales User"),
	("team_roles", "Sales Manager"),
	("see_all_roles", "System Manager"),
)

SETTINGS_DOCTYPE = "Sales Reports Settings"

REPORT_NAMES = (
	"Sales Person Wise Sales Report",
	"Lead-to-Revenue Conversion Report",
)

# Backwards-compatible alias used by uninstall until callers migrate.
REPORT_NAME = REPORT_NAMES[0]

SELLING_WORKSPACES = ("Sales", "Selling")
SELLING_SIDEBARS = ("Sales", "Selling")

# Prefer inserting after the previous sales report when present.
INSERT_AFTER_BY_REPORT = {
	"Sales Person Wise Sales Report": "Sales Person-wise Transaction Summary",
	"Lead-to-Revenue Conversion Report": "Sales Person Wise Sales Report",
}
INSERT_AFTER_FALLBACK = "Sales Analytics"


# Desk report gate: frappe.desk.query_report.get_report_doc checks
# has_permission(ref_doctype, "report") before execute(). Sales Person Wise
# Sales Report uses Sales Person. Sales User and Sales Manager already have
# that permission. Every current See All role is granted it here.
REF_DOCTYPE = "Sales Person"
ROLE_CHILD_DOCTYPE = "Sales Reports Role"
BASIC_PERM_TYPES = ("select", "read", "write", "create", "submit", "cancel")
# Roles shipped on the report. A Custom Role replaces this list, so a new one
# keeps these roles and then adds any See All role that was missing.
SHIPPED_REPORT_ROLES = (
	"Sales User",
	"Sales Manager",
	"Accounts User",
	"Accounts Manager",
	"System Manager",
)


def after_install():
	ensure_sales_reports_settings()
	ensure_see_all_report_access()
	sync_navigation()


def after_migrate():
	ensure_sales_reports_settings()
	ensure_see_all_report_access()
	sync_navigation()


def ensure_sales_reports_settings():
	"""Create default role rows once. Later edits in the Single are left alone."""
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return
	if cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, "defaults_applied")):
		return

	doc = frappe.get_doc(SETTINGS_DOCTYPE)
	for fieldname, role in DEFAULT_ROLE_ROWS:
		if doc.get(fieldname):
			continue
		if frappe.db.exists("Role", role):
			doc.append(fieldname, {"role": role})

	doc.defaults_applied = 1
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


def ensure_see_all_report_access(see_all_roles=None):
	"""Let every See All role pass the desk report gate for this report.

	Called from install, migrate, and Sales Reports Settings.on_update. Migrate
	still runs it after defaults_applied is set, so an existing site picks up
	the grant without a re-seed. Removing a role from See All does not revoke
	the permission: the previous grant is unknown, and execute() still denies
	a role that is not in any scope list.
	"""
	if see_all_roles is None:
		ensure_sales_reports_settings()
		see_all_roles = _see_all_roles_from_settings()

	roles = [role for role in see_all_roles if role and frappe.db.exists("Role", role)]
	_ensure_report_ref_doctype()
	if frappe.db.exists("DocType", REF_DOCTYPE):
		for role in roles:
			_grant_report_permission(REF_DOCTYPE, role)
		frappe.clear_cache(doctype=REF_DOCTYPE)
	_ensure_see_all_roles_on_report(roles)


def _see_all_roles_from_settings():
	if not frappe.db.exists("DocType", ROLE_CHILD_DOCTYPE):
		return []
	return frappe.get_all(
		ROLE_CHILD_DOCTYPE,
		filters={
			"parent": SETTINGS_DOCTYPE,
			"parenttype": SETTINGS_DOCTYPE,
			"parentfield": "see_all_roles",
		},
		pluck="role",
	)


def _ensure_report_ref_doctype():
	report_name = REPORT_NAMES[0]
	if not frappe.db.exists("Report", report_name):
		return
	if frappe.db.get_value("Report", report_name, "ref_doctype") == REF_DOCTYPE:
		return
	frappe.db.set_value("Report", report_name, "ref_doctype", REF_DOCTYPE, update_modified=False)
	frappe.clear_document_cache("Report", report_name)


def _grant_report_permission(doctype, role):
	"""Grant report on doctype without dropping the standard DocPerm rows.

	Custom DocPerm replaces DocPerm once any custom row exists, so the standard
	rows are copied first. A row with only report set fails Frappe's permission
	validation, so a new row also gets select.
	"""
	from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

	setup_custom_perms(doctype)
	row = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		["name", "report", *BASIC_PERM_TYPES],
		as_dict=True,
	)
	if not row:
		add_permission(doctype, role, 0, "select")
		row = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
			["name", "report", *BASIC_PERM_TYPES],
			as_dict=True,
		)
	if not row:
		return

	if not any(cint(row.get(ptype)) for ptype in BASIC_PERM_TYPES):
		update_permission_property(doctype, role, 0, "select", 1)
	if not cint(row.report):
		update_permission_property(doctype, role, 0, "report", 1)


def _ensure_see_all_roles_on_report(see_all_roles):
	"""Report.is_permitted() requires a role on the report, or on its Custom Role.

	Custom Role replaces the standard role list, so a new Custom Role keeps the
	standard roles and adds any See All role that was missing. Accounts User and
	Accounts Manager are already on the report. A role the client adds to See All
	is appended. Existing Custom Role rows are left in place.
	"""
	report_name = REPORT_NAMES[0]
	if not frappe.db.exists("Report", report_name):
		return

	wanted = [role for role in see_all_roles if role and frappe.db.exists("Role", role)]
	report = frappe.get_doc("Report", report_name)
	standard = {row.role for row in report.roles if row.role} | set(SHIPPED_REPORT_ROLES)
	custom_name = frappe.db.get_value("Custom Role", {"report": report_name}, "name")
	if custom_name:
		doc = frappe.get_doc("Custom Role", custom_name)
		have = {row.role for row in doc.roles}
		changed = False
		for role in wanted:
			if role not in have:
				doc.append("roles", {"role": role})
				changed = True
		if changed:
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
		return

	missing = [role for role in wanted if role not in standard]
	if not missing:
		return

	frappe.get_doc(
		{
			"doctype": "Custom Role",
			"report": report_name,
			"ref_doctype": REF_DOCTYPE,
			"roles": [{"role": role} for role in sorted(standard | set(missing))],
		}
	).insert(ignore_permissions=True)


def sync_navigation():
	"""Show reports under Sales / Selling workspace and sidebar."""
	try:
		for workspace in SELLING_WORKSPACES:
			for report_name in REPORT_NAMES:
				_sync_workspace_links(workspace, report_name)
		for sidebar in SELLING_SIDEBARS:
			for report_name in REPORT_NAMES:
				_sync_sidebar_items(sidebar, report_name)
		frappe.clear_cache()
	except Exception:
		frappe.log_error(title="Sales Reports: failed to sync navigation")


def remove_navigation():
	for workspace in SELLING_WORKSPACES:
		_remove_workspace_links(workspace)
	for sidebar in SELLING_SIDEBARS:
		_remove_sidebar_items(sidebar)


def _child_as_dict(row):
	data = row.as_dict()
	for key in (
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"parent",
		"parentfield",
		"parenttype",
		"idx",
		"docstatus",
	):
		data.pop(key, None)
	return data


def _insert_links_after(rows, after_link_to, new_rows, fallback_link_to=None):
	result = []
	inserted = False
	for row in rows:
		result.append(row)
		if not inserted and row.get("type") == "Link" and row.get("link_to") == after_link_to:
			result.extend(new_rows)
			inserted = True
	if not inserted and fallback_link_to:
		result = []
		for row in rows:
			result.append(row)
			if not inserted and row.get("type") == "Link" and row.get("link_to") == fallback_link_to:
				result.extend(new_rows)
				inserted = True
	if not inserted:
		result = list(rows) + list(new_rows)
	return result


def _sync_workspace_links(workspace_name: str, report_name: str):
	if not frappe.db.exists("Workspace", workspace_name):
		return
	if not frappe.db.exists("Report", report_name):
		return

	ws = frappe.get_doc("Workspace", workspace_name)
	existing = {row.link_to for row in ws.links if row.type == "Link" and row.link_to}
	if report_name in existing:
		return

	rows = [_child_as_dict(row) for row in ws.links]
	new_row = {
		"type": "Link",
		"label": report_name,
		"link_type": "Report",
		"link_to": report_name,
		"is_query_report": 1,
		"onboard": 0,
		"hidden": 0,
	}
	insert_after = INSERT_AFTER_BY_REPORT.get(report_name, INSERT_AFTER_FALLBACK)
	rows = _insert_links_after(rows, insert_after, [new_row], INSERT_AFTER_FALLBACK)

	ws.set("links", [])
	for row in rows:
		ws.append("links", row)

	frappe.flags.in_migrate = True
	try:
		ws.flags.ignore_permissions = True
		ws.flags.ignore_links = True
		ws.save()
	finally:
		frappe.flags.in_migrate = False


def _sync_sidebar_items(sidebar_name: str, report_name: str):
	if not frappe.db.exists("Workspace Sidebar", sidebar_name):
		return
	if not frappe.db.exists("Report", report_name):
		return

	sb = frappe.get_doc("Workspace Sidebar", sidebar_name)
	existing = {row.link_to for row in sb.items if row.type == "Link" and row.link_to}
	if report_name in existing:
		return

	rows = [_child_as_dict(row) for row in sb.items]
	new_row = {
		"type": "Link",
		"label": report_name,
		"link_type": "Report",
		"link_to": report_name,
		"child": 1,
		"collapsible": 1,
	}
	insert_after = INSERT_AFTER_BY_REPORT.get(report_name, INSERT_AFTER_FALLBACK)
	rows = _insert_links_after(rows, insert_after, [new_row], INSERT_AFTER_FALLBACK)

	sb.set("items", [])
	for row in rows:
		sb.append("items", row)

	frappe.flags.in_migrate = True
	try:
		sb.flags.ignore_permissions = True
		sb.save()
	finally:
		frappe.flags.in_migrate = False


def _remove_workspace_links(workspace_name: str):
	if not frappe.db.exists("Workspace", workspace_name):
		return

	ws = frappe.get_doc("Workspace", workspace_name)
	before = len(ws.links)
	ws.links = [row for row in ws.links if not (row.type == "Link" and row.link_to in REPORT_NAMES)]
	if len(ws.links) == before:
		return

	frappe.flags.in_migrate = True
	try:
		ws.flags.ignore_permissions = True
		ws.flags.ignore_links = True
		ws.save()
	finally:
		frappe.flags.in_migrate = False


def _remove_sidebar_items(sidebar_name: str):
	if not frappe.db.exists("Workspace Sidebar", sidebar_name):
		return

	sb = frappe.get_doc("Workspace Sidebar", sidebar_name)
	before = len(sb.items)
	sb.items = [row for row in sb.items if not (row.type == "Link" and row.link_to in REPORT_NAMES)]
	if len(sb.items) == before:
		return

	frappe.flags.in_migrate = True
	try:
		sb.flags.ignore_permissions = True
		sb.save()
	finally:
		frappe.flags.in_migrate = False
