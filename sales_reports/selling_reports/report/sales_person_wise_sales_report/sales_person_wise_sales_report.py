# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""Sales Person Wise Sales Report — allocated Sales Invoice performance by Sales Person.

Row visibility is decided by the user's roles in Sales Reports Settings, not by
where their Sales Person sits in the tree:

- Own Only: the Sales Person linked to the user
- Team: that Sales Person plus its descendants (lft/rgt on the site)
- See All: every Sales Person (also Administrator)

When several roles match, the broadest scope wins. A role in none of the lists
cannot run the report.
"""

from __future__ import annotations

import frappe
from erpnext import get_company_currency
from frappe import _
from frappe.query_builder import Case
from frappe.query_builder.functions import Abs, Count, IfNull, Sum
from frappe.utils import flt, getdate

from sales_reports.install import ensure_sales_reports_settings

SCOPE_SEE_ALL = "see_all"
SCOPE_TEAM = "team"
SCOPE_OWN = "own"
SCOPE_NONE = "none"

SETTINGS_NAME = "Sales Reports Settings"
ROLE_CHILD = "Sales Reports Role"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	# Ignore a client-supplied allow-list. Export and frappe.desk.query_report.run
	# both call execute(), so this is the only data path.
	filters.pop("allowed_sales_persons", None)
	validate_filters(filters)
	apply_sales_person_scope(filters)
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("Please select Company"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Please select From Date and To Date"))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))


def get_columns():
	return [
		{
			"label": _("Sales Person"),
			"fieldname": "sales_person",
			"fieldtype": "Link",
			"options": "Sales Person",
			"width": 180,
		},
		{
			"label": _("Total Invoices"),
			"fieldname": "total_invoices",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Total Quantity"),
			"fieldname": "total_qty",
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"label": _("Gross Sales"),
			"fieldname": "gross_sales",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Discount"),
			"fieldname": "discount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Net Sales"),
			"fieldname": "net_sales",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Return Amount"),
			"fieldname": "return_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Net Sales After Returns"),
			"fieldname": "net_sales_after_returns",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 170,
		},
		{
			"label": _("Average Invoice Value"),
			"fieldname": "average_invoice_value",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"hidden": 1,
		},
	]


def get_data(filters):
	currency = get_company_currency(filters.company)
	rows = get_grouped_rows(filters)
	data = [build_row(row, currency) for row in rows]
	if data:
		data.append(build_total_row(data, get_distinct_invoice_count(filters), currency))
	return data


def build_row(row, currency):
	invoices = cint_invoices(row.total_invoices)
	net_after = flt(row.net_sales_after_returns)
	return {
		"sales_person": row.sales_person,
		"total_invoices": invoices,
		"total_qty": flt(row.total_qty),
		"gross_sales": flt(row.gross_sales),
		"discount": flt(row.discount),
		"net_sales": flt(row.net_sales),
		"return_amount": flt(row.return_amount),
		"net_sales_after_returns": net_after,
		"average_invoice_value": flt(net_after / invoices) if invoices else 0,
		"currency": currency,
	}


def build_total_row(data, distinct_invoices, currency):
	invoices = cint_invoices(distinct_invoices)
	qty = sum(d["total_qty"] for d in data)
	gross = sum(d["gross_sales"] for d in data)
	discount = sum(d["discount"] for d in data)
	net_sales = sum(d["net_sales"] for d in data)
	returns = sum(d["return_amount"] for d in data)
	net_after = sum(d["net_sales_after_returns"] for d in data)
	return {
		"sales_person": _("Total"),
		"total_invoices": invoices,
		"total_qty": qty,
		"gross_sales": gross,
		"discount": discount,
		"net_sales": net_sales,
		"return_amount": returns,
		"net_sales_after_returns": net_after,
		"average_invoice_value": flt(net_after / invoices) if invoices else 0,
		"currency": currency,
		"bold": 1,
	}


def cint_invoices(value):
	return int(flt(value))


def get_grouped_rows(filters):
	si, sii, st = invoice_tables()
	alloc = IfNull(st.allocated_percentage, 0) / 100
	sales = si.is_return == 0
	returns = si.is_return == 1

	query = (
		joined_query(filters, si, sii, st)
		.select(
			st.sales_person,
			Count(si.name).distinct().as_("total_invoices"),
			Sum(Case().when(sales, sii.stock_qty * alloc).else_(0)).as_("total_qty"),
			Sum(Case().when(sales, sii.base_amount * alloc).else_(0)).as_("gross_sales"),
			Sum(Case().when(sales, (sii.base_amount - sii.base_net_amount) * alloc).else_(0)).as_("discount"),
			Sum(Case().when(sales, sii.base_net_amount * alloc).else_(0)).as_("net_sales"),
			Sum(Case().when(returns, Abs(sii.base_net_amount * alloc)).else_(0)).as_("return_amount"),
			(
				Sum(Case().when(sales, sii.base_net_amount * alloc).else_(0))
				- Sum(Case().when(returns, Abs(sii.base_net_amount * alloc)).else_(0))
			).as_("net_sales_after_returns"),
		)
		.groupby(st.sales_person)
		.orderby(st.sales_person)
	)
	return query.run(as_dict=True)


def get_distinct_invoice_count(filters):
	# frappe.get_query always selects `name` first; read the aliased count, not [0][0].
	si, sii, st = invoice_tables()
	query = joined_query(filters, si, sii, st).select(Count(si.name).distinct().as_("cnt"))
	row = query.run(as_dict=True)
	return cint_invoices(row[0].cnt) if row else 0


def invoice_tables():
	return (
		frappe.qb.DocType("Sales Invoice"),
		frappe.qb.DocType("Sales Invoice Item"),
		frappe.qb.DocType("Sales Team"),
	)


def joined_query(filters, si, sii, st):
	doc_filters = {
		"docstatus": 1,
		"company": filters.company,
		"posting_date": ["between", [filters.from_date, filters.to_date]],
	}
	if filters.get("customer"):
		doc_filters["customer"] = filters.customer

	# Sales Invoice select/read is granted to Accounts roles, not to Sales User,
	# Sales Manager, or System Manager. This report's audience is those sales
	# roles, so the query is not gated on Sales Invoice permissions. Who can run
	# it, and which Sales Persons they see, is apply_sales_person_scope above.
	# The same joined_query builds the grouped rows, the Total row, and the
	# distinct invoice count.
	query = (
		frappe.get_query(si, filters=doc_filters, ignore_permissions=True)
		.join(sii)
		.on((si.name == sii.parent) & (sii.parenttype == "Sales Invoice"))
		.join(st)
		.on((si.name == st.parent) & (st.parenttype == "Sales Invoice"))
	)
	query = apply_tree_filter(query, st.sales_person, "Sales Person", filters.get("sales_person"))
	query = apply_tree_filter(query, si.territory, "Territory", filters.get("territory"))
	query = apply_tree_filter(query, sii.item_group, "Item Group", filters.get("item_group"))
	query = apply_tree_filter(query, sii.cost_center, "Cost Center", filters.get("cost_center"))
	return apply_allowed_sales_persons(query, st.sales_person, filters)


def apply_allowed_sales_persons(query, sales_person_field, filters):
	allowed = filters.get("allowed_sales_persons")
	if allowed is None:
		return query
	names = [name for name in allowed if name]
	if not names:
		return query.where((sales_person_field == "") & (sales_person_field != ""))
	return query.where(sales_person_field.isin(names))


def apply_sales_person_scope(filters):
	ctx = _restriction_context(frappe.session.user)
	if ctx["error"]:
		frappe.throw(ctx["error"], frappe.PermissionError)
	if not ctx["restricted"]:
		return

	requested = filters.get("sales_person")
	allowed = set(ctx["allowed_sales_persons"])
	if requested and requested not in allowed:
		frappe.throw(
			_("You are not permitted to view sales for {0}.").format(frappe.bold(requested)),
			frappe.PermissionError,
		)
	filters.allowed_sales_persons = list(ctx["allowed_sales_persons"])


@frappe.whitelist()
def get_restriction_context():
	"""Return the calling user's scope for the sales person filter."""
	return _restriction_context(frappe.session.user)


def _restriction_context(user):
	scope = resolve_scope(user)
	if scope == SCOPE_SEE_ALL:
		return _context(scope, restricted=False)

	if scope == SCOPE_NONE:
		return _context(scope, restricted=True, read_only=True, error=_role_not_allowed_message())

	linked = get_linked_sales_persons(user)
	if not linked:
		return _context(scope, restricted=True, read_only=True, error=_no_sales_person_message())

	allowed = expand_with_descendants(linked) if scope == SCOPE_TEAM else list(linked)
	return _context(
		scope,
		restricted=True,
		sales_person=linked[0] if len(linked) == 1 else None,
		allowed_sales_persons=allowed,
		read_only=len(allowed) == 1,
	)


def _context(
	scope, *, restricted, sales_person=None, allowed_sales_persons=None, read_only=False, error=None
):
	return {
		"restricted": restricted,
		"scope": scope,
		"sales_person": sales_person,
		"allowed_sales_persons": allowed_sales_persons or [],
		"read_only": read_only,
		"error": error,
	}


def resolve_scope(user):
	"""Broadest matching role wins. Tree position is not a scope."""
	if user == "Administrator":
		return SCOPE_SEE_ALL

	roles = set(frappe.get_roles(user))
	configured = get_configured_role_sets()
	if roles & configured["see_all_roles"]:
		return SCOPE_SEE_ALL
	if roles & configured["team_roles"]:
		return SCOPE_TEAM
	if roles & configured["own_only_roles"]:
		return SCOPE_OWN
	return SCOPE_NONE


def get_configured_role_sets():
	ensure_sales_reports_settings()
	role = frappe.qb.DocType(ROLE_CHILD)
	rows = (
		frappe.qb.from_(role)
		.select(role.parentfield, role.role)
		.where(
			(role.parent == SETTINGS_NAME)
			& (role.parenttype == SETTINGS_NAME)
			& (role.role.isnotnull())
			& (role.role != "")
		)
	).run(as_dict=True)

	grouped = {"own_only_roles": set(), "team_roles": set(), "see_all_roles": set()}
	for row in rows:
		if row.parentfield in grouped and row.role:
			grouped[row.parentfield].add(row.role)
	return grouped


def get_linked_sales_persons(user):
	"""Enabled Sales Persons for the user's active Employee (Employee.user_id)."""
	employee = frappe.qb.DocType("Employee")
	employees = (
		frappe.qb.from_(employee)
		.select(employee.name)
		.where((employee.user_id == user) & (employee.status == "Active"))
		.orderby(employee.name)
	).run(pluck=True)
	if not employees:
		return []

	sales_person = frappe.qb.DocType("Sales Person")
	return (
		frappe.qb.from_(sales_person)
		.select(sales_person.name)
		.where((sales_person.employee.isin(employees)) & (sales_person.enabled == 1))
		.orderby(sales_person.name)
	).run(pluck=True)


def expand_with_descendants(sales_persons):
	"""Linked nodes plus descendants. The site's nested set is the team."""
	seen = set()
	allowed = []
	for name in sales_persons:
		for descendant in _subtree_names(name):
			if descendant in seen:
				continue
			seen.add(descendant)
			allowed.append(descendant)
	allowed.sort()
	return allowed


def _subtree_names(sales_person):
	lft, rgt = frappe.db.get_value("Sales Person", sales_person, ["lft", "rgt"]) or (None, None)
	if lft is None or rgt is None:
		return [sales_person]

	node = frappe.qb.DocType("Sales Person")
	names = (
		frappe.qb.from_(node)
		.select(node.name)
		.where((node.lft >= lft) & (node.rgt <= rgt))
		.orderby(node.name)
	).run(pluck=True)
	return names or [sales_person]


def _no_sales_person_message():
	return _(
		"No Sales Person is linked to your user. Link an active Employee (User ID) to an enabled Sales Person."
	)


def _role_not_allowed_message():
	return _(
		"You are not permitted to view Sales Person Wise Sales Report. "
		"A System Manager can add your role in Sales Reports Settings."
	)


def apply_tree_filter(query, field, doctype, value):
	if not value:
		return query
	bounds = frappe.db.get_value(doctype, value, ["lft", "rgt"])
	if not bounds or bounds[0] is None or bounds[1] is None:
		return query.where(field == value)
	lft, rgt = bounds
	tree = frappe.qb.DocType(doctype)
	descendants = frappe.qb.from_(tree).select(tree.name).where((tree.lft >= lft) & (tree.rgt <= rgt))
	return query.where(field.isin(descendants))
