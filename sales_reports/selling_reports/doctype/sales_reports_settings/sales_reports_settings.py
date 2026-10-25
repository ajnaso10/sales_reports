# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document


class SalesReportsSettings(Document):
	def validate(self):
		seen = {}
		labels = {
			"own_only_roles": _("Own Only"),
			"team_roles": _("Team"),
			"see_all_roles": _("See All"),
		}
		for fieldname, label in labels.items():
			for row in self.get(fieldname) or []:
				role = row.role
				if not role:
					continue
				if role in seen:
					frappe.throw(
						_("{0} is already listed under {1}. A role can belong to only one scope.").format(
							frappe.bold(role), frappe.bold(seen[role])
						)
					)
				seen[role] = label

	def on_update(self):
		from sales_reports.install import ensure_see_all_report_access

		ensure_see_all_report_access([row.role for row in (self.see_all_roles or []) if row.role])
