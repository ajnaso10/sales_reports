# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""Sales Person Wise Sales Report — allocated Sales Invoice performance by Sales Person."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import Case
from frappe.query_builder.functions import Abs, Count, IfNull, Sum
from frappe.utils import flt, getdate

from erpnext import get_company_currency


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
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
			Sum(Case().when(sales, (sii.base_amount - sii.base_net_amount) * alloc).else_(0)).as_(
				"discount"
			),
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

	query = (
		frappe.get_query(si, filters=doc_filters, ignore_permissions=False)
		.join(sii)
		.on((si.name == sii.parent) & (sii.parenttype == "Sales Invoice"))
		.join(st)
		.on((si.name == st.parent) & (st.parenttype == "Sales Invoice"))
	)
	query = apply_tree_filter(query, st.sales_person, "Sales Person", filters.get("sales_person"))
	query = apply_tree_filter(query, si.territory, "Territory", filters.get("territory"))
	query = apply_tree_filter(query, sii.item_group, "Item Group", filters.get("item_group"))
	query = apply_tree_filter(query, sii.cost_center, "Cost Center", filters.get("cost_center"))
	return query


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
