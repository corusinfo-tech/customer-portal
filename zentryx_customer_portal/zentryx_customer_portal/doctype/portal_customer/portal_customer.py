import frappe
from frappe.model.document import Document


class PortalCustomer(Document):
    def validate(self):
        if self.erpnext_customer and not frappe.db.exists("Customer", self.erpnext_customer):
            frappe.throw(f"ERPNext Customer {self.erpnext_customer} does not exist.")

