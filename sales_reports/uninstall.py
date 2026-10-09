# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""Clean uninstall handlers for Sales Person Sales Reports."""

import frappe

from sales_reports.install import REPORT_NAMES, remove_navigation


def before_uninstall():
	try:
		frappe.clear_cache()
		remove_navigation()
		for report_name in REPORT_NAMES:
			if frappe.db.exists("Report", report_name):
				frappe.delete_doc("Report", report_name, force=True, ignore_permissions=True)
		frappe.clear_cache()
	except Exception:
		frappe.log_error(title="Sales Reports before_uninstall failed")


def after_uninstall():
	try:
		frappe.clear_cache()
	except Exception:
		frappe.log_error(title="Sales Reports after_uninstall failed")
