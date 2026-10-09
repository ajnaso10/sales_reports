# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""Lead-to-Revenue Conversion Report — Lead → Quotation → Customer → SO → SI."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext import get_company_currency

QT_SALES_PERSON_FIELD = "custom_sales_person"
CONVERTED = "Converted"
NOT_CONVERTED = "Not Converted"
PARTIALLY = "Partially Converted"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	builder = LeadToRevenueReport(filters)
	columns = builder.get_columns()
	data = builder.get_data()
	message = builder.get_summary_message()
	return columns, data, message


def validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("Please select Company"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("Please select From Date and To Date"))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))


class LeadToRevenueReport:
	def __init__(self, filters):
		self.filters = filters
		self.currency = get_company_currency(filters.company)
		self.has_qt_sales_person = frappe.get_meta("Quotation").has_field(QT_SALES_PERSON_FIELD)
		self.qt_statuses = parse_multiselect(filters.get("quotation_status"))
		self.so_statuses = parse_multiselect(filters.get("sales_order_status"))
		self.si_statuses = parse_multiselect(filters.get("sales_invoice_status"))
		self.summary = frappe._dict(qt_value=0, so_value=0, si_value=0, qt_ids=set(), so_ids=set(), si_ids=set())

	def get_columns(self):
		return [
			{"label": _("Lead ID"), "fieldname": "lead", "fieldtype": "Link", "options": "Lead", "width": 140},
			{"label": _("Lead Name"), "fieldname": "lead_name", "fieldtype": "Data", "width": 150},
			{"label": _("Lead Created Date"), "fieldname": "lead_created", "fieldtype": "Date", "width": 120},
			{"label": _("Lead Source"), "fieldname": "lead_source", "fieldtype": "Link", "options": "UTM Source", "width": 120},
			{"label": _("Lead Owner"), "fieldname": "lead_owner", "fieldtype": "Link", "options": "User", "width": 150},
			{"label": _("Quotation ID"), "fieldname": "quotation", "fieldtype": "Link", "options": "Quotation", "width": 140},
			{"label": _("Quotation Date"), "fieldname": "quotation_date", "fieldtype": "Date", "width": 110},
			{"label": _("Quotation Status"), "fieldname": "quotation_status", "fieldtype": "Data", "width": 120},
			{"label": _("Quotation Grand Total"), "fieldname": "quotation_grand_total", "fieldtype": "Currency", "options": "currency", "width": 140},
			{"label": _("Quotation Sales Person"), "fieldname": "quotation_sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 140},
			{"label": _("Customer ID"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 130},
			{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 150},
			{"label": _("Customer Created Date"), "fieldname": "customer_created", "fieldtype": "Date", "width": 130},
			{"label": _("Sales Order ID"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
			{"label": _("Sales Order Date"), "fieldname": "sales_order_date", "fieldtype": "Date", "width": 120},
			{"label": _("Sales Order Status"), "fieldname": "sales_order_status", "fieldtype": "Data", "width": 140},
			{"label": _("Sales Order Grand Total"), "fieldname": "sales_order_grand_total", "fieldtype": "Currency", "options": "currency", "width": 150},
			{"label": _("Sales Order Sales Person"), "fieldname": "sales_order_sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 150},
			{"label": _("Sales Invoice ID"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
			{"label": _("Sales Invoice Posting Date"), "fieldname": "sales_invoice_date", "fieldtype": "Date", "width": 140},
			{"label": _("Sales Invoice Status"), "fieldname": "sales_invoice_status", "fieldtype": "Data", "width": 130},
			{"label": _("Sales Invoice Grand Total"), "fieldname": "sales_invoice_grand_total", "fieldtype": "Currency", "options": "currency", "width": 150},
			{"label": _("Sales Invoice Sales Person"), "fieldname": "sales_invoice_sales_person", "fieldtype": "Link", "options": "Sales Person", "width": 150},
			{"label": _("Lead-to-Quotation Status"), "fieldname": "lead_to_quotation_status", "fieldtype": "Data", "width": 150},
			{"label": _("Quotation-to-Sales-Order Status"), "fieldname": "quotation_to_so_status", "fieldtype": "Data", "width": 180},
			{"label": _("Sales-Order-to-Sales-Invoice Status"), "fieldname": "so_to_si_status", "fieldtype": "Data", "width": 200},
			{"label": _("Total Quotation Value"), "fieldname": "total_quotation_value", "fieldtype": "Currency", "options": "currency", "width": 140},
			{"label": _("Total Sales Order Value"), "fieldname": "total_sales_order_value", "fieldtype": "Currency", "options": "currency", "width": 150},
			{"label": _("Total Invoiced Value"), "fieldname": "total_invoiced_value", "fieldtype": "Currency", "options": "currency", "width": 140},
			{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
		]

	def get_summary_message(self):
		if not (self.summary.qt_ids or self.summary.so_ids or self.summary.si_ids):
			return None
		return _(
			"Deduplicated totals — Quotations ({0}): {1} | Sales Orders ({2}): {3} | Invoices ({4}): {5}"
		).format(
			len(self.summary.qt_ids),
			frappe.format_value(self.summary.qt_value, {"fieldtype": "Currency", "options": self.currency}),
			len(self.summary.so_ids),
			frappe.format_value(self.summary.so_value, {"fieldtype": "Currency", "options": self.currency}),
			len(self.summary.si_ids),
			frappe.format_value(self.summary.si_value, {"fieldtype": "Currency", "options": self.currency}),
		)

	def get_data(self):
		leads = self._fetch_leads()
		if not leads:
			return []

		lead_names = [d.name for d in leads]
		customers_by_lead = self._fetch_customers(lead_names)
		opportunities = self._fetch_opportunities(lead_names)
		quotations = self._fetch_quotations(lead_names, customers_by_lead, opportunities)
		qt_by_lead = self._group_quotations_by_lead(quotations, lead_names, customers_by_lead, opportunities)

		qt_names = list({q.name for qs in qt_by_lead.values() for q in qs})
		so_by_qt = self._fetch_sales_orders(qt_names)
		so_names = list({so.name for sos in so_by_qt.values() for so in sos})
		si_by_so = self._fetch_sales_invoices(so_names)

		so_team = self._fetch_sales_team("Sales Order", so_names)
		si_names = list({si.name for sis in si_by_so.values() for si in sis})
		si_team = self._fetch_sales_team("Sales Invoice", si_names)

		rows = []
		for lead in leads:
			customer = customers_by_lead.get(lead.name)
			if self.filters.get("customer") and (not customer or customer.name != self.filters.customer):
				continue

			lead_qts = qt_by_lead.get(lead.name) or []
			lead_to_qt = CONVERTED if lead_qts else NOT_CONVERTED

			if not lead_qts:
				if self._status_filters_block_empty_path():
					continue
				if self.filters.get("sales_person"):
					continue
				rows.append(self._build_row(lead, None, customer, None, None, None, None, lead_to_qt, NOT_CONVERTED, NOT_CONVERTED))
				continue

			for qt in lead_qts:
				if not self._match_status(qt.status, self.qt_statuses, include_cancelled_default=False):
					continue
				sos = so_by_qt.get(qt.name) or []
				qt_to_so = self._qt_to_so_status(qt, sos)
				qt_sp = qt.get("sales_person")

				if not sos:
					if self.so_statuses or self.si_statuses:
						continue
					if not self._match_sales_person_filter(qt_sp, None, None):
						continue
					rows.append(self._build_row(lead, qt, customer, None, None, qt_sp, None, lead_to_qt, qt_to_so, NOT_CONVERTED))
					continue

				for so in sos:
					if not self._match_status(so.status, self.so_statuses, include_cancelled_default=False):
						continue
					sis = si_by_so.get(so.name) or []
					so_to_si = CONVERTED if sis else NOT_CONVERTED
					so_people = so_team.get(so.name) or []

					if not sis:
						if self.si_statuses:
							continue
						for so_person, so_alloc in self._iter_team(so_people, so.base_grand_total):
							if not self._match_sales_person_filter(qt_sp, so_person, None):
								continue
							rows.append(
								self._build_row(
									lead, qt, customer, so, None, qt_sp, so_person, lead_to_qt, qt_to_so, so_to_si,
									so_amount=so_alloc,
								)
							)
						continue

					for si in sis:
						if not self._match_status(si.status, self.si_statuses, include_cancelled_default=False):
							continue
						si_people = si_team.get(si.name) or []
						for si_person, si_alloc in self._iter_team(si_people, si.base_grand_total):
							so_person, so_alloc = self._pick_so_person(so_people, so.base_grand_total, si_person)
							if not self._match_sales_person_filter(qt_sp, so_person, si_person):
								continue
							rows.append(
								self._build_row(
									lead, qt, customer, so, si, qt_sp, so_person, lead_to_qt, qt_to_so, so_to_si,
									so_amount=so_alloc,
									si_person=si_person,
									si_amount=si_alloc,
								)
							)
		return rows

	def _status_filters_block_empty_path(self):
		return bool(self.qt_statuses or self.so_statuses or self.si_statuses)

	def _match_status(self, status, selected, include_cancelled_default=False):
		if selected:
			return status in selected
		if status == "Cancelled" and not include_cancelled_default:
			return False
		return True

	def _qt_to_so_status(self, qt, sos):
		if sos:
			return CONVERTED
		if qt.status == "Partially Ordered":
			return PARTIALLY
		return NOT_CONVERTED

	def _match_sales_person_filter(self, qt_sp, so_sp, si_sp):
		wanted = self.filters.get("sales_person")
		if not wanted:
			return True
		return wanted in {qt_sp, so_sp, si_sp}

	def _iter_team(self, people, grand_total):
		if not people:
			yield None, flt(grand_total)
			return
		if len(people) == 1:
			row = people[0]
			amount = flt(row.allocated_amount) if row.allocated_amount is not None else flt(grand_total)
			yield row.sales_person, amount
			return
		for row in people:
			amount = flt(row.allocated_amount)
			if not amount and row.allocated_percentage:
				amount = flt(grand_total) * flt(row.allocated_percentage) / 100.0
			yield row.sales_person, amount

	def _pick_so_person(self, so_people, grand_total, preferred):
		if not so_people:
			return None, flt(grand_total)
		if preferred:
			for row in so_people:
				if row.sales_person == preferred:
					amount = flt(row.allocated_amount)
					if not amount and row.allocated_percentage:
						amount = flt(grand_total) * flt(row.allocated_percentage) / 100.0
					return row.sales_person, amount or flt(grand_total)
		# Single display person when expanding by invoice allocations
		if len(so_people) == 1:
			row = so_people[0]
			amount = flt(row.allocated_amount) if row.allocated_amount is not None else flt(grand_total)
			return row.sales_person, amount
		wanted = self.filters.get("sales_person")
		for row in so_people:
			if wanted and row.sales_person == wanted:
				amount = flt(row.allocated_amount)
				if not amount and row.allocated_percentage:
					amount = flt(grand_total) * flt(row.allocated_percentage) / 100.0
				return row.sales_person, amount or flt(grand_total)
		row = so_people[0]
		amount = flt(row.allocated_amount) if row.allocated_amount is not None else flt(grand_total)
		return row.sales_person, amount

	def _build_row(
		self,
		lead,
		qt,
		customer,
		so,
		si,
		qt_sp,
		so_sp,
		lead_to_qt,
		qt_to_so,
		so_to_si,
		so_amount=None,
		si_person=None,
		si_amount=None,
	):
		qt_value = flt(qt.base_grand_total) if qt else 0
		so_value = flt(so_amount) if so else 0
		si_value = flt(si_amount) if si else 0

		if qt and qt.name not in self.summary.qt_ids:
			self.summary.qt_ids.add(qt.name)
			self.summary.qt_value += qt_value
		if so and so.name not in self.summary.so_ids:
			self.summary.so_ids.add(so.name)
			self.summary.so_value += flt(so.base_grand_total)
		if si and si.name not in self.summary.si_ids:
			self.summary.si_ids.add(si.name)
			self.summary.si_value += flt(si.base_grand_total)

		return {
			"lead": lead.name,
			"lead_name": lead.lead_name,
			"lead_created": getdate(lead.creation),
			"lead_source": lead.utm_source,
			"lead_owner": lead.lead_owner,
			"quotation": qt.name if qt else None,
			"quotation_date": qt.transaction_date if qt else None,
			"quotation_status": qt.status if qt else None,
			"quotation_grand_total": qt_value or None,
			"quotation_sales_person": qt_sp,
			"customer": customer.name if customer else None,
			"customer_name": customer.customer_name if customer else None,
			"customer_created": getdate(customer.creation) if customer else None,
			"sales_order": so.name if so else None,
			"sales_order_date": so.transaction_date if so else None,
			"sales_order_status": so.status if so else None,
			"sales_order_grand_total": so_value or None,
			"sales_order_sales_person": so_sp,
			"sales_invoice": si.name if si else None,
			"sales_invoice_date": si.posting_date if si else None,
			"sales_invoice_status": si.status if si else None,
			"sales_invoice_grand_total": si_value or None,
			"sales_invoice_sales_person": si_person,
			"lead_to_quotation_status": lead_to_qt,
			"quotation_to_so_status": qt_to_so if qt else NOT_CONVERTED,
			"so_to_si_status": so_to_si if so else NOT_CONVERTED,
			"total_quotation_value": qt_value or None,
			"total_sales_order_value": so_value or None,
			"total_invoiced_value": si_value or None,
			"currency": self.currency,
		}

	def _fetch_leads(self):
		filters = {
			"creation": ["between", [self.filters.from_date, self.filters.to_date]],
		}
		if self.filters.get("lead"):
			filters["name"] = self.filters.lead
		if self.filters.get("lead_owner"):
			filters["lead_owner"] = self.filters.lead_owner
		if self.filters.get("lead_source"):
			filters["utm_source"] = self.filters.lead_source

		# Permission-aware fetch; company blank-or-match applied below.
		leads = frappe.get_list(
			"Lead",
			filters=filters,
			fields=["name", "lead_name", "creation", "utm_source", "lead_owner", "company"],
			order_by="creation desc",
			limit_page_length=0,
		)
		company = self.filters.company
		return [d for d in leads if not d.company or d.company == company]

	def _fetch_customers(self, lead_names):
		if not lead_names:
			return {}
		rows = frappe.get_list(
			"Customer",
			filters={"lead_name": ["in", lead_names]},
			fields=["name", "customer_name", "creation", "lead_name"],
			limit_page_length=0,
		)
		return {d.lead_name: d for d in rows}

	def _fetch_opportunities(self, lead_names):
		if not lead_names:
			return []
		return frappe.get_all(
			"Opportunity",
			filters={"opportunity_from": "Lead", "party_name": ["in", lead_names]},
			fields=["name", "party_name"],
			limit_page_length=0,
		)

	def _fetch_quotations(self, lead_names, customers_by_lead, opportunities):
		if not lead_names:
			return []

		conditions = ["q.company = %(company)s", "q.docstatus < 2"]
		values = {"company": self.filters.company, "leads": lead_names}
		# Include cancelled only when status filter asks for it
		if self.qt_statuses and "Cancelled" in self.qt_statuses:
			conditions = ["q.company = %(company)s", "q.docstatus <= 2"]

		party_clauses = ["(q.quotation_to = 'Lead' AND q.party_name IN %(leads)s)"]

		opp_names = [o.name for o in opportunities]
		if opp_names:
			values["opps"] = opp_names
			party_clauses.append("q.opportunity IN %(opps)s")

		customer_names = [c.name for c in customers_by_lead.values()]
		if customer_names:
			values["customers"] = customer_names
			party_clauses.append("(q.quotation_to = 'Customer' AND q.party_name IN %(customers)s)")

		sp_select = f"q.`{QT_SALES_PERSON_FIELD}` AS sales_person" if self.has_qt_sales_person else "NULL AS sales_person"

		return frappe.db.sql(
			f"""
			SELECT
				q.name, q.transaction_date, q.status, q.base_grand_total, q.docstatus,
				q.quotation_to, q.party_name, q.opportunity, {sp_select}
			FROM `tabQuotation` q
			WHERE {" AND ".join(conditions)}
				AND ({" OR ".join(party_clauses)})
			ORDER BY q.transaction_date ASC, q.name ASC
			""",
			values=values,
			as_dict=True,
		)

	def _group_quotations_by_lead(self, quotations, lead_names, customers_by_lead, opportunities):
		opp_to_lead = {o.name: o.party_name for o in opportunities}
		customer_to_lead = {c.name: lead for lead, c in customers_by_lead.items()}
		lead_set = set(lead_names)
		grouped = {name: [] for name in lead_names}

		for qt in quotations:
			lead = None
			if qt.quotation_to == "Lead" and qt.party_name in lead_set:
				lead = qt.party_name
			elif qt.opportunity and qt.opportunity in opp_to_lead:
				lead = opp_to_lead[qt.opportunity]
			elif qt.quotation_to == "Customer" and qt.party_name in customer_to_lead:
				lead = customer_to_lead[qt.party_name]

			if lead and lead in grouped:
				grouped[lead].append(qt)
		return grouped

	def _fetch_sales_orders(self, qt_names):
		if not qt_names:
			return {}
		conditions = ["so.company = %(company)s", "so.docstatus < 2"]
		if self.so_statuses and "Cancelled" in self.so_statuses:
			conditions = ["so.company = %(company)s", "so.docstatus <= 2"]

		rows = frappe.db.sql(
			f"""
			SELECT DISTINCT
				so.name, so.transaction_date, so.status, so.base_grand_total, so.docstatus,
				soi.prevdoc_docname AS quotation
			FROM `tabSales Order` so
			INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
			WHERE {" AND ".join(conditions)}
				AND soi.prevdoc_docname IN %(quotations)s
			ORDER BY so.transaction_date ASC, so.name ASC
			""",
			{"company": self.filters.company, "quotations": qt_names},
			as_dict=True,
		)
		grouped = {}
		for row in rows:
			grouped.setdefault(row.quotation, []).append(row)
		return grouped

	def _fetch_sales_invoices(self, so_names):
		if not so_names:
			return {}
		conditions = ["si.company = %(company)s", "si.docstatus < 2", "IFNULL(si.is_return, 0) = 0"]
		if self.si_statuses and "Cancelled" in self.si_statuses:
			conditions = ["si.company = %(company)s", "si.docstatus <= 2", "IFNULL(si.is_return, 0) = 0"]

		rows = frappe.db.sql(
			f"""
			SELECT DISTINCT
				si.name, si.posting_date, si.status, si.base_grand_total, si.docstatus,
				sii.sales_order
			FROM `tabSales Invoice` si
			INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
			WHERE {" AND ".join(conditions)}
				AND sii.sales_order IN %(sales_orders)s
			ORDER BY si.posting_date ASC, si.name ASC
			""",
			{"company": self.filters.company, "sales_orders": so_names},
			as_dict=True,
		)
		grouped = {}
		for row in rows:
			grouped.setdefault(row.sales_order, []).append(row)
		return grouped

	def _fetch_sales_team(self, parenttype, parents):
		if not parents:
			return {}
		rows = frappe.get_all(
			"Sales Team",
			filters={"parenttype": parenttype, "parent": ["in", parents]},
			fields=["parent", "sales_person", "allocated_percentage", "allocated_amount"],
			order_by="idx asc",
			limit_page_length=0,
		)
		grouped = {}
		for row in rows:
			grouped.setdefault(row.parent, []).append(row)
		return grouped


def parse_multiselect(value) -> list:
	if not value:
		return []
	if isinstance(value, list):
		return [v for v in value if v]
	if isinstance(value, str):
		text = value.strip()
		if not text:
			return []
		if text.startswith("["):
			parsed = frappe.parse_json(text)
			if isinstance(parsed, list):
				return [v for v in parsed if v]
		return [part.strip() for part in text.split(",") if part.strip()]
	return [value]
