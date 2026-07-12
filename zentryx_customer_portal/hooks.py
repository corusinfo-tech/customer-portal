app_name = "zentryx_customer_portal"
app_title = "Zentryx Customer Portal"
app_publisher = "Zentryx Global Systems Pvt Ltd"
app_description = "Modern customer self-service portal for ERPNext, CRM and Helpdesk."
app_email = "support@zentryx.com"
app_license = "MIT"

required_apps = ["frappe", "erpnext"]

website_context = {
    "favicon": "/assets/zentryx_customer_portal/images/favicon.ico",
    "splash_image": "/assets/zentryx_customer_portal/images/logo.png",
}

app_include_css = []
app_include_js = []
web_include_css = ["/assets/zentryx_customer_portal/css/portal.css"]
web_include_js = ["/assets/zentryx_customer_portal/js/portal.js"]

doctype_js = {}

fixtures = [
    {"dt": "Role", "filters": [["role_name", "in", ["Customer Portal Manager"]]]},
    {"dt": "Custom DocPerm", "filters": [["parent", "in", [
        "Portal Customer",
        "Portal Department",
        "Portal Permission Group",
        "Portal User",
        "Portal Sync Log",
        "Portal SLA Policy",
        "Portal Audit Log",
        "AMC Contract",
        "Network Device",
        "Maintenance Schedule",
        "Portal Announcement",
        "Customer Document",
        "SLA Report",
        "Customer Portal Settings",
    ]]]},
]

website_route_rules = [
    {"from_route": "/helpdesk", "to_route": "portal"},
    {"from_route": "/support", "to_route": "portal/support"},
]

get_website_user_home_page = "zentryx_customer_portal.boot.get_website_user_home_page"
boot_session = "zentryx_customer_portal.boot.get_bootinfo"
after_install = "zentryx_customer_portal.install.after_install"
after_migrate = "zentryx_customer_portal.install.after_migrate"

scheduler_events = {
    "daily": [
        "zentryx_customer_portal.sync.scheduled_sync",
    ],
}

permission_query_conditions = {
    "Sales Invoice": "zentryx_customer_portal.permissions.sales_invoice_query",
    "Sales Order": "zentryx_customer_portal.permissions.sales_order_query",
    "Quotation": "zentryx_customer_portal.permissions.quotation_query",
    "Delivery Note": "zentryx_customer_portal.permissions.delivery_note_query",
    "Payment Entry": "zentryx_customer_portal.permissions.get_payment_permission_query_conditions",
    "Project": "zentryx_customer_portal.permissions.get_project_permission_query_conditions",
    "Issue": "zentryx_customer_portal.permissions.get_ticket_permission_query_conditions",
    "HD Ticket": "zentryx_customer_portal.permissions.get_ticket_permission_query_conditions",
    "AMC Contract": "zentryx_customer_portal.permissions.amc_contract_query",
    "Network Device": "zentryx_customer_portal.permissions.network_device_query",
    "Maintenance Schedule": "zentryx_customer_portal.permissions.maintenance_schedule_query",
    "Customer Document": "zentryx_customer_portal.permissions.customer_document_query",
    "SLA Report": "zentryx_customer_portal.permissions.sla_report_query",
}

has_permission = {
    "Sales Invoice": "zentryx_customer_portal.permissions.has_customer_permission",
    "Sales Order": "zentryx_customer_portal.permissions.has_customer_permission",
    "Quotation": "zentryx_customer_portal.permissions.has_customer_permission",
    "Delivery Note": "zentryx_customer_portal.permissions.has_customer_permission",
    "Payment Entry": "zentryx_customer_portal.permissions.has_customer_permission",
    "Project": "zentryx_customer_portal.permissions.has_customer_permission",
    "Issue": "zentryx_customer_portal.permissions.has_customer_permission",
    "HD Ticket": "zentryx_customer_portal.permissions.has_customer_permission",
    "AMC Contract": "zentryx_customer_portal.permissions.has_customer_permission",
    "Network Device": "zentryx_customer_portal.permissions.has_customer_permission",
    "Maintenance Schedule": "zentryx_customer_portal.permissions.has_customer_permission",
    "Customer Document": "zentryx_customer_portal.permissions.has_customer_permission",
    "SLA Report": "zentryx_customer_portal.permissions.has_customer_permission",
}
