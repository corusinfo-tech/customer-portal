import frappe
from frappe.model.document import Document


class PortalTicketMetadata(Document):
    def validate(self):
        if self.ticket_doctype not in ("HD Ticket", "Issue"):
            frappe.throw("Ticket DocType must be HD Ticket or Issue.")
        if self.ticket and not frappe.db.exists(self.ticket_doctype, self.ticket):
            frappe.throw(f"{self.ticket_doctype} {self.ticket} does not exist.")
        if self.primary_ticket and self.primary_ticket == self.ticket:
            frappe.throw("Primary ticket cannot be the same ticket.")

