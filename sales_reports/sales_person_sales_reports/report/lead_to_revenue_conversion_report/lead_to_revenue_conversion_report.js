// Copyright (c) 2026, Ajnas and Contributors
// License: MIT

const QUOTATION_STATUSES = [
	"Draft",
	"Open",
	"Replied",
	"Partially Ordered",
	"Ordered",
	"Lost",
	"Cancelled",
	"Expired",
];

const SALES_ORDER_STATUSES = [
	"Draft",
	"On Hold",
	"To Pay",
	"To Deliver and Bill",
	"To Bill",
	"To Deliver",
	"Completed",
	"Cancelled",
	"Closed",
];

const SALES_INVOICE_STATUSES = [
	"Draft",
	"Return",
	"Credit Note Issued",
	"Submitted",
	"Paid",
	"Partly Paid",
	"Unpaid",
	"Unpaid and Discounted",
	"Partly Paid and Discounted",
	"Overdue and Discounted",
	"Overdue",
	"Cancelled",
	"Internal Transfer",
];

function status_options(values, txt) {
	const needle = (txt || "").toLowerCase();
	return values
		.filter((v) => !needle || v.toLowerCase().includes(needle))
		.map((v) => ({ value: v, description: v }));
}

frappe.query_reports["Lead-to-Revenue Conversion Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1],
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{
			fieldname: "lead_owner",
			label: __("Lead Owner"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "lead_source",
			label: __("Lead Source"),
			fieldtype: "Link",
			options: "UTM Source",
		},
		{
			fieldname: "lead",
			label: __("Lead"),
			fieldtype: "Link",
			options: "Lead",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "quotation_status",
			label: __("Quotation Status"),
			fieldtype: "MultiSelectList",
			get_data: (txt) => status_options(QUOTATION_STATUSES, txt),
		},
		{
			fieldname: "sales_order_status",
			label: __("Sales Order Status"),
			fieldtype: "MultiSelectList",
			get_data: (txt) => status_options(SALES_ORDER_STATUSES, txt),
		},
		{
			fieldname: "sales_invoice_status",
			label: __("Sales Invoice Status"),
			fieldtype: "MultiSelectList",
			get_data: (txt) => status_options(SALES_INVOICE_STATUSES, txt),
		},
	],
};
