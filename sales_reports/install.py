# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""Install / migrate handlers for Sales Reports."""

import frappe

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


def after_install():
	sync_navigation()


def after_migrate():
	sync_navigation()


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
