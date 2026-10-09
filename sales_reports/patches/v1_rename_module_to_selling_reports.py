import frappe

OLD = "Sales Person Sales Reports"
NEW = "Selling Reports"


def execute():
	"""Point reports at Selling Reports module; drop the old module name."""
	if not frappe.db.exists("Module Def", NEW):
		frappe.get_doc(
			{
				"doctype": "Module Def",
				"module_name": NEW,
				"app_name": "sales_reports",
			}
		).insert(ignore_permissions=True)

	for report_name in (
		"Lead-to-Revenue Conversion Report",
		"Sales Person Wise Sales Report",
	):
		if frappe.db.exists("Report", report_name):
			frappe.db.set_value("Report", report_name, "module", NEW, update_modified=False)

	frappe.db.set_value("Report", {"module": OLD}, "module", NEW, update_modified=False)

	if frappe.db.exists("Module Def", OLD):
		# Standard Module Def cannot be renamed; delete after reports are moved.
		frappe.db.set_value("Module Def", OLD, "custom", 1)
		frappe.delete_doc("Module Def", OLD, force=True, ignore_permissions=True)
