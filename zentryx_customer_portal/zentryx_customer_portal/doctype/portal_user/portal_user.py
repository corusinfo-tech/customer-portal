import frappe
from frappe.model.document import Document


class PortalUser(Document):
    def validate(self):
        if self.user and not frappe.db.exists("User", self.user):
            frappe.throw(f"User {self.user} does not exist.")
        if self.portal_customer:
            customer = frappe.get_doc("Portal Customer", self.portal_customer)
            self.erpnext_customer = customer.erpnext_customer
        if self.user_type == "Customer Staff" and not self.permission_group:
            frappe.throw("Customer Staff requires a Permission Group.")

