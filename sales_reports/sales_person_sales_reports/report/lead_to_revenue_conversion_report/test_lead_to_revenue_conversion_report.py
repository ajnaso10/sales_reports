# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""End-to-end tests for Lead-to-Revenue Conversion Report covering all plan scenarios."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from sales_reports.sales_person_sales_reports.report.lead_to_revenue_conversion_report.lead_to_revenue_conversion_report import (
	CONVERTED,
	NOT_CONVERTED,
	QT_SALES_PERSON_FIELD,
	execute,
	parse_multiselect,
)

PREFIX = "LTR-E2E"


class TestLeadToRevenueConversionReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		cls.currency = frappe.db.get_value("Company", cls.company, "default_currency")
		cls.item = _ensure_service_item()
		cls.price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
		cls.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		cls.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
		cls.sp_a, cls.sp_b = _two_sales_persons()
		cls.alt_user = _alt_user()
		cls.has_qt_sp = frappe.get_meta("Quotation").has_field(QT_SALES_PERSON_FIELD)
		existing_sources = frappe.get_all("UTM Source", pluck="name", limit_page_length=1)
		cls.utm_source = existing_sources[0] if existing_sources else _ensure_utm_source(f"{PREFIX} Source")
		cls.created = []
		frappe.db.commit()

	def setUp(self):
		# Site has SO workflows that attach PDF; wkhtmltopdf is broken on this machine.
		self._patches = [
			patch("frappe.utils.pdf.get_pdf", return_value=b"%PDF-1.4"),
			patch("frappe.attach_print", return_value={}),
		]
		for p in self._patches:
			p.start()
		frappe.flags.mute_emails = True

	def tearDown(self):
		for p in getattr(self, "_patches", []):
			p.stop()
		frappe.flags.mute_emails = False
		frappe.db.rollback()

	def _filters(self, **extra):
		filters = {
			"from_date": add_days(today(), -1),
			"to_date": today(),
			"company": self.company,
		}
		filters.update(extra)
		return filters

	def _rows_for_lead(self, lead_name, **extra_filters):
		_columns, data, message = execute(self._filters(lead=lead_name, **extra_filters))
		return data, message

	def _make_lead(self, tag: str, lead_owner: str | None = None, source: str | None = None):
		payload = {
			"doctype": "Lead",
			"first_name": PREFIX,
			"last_name": tag,
			"email_id": f"{PREFIX.lower()}.{tag.lower()}.{frappe.generate_hash(length=8)}@example.com",
			"company": self.company,
			"company_name": f"{PREFIX} {tag} Co",
			"lead_owner": lead_owner or "Administrator",
		}
		if source:
			payload["utm_source"] = source
		lead = frappe.get_doc(payload).insert(ignore_permissions=True)
		self.created.append(("Lead", lead.name))
		return lead

	def _make_quotation(self, lead, rate=100, qty=2, submit=True, sales_person=None):
		qt = frappe.new_doc("Quotation")
		qt.quotation_to = "Lead"
		qt.party_name = lead.name
		qt.company = self.company
		qt.transaction_date = today()
		qt.order_type = "Sales"
		qt.currency = self.currency
		qt.conversion_rate = 1
		if self.price_list:
			qt.selling_price_list = self.price_list
		qt.append(
			"items",
			{
				"item_code": self.item,
				"qty": qty,
				"rate": rate,
			},
		)
		if self.has_qt_sp and sales_person:
			qt.set(QT_SALES_PERSON_FIELD, sales_person)
		qt.insert(ignore_permissions=True)
		if submit:
			qt.submit()
		self.created.append(("Quotation", qt.name))
		return qt

	def _make_so_from_qt(self, quotation, qty=None, sales_persons=None):
		from erpnext.selling.doctype.quotation.quotation import make_sales_order

		so = make_sales_order(quotation.name)
		so.delivery_date = add_days(today(), 7)
		if qty is not None and so.items:
			so.items[0].qty = qty
		if self.has_qt_sp and sales_persons:
			# Prefer custom field so crm_custom sync is predictable before submit
			so.set(QT_SALES_PERSON_FIELD, sales_persons[0][0])
		so.insert(ignore_permissions=True)
		so.submit()
		if sales_persons and len(sales_persons) > 1:
			_set_sales_team_after_submit(so.name, "Sales Order", sales_persons)
		self.created.append(("Sales Order", so.name))
		# Customer created from lead during make_sales_order
		customer = frappe.db.get_value("Sales Order", so.name, "customer")
		if customer:
			self.created.append(("Customer", customer))
		return frappe.get_doc("Sales Order", so.name)

	def _make_si_from_so(self, sales_order, qty=None, sales_persons=None):
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		si = make_sales_invoice(sales_order.name)
		si.update_stock = 0
		if qty is not None and si.items:
			si.items[0].qty = qty
		if self.has_qt_sp and sales_persons:
			si.set(QT_SALES_PERSON_FIELD, sales_persons[0][0])
		si.insert(ignore_permissions=True)
		si.submit()
		if sales_persons and len(sales_persons) > 1:
			_set_sales_team_after_submit(si.name, "Sales Invoice", sales_persons)
		self.created.append(("Sales Invoice", si.name))
		return frappe.get_doc("Sales Invoice", si.name)

	# --- unit helpers ---

	def test_parse_multiselect(self):
		self.assertEqual(parse_multiselect(None), [])
		self.assertEqual(parse_multiselect(["Open", "Ordered"]), ["Open", "Ordered"])
		self.assertEqual(parse_multiselect('["Open","Lost"]'), ["Open", "Lost"])
		self.assertEqual(parse_multiselect("Open, Lost"), ["Open", "Lost"])

	def test_validate_filters(self):
		with self.assertRaises(frappe.ValidationError):
			execute({"from_date": today(), "to_date": today()})
		with self.assertRaises(frappe.ValidationError):
			execute({"company": self.company, "from_date": today(), "to_date": add_days(today(), -1)})

	# --- scenario 1: one lead, multiple quotations ---

	def test_one_lead_multiple_quotations(self):
		lead = self._make_lead("MultiQT")
		qt1 = self._make_quotation(lead, rate=100, qty=1, sales_person=self.sp_a)
		qt2 = self._make_quotation(lead, rate=200, qty=1, sales_person=self.sp_a)

		rows, _message = self._rows_for_lead(lead.name)
		qt_ids = {r["quotation"] for r in rows}
		self.assertEqual(qt_ids, {qt1.name, qt2.name})
		self.assertEqual(len(rows), 2)
		for row in rows:
			self.assertEqual(row["lead"], lead.name)
			self.assertEqual(row["lead_to_quotation_status"], CONVERTED)
			self.assertEqual(row["quotation_to_so_status"], NOT_CONVERTED)
			self.assertFalse(row.get("sales_order"))

	# --- scenario 6: quotation without sales order ---

	def test_quotation_without_sales_order(self):
		lead = self._make_lead("QTNoSO")
		qt = self._make_quotation(lead, sales_person=self.sp_a)
		rows, _message = self._rows_for_lead(lead.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["quotation"], qt.name)
		self.assertIsNone(rows[0].get("sales_order"))
		self.assertEqual(rows[0]["quotation_to_so_status"], NOT_CONVERTED)
		self.assertEqual(rows[0]["so_to_si_status"], NOT_CONVERTED)

	# --- scenario 2: one quotation → multiple sales orders ---

	def test_one_quotation_multiple_sales_orders(self):
		lead = self._make_lead("MultiSO")
		qt = self._make_quotation(lead, rate=50, qty=10, sales_person=self.sp_a)
		so1 = self._make_so_from_qt(qt, qty=4, sales_persons=[(self.sp_a, 100)])
		so2 = self._make_so_from_qt(qt, qty=6, sales_persons=[(self.sp_a, 100)])

		rows, message = self._rows_for_lead(lead.name)
		so_ids = {r["sales_order"] for r in rows}
		self.assertEqual(so_ids, {so1.name, so2.name})
		self.assertGreaterEqual(len(rows), 2)
		for row in rows:
			self.assertEqual(row["quotation"], qt.name)
			self.assertEqual(row["quotation_to_so_status"], CONVERTED)
			self.assertEqual(row["so_to_si_status"], NOT_CONVERTED)
			self.assertFalse(row.get("sales_invoice"))
		self.assertIn("Quotations (1)", message or "")
		self.assertIn("Sales Orders (2)", message or "")

	# --- scenario 7: sales order without invoice ---

	def test_sales_order_without_invoice(self):
		lead = self._make_lead("SONoSI")
		qt = self._make_quotation(lead, rate=80, qty=2, sales_person=self.sp_a)
		so = self._make_so_from_qt(qt, sales_persons=[(self.sp_a, 100)])
		rows, _message = self._rows_for_lead(lead.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["sales_order"], so.name)
		self.assertIsNone(rows[0].get("sales_invoice"))
		self.assertEqual(rows[0]["so_to_si_status"], NOT_CONVERTED)

	# --- scenario 3: one SO → multiple invoices ---

	def test_one_sales_order_multiple_invoices(self):
		lead = self._make_lead("MultiSI")
		qt = self._make_quotation(lead, rate=40, qty=10, sales_person=self.sp_a)
		so = self._make_so_from_qt(qt, sales_persons=[(self.sp_a, 100)])
		si1 = self._make_si_from_so(so, qty=4, sales_persons=[(self.sp_a, 100)])
		si2 = self._make_si_from_so(so, qty=6, sales_persons=[(self.sp_a, 100)])

		rows, message = self._rows_for_lead(lead.name)
		si_ids = {r["sales_invoice"] for r in rows}
		self.assertEqual(si_ids, {si1.name, si2.name})
		for row in rows:
			self.assertEqual(row["sales_order"], so.name)
			self.assertEqual(row["so_to_si_status"], CONVERTED)
			self.assertEqual(row["lead_to_quotation_status"], CONVERTED)
			self.assertTrue(row.get("customer"))
		self.assertIn("Sales Orders (1)", message or "")
		self.assertIn("Invoices (2)", message or "")

	# --- scenario 4: multiple salespersons / allocated amounts ---

	def test_multiple_salespersons_allocated_amounts(self):
		lead = self._make_lead("MultiSP")
		qt = self._make_quotation(lead, rate=100, qty=2, sales_person=self.sp_a)
		so = self._make_so_from_qt(
			qt,
			sales_persons=[(self.sp_a, 60), (self.sp_b, 40)],
		)

		rows, _message = self._rows_for_lead(lead.name)
		persons = {r["sales_order_sales_person"] for r in rows}
		self.assertEqual(persons, {self.sp_a, self.sp_b})
		self.assertEqual(len(rows), 2)

		by_sp = {r["sales_order_sales_person"]: r for r in rows}
		total = flt(so.base_grand_total)
		self.assertAlmostEqual(flt(by_sp[self.sp_a]["sales_order_grand_total"]), total * 0.6, places=2)
		self.assertAlmostEqual(flt(by_sp[self.sp_b]["sales_order_grand_total"]), total * 0.4, places=2)
		# Full SO total must not be repeated as each row's value
		self.assertNotAlmostEqual(flt(by_sp[self.sp_a]["sales_order_grand_total"]), total, places=2)

	# --- scenario 5: Lead Owner ≠ Sales Person ---

	def test_different_lead_owner_and_sales_person(self):
		lead = self._make_lead("OwnerSP", lead_owner=self.alt_user)
		qt = self._make_quotation(lead, sales_person=self.sp_a)
		so = self._make_so_from_qt(qt, sales_persons=[(self.sp_a, 100)])

		rows, _message = self._rows_for_lead(lead.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["lead_owner"], self.alt_user)
		self.assertEqual(rows[0]["sales_order_sales_person"], self.sp_a)
		if self.has_qt_sp:
			self.assertEqual(rows[0]["quotation_sales_person"], self.sp_a)

		# Lead Owner filter
		rows_owner, _ = self._rows_for_lead(lead.name, lead_owner=self.alt_user)
		self.assertEqual(len(rows_owner), 1)
		rows_other, _ = self._rows_for_lead(lead.name, lead_owner="Administrator")
		self.assertEqual(len(rows_other), 0)

		# Sales Person filter still finds the row
		rows_sp, _ = self._rows_for_lead(lead.name, sales_person=self.sp_a)
		self.assertEqual(len(rows_sp), 1)

	# --- scenario 8: draft and cancelled ---

	def test_draft_and_cancelled_transactions(self):
		lead = self._make_lead("DraftCancel")
		draft_qt = self._make_quotation(lead, rate=10, qty=1, submit=False, sales_person=self.sp_a)
		live_qt = self._make_quotation(lead, rate=20, qty=1, sales_person=self.sp_a)
		cancelled_qt = self._make_quotation(lead, rate=30, qty=1, sales_person=self.sp_a)
		cancelled_qt.cancel()

		rows, _message = self._rows_for_lead(lead.name)
		qt_ids = {r["quotation"] for r in rows}
		self.assertIn(draft_qt.name, qt_ids)
		self.assertIn(live_qt.name, qt_ids)
		self.assertNotIn(cancelled_qt.name, qt_ids)

		draft_row = next(r for r in rows if r["quotation"] == draft_qt.name)
		self.assertEqual(draft_row["quotation_status"], "Draft")

		# Explicit Cancelled filter includes cancelled quotation
		rows_c, _ = self._rows_for_lead(lead.name, quotation_status=["Cancelled"])
		self.assertEqual({r["quotation"] for r in rows_c}, {cancelled_qt.name})

	# --- scenario 9: sales person filter across journey ---

	def test_sales_person_filter_across_journey(self):
		lead = self._make_lead("SPFilter")
		qt = self._make_quotation(lead, rate=100, qty=2, sales_person=self.sp_a)
		so = self._make_so_from_qt(qt, sales_persons=[(self.sp_a, 50), (self.sp_b, 50)])
		si = self._make_si_from_so(so, sales_persons=[(self.sp_b, 100)])

		rows_a, _ = self._rows_for_lead(lead.name, sales_person=self.sp_a)
		self.assertTrue(rows_a)
		for row in rows_a:
			self.assertIn(self.sp_a, {row.get("quotation_sales_person"), row.get("sales_order_sales_person"), row.get("sales_invoice_sales_person")})

		rows_b, _ = self._rows_for_lead(lead.name, sales_person=self.sp_b)
		self.assertTrue(rows_b)
		for row in rows_b:
			self.assertIn(self.sp_b, {row.get("quotation_sales_person"), row.get("sales_order_sales_person"), row.get("sales_invoice_sales_person")})

		# Unrelated sales person → no rows for this lead
		other_sp = frappe.db.get_value(
			"Sales Person",
			{"enabled": 1, "name": ["not in", [self.sp_a, self.sp_b]]},
			"name",
		)
		if other_sp:
			rows_x, _ = self._rows_for_lead(lead.name, sales_person=other_sp)
			self.assertEqual(rows_x, [])

		# Full path still visible without SP filter
		rows_all, message = self._rows_for_lead(lead.name)
		self.assertTrue(any(r.get("sales_invoice") == si.name for r in rows_all))
		self.assertTrue(message)

	# --- lead with no quotation ---

	def test_lead_without_quotation(self):
		lead = self._make_lead("NoQT")
		rows, _message = self._rows_for_lead(lead.name)
		self.assertEqual(len(rows), 1)
		self.assertIsNone(rows[0].get("quotation"))
		self.assertEqual(rows[0]["lead_to_quotation_status"], NOT_CONVERTED)

	# --- lead source / customer filters ---

	def test_lead_source_and_customer_filters(self):
		source = _ensure_utm_source(f"{PREFIX} FilterSrc")
		lead = self._make_lead("SrcCust", source=source)
		qt = self._make_quotation(lead, sales_person=self.sp_a)
		so = self._make_so_from_qt(qt, sales_persons=[(self.sp_a, 100)])
		customer = frappe.db.get_value("Sales Order", so.name, "customer")

		rows, _ = self._rows_for_lead(lead.name, lead_source=source)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["lead_source"], source)

		rows_c, _ = self._rows_for_lead(lead.name, customer=customer)
		self.assertEqual(len(rows_c), 1)
		self.assertEqual(rows_c[0]["customer"], customer)

		rows_wrong, _ = self._rows_for_lead(lead.name, lead_source=_ensure_utm_source(f"{PREFIX} OtherSrc"))
		self.assertEqual(rows_wrong, [])

	# --- summary does not inflate on fan-out ---

	def test_summary_deduplicates_values(self):
		lead = self._make_lead("Dedup")
		qt = self._make_quotation(lead, rate=100, qty=4, sales_person=self.sp_a)
		so = self._make_so_from_qt(qt, sales_persons=[(self.sp_a, 50), (self.sp_b, 50)])
		si1 = self._make_si_from_so(so, qty=2, sales_persons=[(self.sp_a, 100)])
		si2 = self._make_si_from_so(so, qty=2, sales_persons=[(self.sp_a, 100)])

		_rows, message = self._rows_for_lead(lead.name)
		# One QT, one SO, two SIs in deduplicated summary
		self.assertIn("Quotations (1)", message)
		self.assertIn("Sales Orders (1)", message)
		self.assertIn("Invoices (2)", message)
		self.assertAlmostEqual(flt(si1.base_grand_total) + flt(si2.base_grand_total), flt(so.base_grand_total), places=2)


def _ensure_service_item() -> str:
	"""Prefer non-asset sales item. Avoid creating Items (site Server Scripts block insert)."""
	item = frappe.db.sql(
		"""
		SELECT name FROM `tabItem`
		WHERE disabled = 0
			AND is_sales_item = 1
			AND IFNULL(is_fixed_asset, 0) = 0
			AND IFNULL(has_serial_no, 0) = 0
			AND IFNULL(has_batch_no, 0) = 0
		ORDER BY is_stock_item ASC, name ASC
		LIMIT 1
		"""
	)
	if not item:
		frappe.throw("No suitable sales Item available for E2E tests")
	return item[0][0]


def _two_sales_persons() -> tuple[str, str]:
	names = frappe.get_all("Sales Person", filters={"enabled": 1}, pluck="name", limit_page_length=2)
	if len(names) < 2:
		for label in (f"{PREFIX} SPA", f"{PREFIX} SPB"):
			if not frappe.db.exists("Sales Person", label):
				frappe.get_doc({"doctype": "Sales Person", "sales_person_name": label, "enabled": 1}).insert(
					ignore_permissions=True
				)
			names.append(label)
	return names[0], names[1]


def _alt_user() -> str:
	user = frappe.db.get_value(
		"User",
		{"name": ["not in", ["Administrator", "Guest"]], "enabled": 1},
		"name",
	)
	if user:
		return user
	email = f"{PREFIX.lower()}.owner@example.com"
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": PREFIX,
				"last_name": "Owner",
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		u.append("roles", {"role": "Sales User"})
		u.insert(ignore_permissions=True)
	return email


def _ensure_utm_source(name: str) -> str:
	if frappe.db.exists("UTM Source", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "UTM Source",
			"__newname": name,
			"slug": frappe.scrub(name)[:140],
			"description": name,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def _set_sales_team_after_submit(parent: str, parenttype: str, sales_persons: list[tuple[str, float]]):
	"""Replace Sales Team after submit so crm_custom before_validate cannot wipe multi-SP rows."""
	doc = frappe.get_doc(parenttype, parent)
	doc.set("sales_team", [])
	for person, pct in sales_persons:
		doc.append(
			"sales_team",
			{
				"sales_person": person,
				"allocated_percentage": pct,
			},
		)
	doc.flags.ignore_validate_update_after_submit = True
	doc.save(ignore_permissions=True)
	# Ensure allocated_amount is populated for the report
	doc.reload()
	if not any(flt(r.allocated_amount) for r in doc.sales_team):
		total = flt(doc.base_net_total or doc.base_grand_total)
		for row in doc.sales_team:
			row.allocated_amount = total * flt(row.allocated_percentage) / 100.0
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)
