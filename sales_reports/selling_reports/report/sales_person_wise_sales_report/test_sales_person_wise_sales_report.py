# Copyright (c) 2026, Ajnas and Contributors
# License: MIT

"""Role scope for Sales Person Wise Sales Report.

The Sales Person tree in these tests is not a permission table. Own Only stays
on the linked node even when that node is a parent. Team adds descendants.
See All ignores the tree. A user with more than one role gets the broadest.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.desk.query_report import run as run_query_report
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from sales_reports.install import ensure_sales_reports_settings, ensure_see_all_report_access
from sales_reports.selling_reports.report.sales_person_wise_sales_report.sales_person_wise_sales_report import (
	SCOPE_SEE_ALL,
	execute,
	get_restriction_context,
)

EXTRA_TEST_RECORD_DEPENDENCIES = ["Sales Invoice"]

COMPANY = "_Test Company"

OWN_LEAD_AMOUNT = 10
OWN_CHILD_AMOUNT = 77
TEAM_LEAD_AMOUNT = 50
TEAM_REP_AMOUNT = 100
MULTI_LEAD_AMOUNT = 5
MULTI_CHILD_AMOUNT = 30
OUTSIDE_AMOUNT = 400


class TestSalesPersonWiseSalesReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		ensure_sales_reports_settings()
		ensure_see_all_report_access()

		posting_date = nowdate()

		if not frappe.db.exists("Company", COMPANY):
			frappe.throw(f"{COMPANY} is missing. Sales Invoice test records should create it.")

		root = _sales_person_root()
		gender = _gender()
		customer = _make_customer()

		cls.own_lead_user = _make_user("spwsr-own-lead@example.com", ["Sales User"])
		cls.team_user = _make_user("spwsr-team-lead@example.com", ["Sales Manager"])
		cls.team_rep_user = _make_user("spwsr-team-rep@example.com", ["Sales User"])
		cls.multi_user = _make_user("spwsr-multi@example.com", ["Sales User", "Sales Manager"])
		cls.see_all_user = _make_user("spwsr-see-all@example.com", ["System Manager"])
		cls.see_all_and_own_user = _make_user(
			"spwsr-see-all-and-own@example.com", ["Sales User", "System Manager"]
		)
		cls.no_link_user = _make_user("spwsr-no-link@example.com", ["Sales User"])
		cls.accounts_user = _make_user("spwsr-accounts@example.com", ["Accounts User"])

		own_lead_employee = _make_employee(cls.own_lead_user, gender)
		team_employee = _make_employee(cls.team_user, gender)
		team_rep_employee = _make_employee(cls.team_rep_user, gender)
		multi_employee = _make_employee(cls.multi_user, gender)

		# Own Only user is the parent. The child has sales, and must stay hidden.
		cls.own_lead = _make_sales_person("_Test SPWSR Own Lead", root, own_lead_employee, is_group=1)
		cls.own_child = _make_sales_person("_Test SPWSR Own Child", cls.own_lead, is_group=0)
		cls.team_lead = _make_sales_person("_Test SPWSR Team Lead", root, team_employee, is_group=1)
		cls.team_rep = _make_sales_person(
			"_Test SPWSR Team Rep", cls.team_lead, team_rep_employee, is_group=0
		)
		cls.multi_lead = _make_sales_person("_Test SPWSR Multi Lead", root, multi_employee, is_group=1)
		cls.multi_child = _make_sales_person("_Test SPWSR Multi Child", cls.multi_lead, is_group=0)
		cls.outside = _make_sales_person("_Test SPWSR Outside", root, is_group=0)

		_make_invoice(customer, cls.own_lead, OWN_LEAD_AMOUNT, posting_date)
		_make_invoice(customer, cls.own_child, OWN_CHILD_AMOUNT, posting_date)
		_make_invoice(customer, cls.team_lead, TEAM_LEAD_AMOUNT, posting_date)
		_make_invoice(customer, cls.team_rep, TEAM_REP_AMOUNT, posting_date)
		_make_invoice(customer, cls.multi_lead, MULTI_LEAD_AMOUNT, posting_date)
		_make_invoice(customer, cls.multi_child, MULTI_CHILD_AMOUNT, posting_date)
		_make_invoice(customer, cls.outside, OUTSIDE_AMOUNT, posting_date)

		cls.all_sales_persons = [
			cls.own_lead,
			cls.own_child,
			cls.team_lead,
			cls.team_rep,
			cls.multi_lead,
			cls.multi_child,
			cls.outside,
		]
		cls.grand_total = (
			OWN_LEAD_AMOUNT
			+ OWN_CHILD_AMOUNT
			+ TEAM_LEAD_AMOUNT
			+ TEAM_REP_AMOUNT
			+ MULTI_LEAD_AMOUNT
			+ MULTI_CHILD_AMOUNT
			+ OUTSIDE_AMOUNT
		)
		cls.filters = {
			"company": COMPANY,
			"from_date": posting_date,
			"to_date": posting_date,
			"customer": customer,
		}
		frappe.clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_default_role_lists(self):
		doc = frappe.get_doc("Sales Reports Settings")
		self.assertEqual([row.role for row in doc.own_only_roles], ["Sales User"])
		self.assertEqual([row.role for row in doc.team_roles], ["Sales Manager"])
		self.assertEqual([row.role for row in doc.see_all_roles], ["System Manager"])

	def test_report_ref_doctype_is_sales_person(self):
		self.assertEqual(
			frappe.db.get_value("Report", "Sales Person Wise Sales Report", "ref_doctype"),
			"Sales Person",
		)

	def test_own_role_sees_only_own_rows_and_total(self):
		frappe.set_user(self.team_rep_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], "own")
		self.assertEqual(ctx["sales_person"], self.team_rep)
		self.assertEqual(ctx["allowed_sales_persons"], [self.team_rep])
		self.assertTrue(ctx["read_only"])
		self.assertIsNone(ctx["error"])

		detail, total = self._run()
		self.assertEqual([row["sales_person"] for row in detail], [self.team_rep])
		self.assertAlmostEqual(detail[0]["net_sales"], TEAM_REP_AMOUNT, places=2)
		self.assertEqual(detail[0]["total_invoices"], 1)
		self.assertAlmostEqual(total["net_sales"], TEAM_REP_AMOUNT, places=2)
		self.assertEqual(total["total_invoices"], 1)

	def test_own_role_on_a_parent_node_excludes_descendants(self):
		frappe.set_user(self.own_lead_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], "own")
		self.assertEqual(ctx["allowed_sales_persons"], [self.own_lead])
		self.assertNotIn(self.own_child, ctx["allowed_sales_persons"])

		for filters in (self.filters, {**self.filters, "sales_person": self.own_lead}):
			detail, total = self._run(filters)
			self.assertEqual([row["sales_person"] for row in detail], [self.own_lead])
			self.assertAlmostEqual(detail[0]["net_sales"], OWN_LEAD_AMOUNT, places=2)
			self.assertAlmostEqual(total["net_sales"], OWN_LEAD_AMOUNT, places=2)
			self.assertEqual(total["total_invoices"], 1)

	def test_rep_requesting_another_sales_person_is_rejected(self):
		frappe.set_user(self.team_rep_user)
		with self.assertRaises(frappe.PermissionError) as cm:
			execute({**self.filters, "sales_person": self.outside})
		self.assertIn(self.outside, str(cm.exception))

		frappe.set_user(self.own_lead_user)
		with self.assertRaises(frappe.PermissionError) as cm:
			execute({**self.filters, "sales_person": self.own_child})
		self.assertIn(self.own_child, str(cm.exception))

	def test_team_role_sees_linked_person_and_descendants(self):
		frappe.set_user(self.team_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], "team")
		self.assertEqual(ctx["sales_person"], self.team_lead)
		self.assertCountEqual(ctx["allowed_sales_persons"], [self.team_lead, self.team_rep])
		self.assertFalse(ctx["read_only"])

		detail, total = self._run()
		self.assertCountEqual([row["sales_person"] for row in detail], [self.team_lead, self.team_rep])
		self.assertAlmostEqual(total["net_sales"], TEAM_LEAD_AMOUNT + TEAM_REP_AMOUNT, places=2)
		self.assertEqual(total["total_invoices"], 2)
		self.assertNotIn(self.outside, [row["sales_person"] for row in detail])
		self.assertNotIn(self.own_child, [row["sales_person"] for row in detail])

	def test_team_role_requesting_outside_sales_person_is_rejected(self):
		frappe.set_user(self.team_user)
		with self.assertRaises(frappe.PermissionError) as cm:
			execute({**self.filters, "sales_person": self.outside})
		self.assertIn(self.outside, str(cm.exception))

	def test_see_all_role_sees_everything(self):
		frappe.set_user(self.see_all_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], SCOPE_SEE_ALL)
		self.assertFalse(ctx["restricted"])
		self.assertIsNone(ctx["error"])

		detail, total = self._run()
		self.assertCountEqual([row["sales_person"] for row in detail], self.all_sales_persons)
		self.assertAlmostEqual(total["net_sales"], self.grand_total, places=2)
		self.assertEqual(total["total_invoices"], len(self.all_sales_persons))

	def test_administrator_is_unrestricted(self):
		frappe.set_user("Administrator")
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], SCOPE_SEE_ALL)
		self.assertFalse(ctx["restricted"])

	def test_sales_user_and_sales_manager_uses_team_scope(self):
		frappe.set_user(self.multi_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], "team")
		self.assertFalse(ctx["read_only"])
		self.assertCountEqual(ctx["allowed_sales_persons"], [self.multi_lead, self.multi_child])

		detail, total = self._run()
		self.assertCountEqual([row["sales_person"] for row in detail], [self.multi_lead, self.multi_child])
		self.assertAlmostEqual(total["net_sales"], MULTI_LEAD_AMOUNT + MULTI_CHILD_AMOUNT, places=2)
		self.assertEqual(total["total_invoices"], 2)

	def test_system_manager_and_sales_user_sees_everything_without_a_link(self):
		frappe.set_user(self.see_all_and_own_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], SCOPE_SEE_ALL)
		self.assertIsNone(ctx["error"])

		detail, total = self._run()
		self.assertCountEqual([row["sales_person"] for row in detail], self.all_sales_persons)
		self.assertAlmostEqual(total["net_sales"], self.grand_total, places=2)

	def test_linked_role_without_sales_person_is_rejected(self):
		frappe.set_user(self.no_link_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], "own")
		self.assertIn("No Sales Person is linked", ctx["error"])
		with self.assertRaises(frappe.PermissionError) as cm:
			execute(self.filters)
		self.assertIn("No Sales Person is linked", str(cm.exception))

	def test_role_not_in_settings_is_rejected(self):
		frappe.set_user(self.accounts_user)
		ctx = get_restriction_context()
		self.assertEqual(ctx["scope"], "none")
		self.assertIn("Sales Reports Settings", ctx["error"])
		with self.assertRaises(frappe.PermissionError) as cm:
			execute(self.filters)
		self.assertIn("Sales Reports Settings", str(cm.exception))

	def test_client_supplied_allow_list_is_ignored(self):
		frappe.set_user(self.team_rep_user)
		filters = {**self.filters, "allowed_sales_persons": list(self.all_sales_persons)}
		detail, total = self._run(filters)
		self.assertEqual([row["sales_person"] for row in detail], [self.team_rep])
		self.assertAlmostEqual(total["net_sales"], TEAM_REP_AMOUNT, places=2)
		self.assertEqual(total["total_invoices"], 1)

	def test_see_all_list_in_settings_grants_access(self):
		doc = frappe.get_doc("Sales Reports Settings")
		doc.append("see_all_roles", {"role": "Accounts User"})
		doc.save(ignore_permissions=True)
		try:
			frappe.set_user(self.accounts_user)
			ctx = get_restriction_context()
			self.assertEqual(ctx["scope"], SCOPE_SEE_ALL)
			detail, _total = self._run()
			self.assertCountEqual([row["sales_person"] for row in detail], self.all_sales_persons)
		finally:
			frappe.set_user("Administrator")
			self._remove_see_all_role("Accounts User")

	def test_settings_reject_a_role_in_two_scopes(self):
		doc = frappe.get_doc("Sales Reports Settings")
		if not any(row.role == "Sales User" for row in doc.own_only_roles):
			doc.append("own_only_roles", {"role": "Sales User"})
		doc.append("team_roles", {"role": "Sales User"})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_query_report_run_as_sales_user(self):
		frappe.set_user(self.team_rep_user)
		self.assertTrue(frappe.has_permission("Sales Person", "report"))
		detail, total = self._desk_run()
		self.assertEqual([row["sales_person"] for row in detail], [self.team_rep])
		self.assertAlmostEqual(detail[0]["net_sales"], TEAM_REP_AMOUNT, places=2)
		self.assertEqual(detail[0]["total_invoices"], 1)
		self.assertAlmostEqual(total["net_sales"], TEAM_REP_AMOUNT, places=2)
		self.assertEqual(total["total_invoices"], 1)

	def test_query_report_run_as_sales_manager(self):
		frappe.set_user(self.team_user)
		self.assertTrue(frappe.has_permission("Sales Person", "report"))
		detail, total = self._desk_run()
		self.assertCountEqual([row["sales_person"] for row in detail], [self.team_lead, self.team_rep])
		self.assertAlmostEqual(total["net_sales"], TEAM_LEAD_AMOUNT + TEAM_REP_AMOUNT, places=2)
		self.assertEqual(total["total_invoices"], 2)

	def test_query_report_run_as_see_all_system_manager(self):
		# Stock ERPNext gives System Manager read on Company and no read or
		# select on Customer. The desk sends a Link filter only when it has a
		# value, so this call sends the Company link the way the form does on
		# open, and keeps Customer in the filters so the query stays on this
		# test's invoices.
		frappe.set_user(self.see_all_user)
		self.assertTrue(frappe.has_permission("Sales Person", "report"))
		detail, total = self._desk_run(link_fields=("company",))
		self.assertCountEqual([row["sales_person"] for row in detail], self.all_sales_persons)
		self.assertAlmostEqual(total["net_sales"], self.grand_total, places=2)
		self.assertEqual(total["total_invoices"], len(self.all_sales_persons))

	def test_query_report_run_as_accounts_user_added_to_see_all(self):
		frappe.set_user(self.accounts_user)
		with self.assertRaises(frappe.PermissionError) as cm:
			self._desk_run()
		self.assertIn("Sales Person", str(cm.exception))

		frappe.set_user("Administrator")
		doc = frappe.get_doc("Sales Reports Settings")
		doc.append("see_all_roles", {"role": "Accounts User"})
		doc.save(ignore_permissions=True)
		try:
			frappe.set_user(self.accounts_user)
			self.assertTrue(frappe.has_permission("Sales Person", "report"))
			detail, total = self._desk_run()
			self.assertCountEqual([row["sales_person"] for row in detail], self.all_sales_persons)
			self.assertAlmostEqual(total["net_sales"], self.grand_total, places=2)
			self.assertEqual(total["total_invoices"], len(self.all_sales_persons))
		finally:
			frappe.set_user("Administrator")
			self._remove_see_all_role("Accounts User")

	def test_query_report_run_as_a_see_all_role_that_is_not_on_the_report(self):
		role = "SPWSR See All"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)
		user = _make_user("spwsr-custom-see-all@example.com", [role])
		doc = frappe.get_doc("Sales Reports Settings")
		doc.append("see_all_roles", {"role": role})
		doc.save(ignore_permissions=True)
		try:
			custom_role = frappe.db.get_value(
				"Custom Role", {"report": "Sales Person Wise Sales Report"}, "name"
			)
			custom_roles = frappe.get_all("Has Role", filters={"parent": custom_role}, pluck="role")
			self.assertIn("Sales User", custom_roles)
			self.assertIn("Sales Manager", custom_roles)
			self.assertIn(role, custom_roles)

			frappe.set_user(user)
			self.assertTrue(frappe.has_permission("Sales Person", "report"))
			# No Company permission on this role, so the link check is not what
			# this case covers. An empty js_filters list still goes through
			# Report.is_permitted and the Sales Person report permission.
			detail, total = self._desk_run(link_fields=())
			self.assertCountEqual([row["sales_person"] for row in detail], self.all_sales_persons)
			self.assertAlmostEqual(total["net_sales"], self.grand_total, places=2)
		finally:
			frappe.set_user("Administrator")
			self._remove_see_all_role(role)

	def test_company_user_permission_on_sales_invoice_is_enforced(self):
		other = frappe.db.get_value("Company", {"name": ["!=", COMPANY]}, "name")
		if not other:
			self.skipTest(
				"A second Company is required to point a User Permission away from the report company."
			)

		unrelated = _make_user_permission(self.team_rep_user, "Company", other, "Employee")
		try:
			frappe.set_user(self.team_rep_user)
			detail, _total = self._run()
			self.assertEqual([row["sales_person"] for row in detail], [self.team_rep])
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User Permission", unrelated, ignore_permissions=True, force=True)

		blocked = _make_user_permission(self.team_rep_user, "Company", other)
		try:
			frappe.set_user(self.team_rep_user)
			with self.assertRaises(frappe.PermissionError) as cm:
				execute(self.filters)
			self.assertIn(COMPANY, str(cm.exception))
			with self.assertRaises(frappe.PermissionError):
				self._desk_run()
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User Permission", blocked, ignore_permissions=True, force=True)

		allowed = _make_user_permission(self.team_rep_user, "Company", COMPANY, "Sales Invoice")
		try:
			frappe.set_user(self.team_rep_user)
			detail, total = self._desk_run()
			self.assertEqual([row["sales_person"] for row in detail], [self.team_rep])
			self.assertAlmostEqual(total["net_sales"], TEAM_REP_AMOUNT, places=2)
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User Permission", allowed, ignore_permissions=True, force=True)

	def test_customer_user_permission_limits_rows_when_the_filter_is_empty(self):
		other_customer = _make_customer("_Test SPWSR Other Customer")
		_make_invoice(other_customer, self.team_rep, 25, self.filters["from_date"])
		permission = _make_user_permission(
			self.team_rep_user, "Customer", self.filters["customer"], "Sales Invoice"
		)
		try:
			frappe.set_user(self.team_rep_user)
			filters = {key: value for key, value in self.filters.items() if key != "customer"}
			detail, total = self._run(filters)
			self.assertEqual([row["sales_person"] for row in detail], [self.team_rep])
			self.assertAlmostEqual(detail[0]["net_sales"], TEAM_REP_AMOUNT, places=2)
			self.assertAlmostEqual(total["net_sales"], TEAM_REP_AMOUNT, places=2)
			self.assertEqual(total["total_invoices"], 1)
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User Permission", permission, ignore_permissions=True, force=True)

	def test_client_supplied_user_permission_constraints_are_ignored(self):
		frappe.set_user(self.team_rep_user)
		filters = {
			**self.filters,
			"user_permission_constraints": {
				"customer": {"docs": ["_Test Missing Customer"], "strict": 1},
			},
		}
		detail, total = self._run(filters)
		self.assertEqual([row["sales_person"] for row in detail], [self.team_rep])
		self.assertAlmostEqual(total["net_sales"], TEAM_REP_AMOUNT, places=2)

	def _run(self, filters=None):
		_columns, data = execute(filters or self.filters)
		return self._split(data)

	def _desk_run(self, filters=None, link_fields=None):
		filters = dict(filters or self.filters)
		options = {
			"company": "Company",
			"sales_person": "Sales Person",
			"customer": "Customer",
			"territory": "Territory",
			"item_group": "Item Group",
			"cost_center": "Cost Center",
		}
		if link_fields is None:
			link_fields = tuple(options)
		js_filters = [
			{"fieldname": fieldname, "fieldtype": "Link", "options": options[fieldname]}
			for fieldname in link_fields
			if filters.get(fieldname)
		]
		result = run_query_report(
			"Sales Person Wise Sales Report",
			filters=filters,
			are_default_filters=False,
			ignore_prepared_report=True,
			js_filters=js_filters,
		)
		return self._split(result["result"])

	def _split(self, data):
		label = _("Total")
		detail = [row for row in data if row.get("sales_person") != label]
		totals = [row for row in data if row.get("sales_person") == label]
		self.assertEqual(len(totals), 1, msg=data)
		return detail, totals[0]

	def _remove_see_all_role(self, role):
		doc = frappe.get_doc("Sales Reports Settings")
		changed = False
		for row in list(doc.see_all_roles):
			if row.role == role:
				doc.remove(row)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)


def _sales_person_root():
	if not frappe.db.exists("Sales Person", "Sales Team"):
		frappe.throw("Sales Person root 'Sales Team' is missing. ERPNext creates it during setup.")
	if not frappe.db.get_value("Sales Person", "Sales Team", "is_group"):
		frappe.db.set_value("Sales Person", "Sales Team", "is_group", 1)
	return "Sales Team"


def _gender():
	if frappe.db.exists("Gender", "Female"):
		return "Female"
	existing = frappe.db.get_value("Gender", {}, "name")
	if existing:
		return existing
	return frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert(ignore_permissions=True).name


def _make_customer(customer_name="_Test SPWSR Customer"):
	existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
	if existing:
		return existing
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if not group or not territory:
		frappe.throw("A leaf Customer Group and Territory are required.")
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name,
			"customer_group": group,
			"territory": territory,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_user_permission(user, allow, for_value, applicable_for=None):
	doc = frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": user,
			"allow": allow,
			"for_value": for_value,
			"apply_to_all_doctypes": 0 if applicable_for else 1,
			"applicable_for": applicable_for,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_user(email, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@", 1)[0],
				"send_welcome_email": 0,
				"user_type": "System User",
				"roles": [{"role": role} for role in roles],
			}
		)
		user.insert(ignore_permissions=True)
		return user.name

	user.enabled = 1
	have = {row.role for row in user.roles}
	for role in roles:
		if role not in have:
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	return user.name


def _make_employee(user, gender):
	existing = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if existing:
		frappe.db.set_value("Employee", existing, "status", "Active")
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"naming_series": "HR-EMP-",
			"first_name": user.split("@", 1)[0],
			"company": COMPANY,
			"user_id": user,
			"status": "Active",
			"gender": gender,
			"date_of_birth": "1990-05-08",
			"date_of_joining": "2013-01-01",
			"create_user_permission": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_sales_person(name, parent, employee=None, is_group=0):
	if frappe.db.exists("Sales Person", name):
		doc = frappe.get_doc("Sales Person", name)
		doc.parent_sales_person = parent
		doc.is_group = is_group
		doc.enabled = 1
		doc.employee = employee
		doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.get_doc(
		{
			"doctype": "Sales Person",
			"sales_person_name": name,
			"parent_sales_person": parent,
			"is_group": is_group,
			"enabled": 1,
			"employee": employee,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_invoice(customer, sales_person, rate, posting_date):
	from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

	si = create_sales_invoice(
		customer=customer,
		company=COMPANY,
		posting_date=posting_date,
		qty=1,
		rate=rate,
		do_not_save=True,
	)
	si.set("sales_team", [])
	si.append("sales_team", {"sales_person": sales_person, "allocated_percentage": 100})
	si.insert(ignore_permissions=True)
	si.submit()
	return si.name
