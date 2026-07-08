# Zentryx Customer Portal

`zentryx_customer_portal` is a production-ready Frappe v16 application that provides a modern customer self-service portal for ERPNext, CRM v2 and Helpdesk without modifying ERPNext core.

## Features

- Website-user-only `/portal` dashboard
- Customer-scoped support tickets, invoices, quotations, sales orders, projects, payments and delivery notes
- Custom DocTypes for AMC contracts, network devices, maintenance schedules, portal announcements, customer documents and SLA reports
- Bootstrap 5 responsive portal UI with light/dark mode
- REST API endpoints with explicit customer ownership checks
- Permission query hooks and document-level permission hooks
- Dashboard summary, notification bell, global search and integration-ready network status placeholders

## Install

From a Bench environment running Frappe v16, ERPNext v16 and Python 3.12:

```bash
bench get-app https://github.com/zentryx/zentryx_customer_portal.git
bench --site your-site.local install-app zentryx_customer_portal
bench --site your-site.local migrate
bench --site your-site.local clear-cache
```

After installation, website users are sent to `/portal` after login. Desk access is not required for customers.

## Configuration

Open **Customer Portal Settings** in Desk as a System Manager and configure:

- Enabled modules
- Logo and theme colors
- Footer and support contact
- Landing page

## Development

```bash
bench --site your-site.local run-tests --app zentryx_customer_portal
```

This app does not modify ERPNext, CRM or Helpdesk core. All integrations use Frappe hooks, whitelisted methods and standard DocTypes when available.




crm  erpnext  frappe  helpdesk  hrms  india_compliance  infintrix_theme  insights  it_management  lms  payments  telephony  wiki  zentryx_customer_portal.zip