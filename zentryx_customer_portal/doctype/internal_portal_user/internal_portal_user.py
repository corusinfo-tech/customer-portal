import frappe
from frappe.model.document import Document


class InternalPortalUser(Document):
    def validate(self):
        if self.user and not frappe.db.exists("User", self.user):
            frappe.throw(f"User {self.user} does not exist.")
        if not self.access_all_customers and not self.allowed_customers:
            frappe.throw("Either enable Access All Customers or add at least one Allowed Customer.")

