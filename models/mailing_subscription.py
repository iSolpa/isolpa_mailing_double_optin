from odoo import api, models


class MailingSubscription(models.Model):
    _inherit = 'mailing.subscription'

    @api.model_create_multi
    def create(self, vals_list):
        subscriptions = super().create(vals_list)
        subscriptions.contact_id._doi_check()
        return subscriptions

    def write(self, vals):
        res = super().write(vals)
        if 'opt_out' in vals and not vals['opt_out']:
            self.contact_id._doi_check()
        return res
