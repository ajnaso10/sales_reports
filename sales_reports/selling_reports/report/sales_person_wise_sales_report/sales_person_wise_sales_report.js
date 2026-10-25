// Copyright (c) 2026, Ajnas and Contributors
// License: MIT

const REPORT_NAME = "Sales Person Wise Sales Report";
const RESTRICTION_METHOD =
	"sales_reports.selling_reports.report.sales_person_wise_sales_report.sales_person_wise_sales_report.get_restriction_context";

frappe.query_reports[REPORT_NAME] = {
	// Closed until get_restriction_context returns, so the link cannot list
	// other Sales Persons before the scope is known.
	restriction: { pending: true },

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
			get_query() {
				const ctx = frappe.query_reports[REPORT_NAME].restriction;
				if (!ctx || ctx.pending || ctx.error) {
					return { filters: { name: ["=", ""] } };
				}
				if (!ctx.restricted) {
					return {};
				}
				return {
					filters: {
						name: ["in", ctx.allowed_sales_persons || []],
					},
				};
			},
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "territory",
			label: __("Territory"),
			fieldtype: "Link",
			options: "Territory",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: function () {
				const company = frappe.query_report.get_filter_value("company");
				return {
					filters: {
						company: company,
					},
				};
			},
		},
	],

	onload(report) {
		const filter = report.get_filter("sales_person");
		if (filter) {
			filter.df.read_only = 1;
			filter.refresh();
		}

		frappe.call({
			method: RESTRICTION_METHOD,
			callback(r) {
				apply_sales_person_restriction(report, r.message || {});
			},
		});
	},
};

function apply_sales_person_restriction(report, ctx) {
	frappe.query_reports[REPORT_NAME].restriction = ctx;
	const filter = report.get_filter("sales_person");
	if (!filter) {
		return;
	}

	if (ctx.error) {
		frappe.msgprint({
			title: __("Not Permitted"),
			message: ctx.error,
			indicator: "red",
		});
		return;
	}

	if (!ctx.restricted) {
		filter.df.read_only = 0;
		filter.refresh();
		return;
	}

	if (ctx.sales_person && (ctx.read_only || !filter.get_value())) {
		filter.set_value(ctx.sales_person);
	}
	filter.df.read_only = ctx.read_only ? 1 : 0;
	filter.refresh();
}
