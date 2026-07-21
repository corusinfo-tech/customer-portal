from frappe import _


def get_data():
    return [
        {
            "module_name": "Zentryx Customer Portal",
            "category": "Modules",
            "label": _("Zentryx Customer Portal"),
            "color": "#0f766e",
            "icon": "octicon octicon-globe",
            "type": "module",
            "description": _("Customer portal settings, AMC contracts, network devices and documents."),
        }
    ]

