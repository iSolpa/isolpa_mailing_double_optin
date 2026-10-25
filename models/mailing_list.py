from odoo import fields, models


class MailingList(models.Model):
    _inherit = 'mailing.list'

    doi_required = fields.Boolean(
        'Double opt-in', default=False,
        help="New subscribers stay pending (not mailable) until they confirm by email.")

    def _mailing_get_opt_out_list(self, mailing):
        """ Unconfirmed contacts on double opt-in lists never receive mass mailings. """
        opt_out = super()._mailing_get_opt_out_list(mailing)
        lists = self or mailing.contact_list_ids
        doi_lists = lists.filtered('doi_required')
        if doi_lists:
            unconfirmed = self.env['mailing.contact'].sudo().search([
                ('list_ids', 'in', doi_lists.ids),
                ('doi_state', '!=', 'confirmed'),
            ]).mapped('email_normalized')
            opt_out = set(opt_out) | {e for e in unconfirmed if e}
        return opt_out
