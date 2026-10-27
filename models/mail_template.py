from odoo import fields, models


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    doi_marketing = fields.Boolean(
        'Marketing (double opt-in)',
        help="Only sent to confirmed, subscribed, non-blacklisted mailing contacts, with "
             "one-click unsubscribe headers. Use it for every welcome / nurture / launch email, "
             "and put object.doi_unsubscribe_url in its footer.")

    def _doi_gated(self):
        return self.doi_marketing and self.model == 'mailing.contact'

    def send_mail_batch(self, res_ids, force_send=False, raise_exception=False, email_values=None,
                        email_layout_xmlid=False):
        """ Every email to a mailing contact carries OUR List-Unsubscribe headers: otherwise the
        relay (e.g. Brevo) adds its own, and a tap on it puts the address on the relay's blocklist,
        silently dropping even the service emails the customer paid for. Our unsubscribe stops
        marketing only. Marketing templates are additionally gated on _doi_is_mailable(). """
        self.ensure_one()
        if self.model != 'mailing.contact':
            return super().send_mail_batch(
                res_ids, force_send=force_send, raise_exception=raise_exception,
                email_values=email_values, email_layout_xmlid=email_layout_xmlid)
        mails = self.env['mail.mail'].sudo()
        contacts = self.env['mailing.contact'].sudo().browse(res_ids)
        if self._doi_gated():
            contacts = contacts.filtered(lambda c: c._doi_is_mailable())
        for contact in contacts:
            values = dict(email_values or {})
            values['headers'] = repr({
                'List-Unsubscribe': f'<{contact._doi_unsubscribe_url(one_click=True)}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
            })
            mails |= super().send_mail_batch(
                contact.ids, force_send=force_send, raise_exception=raise_exception,
                email_values=values, email_layout_xmlid=email_layout_xmlid)
        # service emails to contacts too (e.g. a launch-day link): the queue cron is hourly
        if mails and not force_send:
            self.env['mailing.contact']._doi_trigger_mail_queue()
        return mails

    def send_mail(self, res_id, force_send=False, raise_exception=False, email_values=None,
                  email_layout_xmlid=False):
        self.ensure_one()
        if not self._doi_gated():
            return super().send_mail(
                res_id, force_send=force_send, raise_exception=raise_exception,
                email_values=email_values, email_layout_xmlid=email_layout_xmlid)
        # the batch version may skip the contact (not mailable): no mail, no IndexError
        mails = self.send_mail_batch(
            [res_id], force_send=force_send, raise_exception=raise_exception,
            email_values=email_values, email_layout_xmlid=email_layout_xmlid)
        return mails[:1].id
