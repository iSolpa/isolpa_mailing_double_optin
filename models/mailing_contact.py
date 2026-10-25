import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models, tools
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

DOI_STATES = [
    ('none', 'Not required'),
    ('pending', 'Pending'),
    ('confirmed', 'Confirmed'),
    ('expired', 'Expired'),
]


class MailingContact(models.Model):
    _inherit = 'mailing.contact'

    doi_state = fields.Selection(
        DOI_STATES, 'Double opt-in', default='none', required=True, index=True,
        tracking=True, copy=False)
    doi_token = fields.Char(copy=False, index='btree_not_null', groups='base.group_system')
    doi_requested_at = fields.Datetime('Confirmation requested', copy=False, readonly=True)
    doi_sent_at = fields.Datetime('Confirmation last sent', copy=False, readonly=True)
    doi_reminded_at = fields.Datetime('Reminder sent', copy=False, readonly=True)
    doi_confirmed_at = fields.Datetime('Confirmed on', copy=False, readonly=True, index=True)
    doi_confirm_ip = fields.Char('Confirmation IP', copy=False, readonly=True)
    doi_confirm_ua = fields.Char('Confirmation user agent', copy=False, readonly=True)
    doi_signup_at = fields.Datetime('Signup date', copy=False, readonly=True)
    doi_signup_ip = fields.Char('Signup IP', copy=False, readonly=True)
    doi_signup_ua = fields.Char('Signup user agent', copy=False, readonly=True)
    doi_signup_source = fields.Char('Signup source', copy=False, readonly=True)
    doi_consent_text = fields.Text('Consent text shown', copy=False, readonly=True)
    doi_consent_version = fields.Char('Consent version', copy=False, readonly=True)
    doi_customer_at = fields.Datetime('Customer since', copy=False, readonly=True)
    doi_customer_ref = fields.Char('Customer reference', copy=False, readonly=True,
                                   help="E.g. the payment/checkout id that made this contact a customer.")
    doi_customer_source = fields.Char('Customer source', copy=False, readonly=True)
    doi_unsub_token = fields.Char(
        copy=False, index='btree_not_null', groups='base.group_system',
        default=lambda self: secrets.token_urlsafe(32))
    doi_confirm_url = fields.Char(compute='_compute_doi_urls')
    doi_unsubscribe_url = fields.Char(compute='_compute_doi_urls')
    doi_sender_footer = fields.Char(compute='_compute_doi_sender_footer',
                                    help="Company name and postal address, for email footers (CAN-SPAM).")

    # ------------------------------------------------------------
    # URLS / SETTINGS / HELPERS
    # ------------------------------------------------------------

    def _compute_doi_urls(self):
        for contact in self:
            sudo = contact.sudo()
            base = contact.get_base_url()
            contact.doi_confirm_url = f'{base}/newsletter/confirm/{sudo.doi_token}' if sudo.doi_token else False
            contact.doi_unsubscribe_url = f'{base}/newsletter/unsubscribe/{sudo.doi_unsub_token}' if sudo.doi_unsub_token else False

    def _compute_doi_sender_footer(self):
        info = self._doi_public_info()
        footer = ' · '.join(p for p in (info['name'], info['address']) if p)
        for contact in self:
            contact.doi_sender_footer = footer

    def _doi_unsubscribe_url(self, one_click=False):
        self.ensure_one()
        sudo = self.sudo()
        if not sudo.doi_unsub_token:
            sudo.doi_unsub_token = secrets.token_urlsafe(32)
        url = f'{self.get_base_url()}/newsletter/unsubscribe/{sudo.doi_unsub_token}'
        return f'{url}/one-click' if one_click else url

    @api.model
    def _doi_param(self, key, default=0):
        """ Integer system parameter mailing_doi.<key> (Settings > Technical > Parameters). """
        return self.env['ir.config_parameter'].sudo().get_int(f'mailing_doi.{key}', default) or default

    @api.model
    def _doi_param_str(self, key, default=''):
        return (self.env['ir.config_parameter'].sudo().get_str(f'mailing_doi.{key}', default) or default).strip()

    @api.model
    def _doi_public_info(self):
        """ What the public pages and the confirmation email show: all from the company /
        website, overridable with mailing_doi.* parameters. """
        company = self.env.company.sudo()  # rendered for the public user on the website pages
        # public texts follow the website language, not the language of whoever triggers the send
        website = self.env['website'].sudo().search([('company_id', '=', company.id)], limit=1)
        partner = company.partner_id.with_context(lang=website.default_lang_id.code or 'en_US')
        city_line = ' '.join(p for p in (partner.city and partner.city + ',', partner.state_id.code, partner.zip) if p).strip(' ,')
        address = ', '.join(p for p in (partner.street, partner.street2, city_line, partner.country_id.name) if p)
        website = company.website or self.get_base_url()
        return {
            'name': company.name,
            'address': address,
            'website': website,
            'signup_url': self._doi_param_str('signup_url') or website,
            'terms_url': self._doi_param_str('terms_url'),
            'privacy_url': self._doi_param_str('privacy_url'),
            'expire_days': self._doi_param('expire_days', 7),
        }

    @api.model
    def _doi_trigger_mail_queue(self):
        """ The mail queue cron runs hourly; a confirmation email that waits an hour loses
        signups. Wake the queue right after this transaction commits. """
        cron = self.env.ref('mail.ir_cron_mail_scheduler_action', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def _doi_lists(self):
        self.ensure_one()
        return self.subscription_ids.filtered(lambda s: s.list_id.doi_required)

    def _doi_is_mailable(self):
        """ Marketing mail may go out: confirmed, still subscribed somewhere, not blacklisted. """
        self.ensure_one()
        return (
            self.doi_state == 'confirmed'
            and bool(self.email_normalized)
            and not self.is_blacklisted
            and any(not sub.opt_out for sub in self.subscription_ids)
        )

    # ------------------------------------------------------------
    # ORM HOOKS — every way into a list (API, website form, import, UI)
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        contacts = super().create(vals_list)
        contacts._doi_check()
        return contacts

    def write(self, vals):
        res = super().write(vals)
        if {'list_ids', 'subscription_ids', 'email'} & set(vals):
            self._doi_check()
        return res

    def _doi_check(self):
        """ Start double opt-in for contacts that joined a DOI list and never confirmed.
        Context ``doi_skip`` bypasses it. Importing contacts who ALREADY consented: create
        them with doi_state='confirmed'. """
        if self.env.context.get('doi_skip'):
            return
        for contact in self.sudo():
            if contact.doi_state not in ('none', 'expired') or not contact.email_normalized:
                continue
            if any(not sub.opt_out for sub in contact._doi_lists()):
                contact._doi_request()

    # ------------------------------------------------------------
    # DOUBLE OPT-IN FLOW
    # ------------------------------------------------------------

    def _doi_request(self, reminder=False):
        """ Put the contact in pending and (re)send the confirmation email. The token is kept
        across resends so the first email's link keeps working until it expires. """
        template = self.env.ref('isolpa_mailing_double_optin.mail_template_doi_confirm', raise_if_not_found=False)
        now = fields.Datetime.now()
        for contact in self.sudo():
            vals = {}
            if contact.doi_state != 'pending' or not contact.doi_token:
                vals.update({
                    'doi_state': 'pending',
                    'doi_token': secrets.token_urlsafe(32),
                    'doi_requested_at': now,
                    'doi_reminded_at': False,
                })
            if reminder:
                vals['doi_reminded_at'] = now
            vals['doi_sent_at'] = now
            contact.with_context(doi_skip=True).write(vals)
            if template:
                template.send_mail(contact.id, force_send=False)
                contact._doi_trigger_mail_queue()
            else:
                _logger.warning('mailing double opt-in: confirmation template missing, nothing sent to contact %s', contact.id)

    @api.model
    def doi_signup(self, email, name=None, list_ids=None, source=None, ip=None,
                   user_agent=None, consent_text=None, consent_version=None):
        """ Entry point for a landing page (JSON-2 ``/json/2/mailing.contact/doi_signup`` or
        JSON-RPC). Finds or creates the contact by email, stores consent evidence, subscribes it
        to ``list_ids`` (double opt-in lists only) and sends the confirmation email, throttled
        for repeat signups. Works for a user with no access rights on mailing contacts.

        :return: dict(contact_id, state, sent)
        """
        email_normalized = tools.email_normalize(email)
        if not email_normalized:
            return {'contact_id': False, 'state': 'invalid_email', 'sent': False}
        Contact = self.sudo().with_context(doi_skip=True)
        contact = Contact.search([('email_normalized', '=', email_normalized)], limit=1)
        evidence = {'doi_signup_at': fields.Datetime.now()}
        for fname, value in (
            ('doi_signup_ip', ip),
            ('doi_signup_ua', (user_agent or '')[:500]),
            ('doi_signup_source', source),
            ('doi_consent_text', consent_text),
            ('doi_consent_version', consent_version),
        ):
            if value:  # a repeat signup without evidence keeps what the first one stored
                evidence[fname] = value
        if not contact:
            contact = Contact.create(dict(evidence, email=email, name=name or False))
        elif contact.doi_state != 'confirmed':
            # keep the latest signup evidence until confirmation; never overwrite a confirmed consent record
            contact.write(evidence)
        if name and not contact.name:
            contact.name = name
        # only double opt-in lists: this entry point may be called by a low-privilege landing user
        doi_list_ids = self.env['mailing.list'].sudo().search([
            ('id', 'in', [int(i) for i in list_ids or []]), ('doi_required', '=', True)]).ids
        for list_id in doi_list_ids:
            sub = contact.subscription_ids.filtered(lambda s: s.list_id.id == list_id)
            if not sub:
                self.env['mailing.subscription'].sudo().with_context(doi_skip=True).create(
                    {'contact_id': contact.id, 'list_id': list_id})
            elif sub.opt_out:
                sub.with_context(doi_skip=True).opt_out = False

        sent = False
        if contact.doi_state == 'confirmed':
            pass
        elif contact.doi_state == 'pending':
            throttle = timedelta(minutes=self._doi_param('resend_throttle_minutes', 60))
            if not contact.doi_sent_at or contact.doi_sent_at < fields.Datetime.now() - throttle:
                contact._doi_request()
                sent = True
        elif any(not sub.opt_out for sub in contact._doi_lists()):
            contact._doi_request()
            sent = True
        return {'contact_id': contact.id, 'state': contact.doi_state, 'sent': sent}

    @api.model
    def doi_record_customer(self, email, name=None, tag_names=None, source=None, reference=None):
        """ Entry point for a purchase (e.g. a paid reservation from the payment webhook).
        Records the contact as a CUSTOMER — this is not marketing consent and subscribes to no
        list: customers get the service emails they paid for (non-marketing templates sent to
        their tag), and marketing only if they also confirm a double opt-in.

        :return: dict(contact_id, doi_state)
        """
        # unlike doi_signup, this is NOT for the low-privilege landing user: it tags customers
        if not (self.env.is_superuser() or self.env.user.has_group('mass_mailing.group_mass_mailing_user')):
            raise AccessError(self.env._('Only email marketing users can record customers.'))
        email_normalized = tools.email_normalize(email)
        if not email_normalized:
            return {'contact_id': False, 'doi_state': 'invalid_email'}
        Contact = self.sudo().with_context(doi_skip=True)
        contact = Contact.search([('email_normalized', '=', email_normalized)], limit=1)
        if not contact:
            contact = Contact.create({'email': email, 'name': name or False})
        Tag = self.env['res.partner.category'].sudo()
        tags = Tag.browse()
        for tag_name in tag_names or []:
            tags |= Tag.search([('name', '=ilike', tag_name)], limit=1) or Tag.create({'name': tag_name})
        vals = {'tag_ids': [(4, tag.id) for tag in tags]}
        if not contact.doi_customer_at:
            vals['doi_customer_at'] = fields.Datetime.now()
        if reference:
            vals['doi_customer_ref'] = reference
        if source:
            vals['doi_customer_source'] = source
        if name and not contact.name:
            vals['name'] = name
        contact.write(vals)
        return {'contact_id': contact.id, 'doi_state': contact.doi_state}

    def _doi_confirm(self, ip=None, user_agent=None):
        """ Called from the POST of /newsletter/confirm/<token>. Writing doi_state='confirmed'
        is what a welcome automation rule listens to. """
        for contact in self.sudo().filtered(lambda c: c.doi_state == 'pending'):
            vals = {
                'doi_state': 'confirmed',
                'doi_confirmed_at': fields.Datetime.now(),
                'doi_confirm_ip': ip or False,
                'doi_confirm_ua': (user_agent or '')[:500] or False,
                'doi_token': False,
            }
            try:
                with self.env.cr.savepoint():
                    contact.with_context(doi_skip=True).write(vals)
                note = self.env._('Subscription confirmed (double opt-in) from IP %s', ip or '?')
            except Exception:
                # a broken automation (e.g. the welcome template) must never lose the consent itself:
                # record it without triggering automations and leave a trace for whoever runs the list
                _logger.exception('mailing double opt-in: automation failed on confirmation of contact %s; '
                                  'confirmation recorded without automations', contact.id)
                self.env.cr.execute(
                    'UPDATE mailing_contact SET doi_state=%s, doi_confirmed_at=%s, doi_confirm_ip=%s, '
                    'doi_confirm_ua=%s, doi_token=NULL WHERE id=%s',
                    ('confirmed', vals['doi_confirmed_at'], vals['doi_confirm_ip'] or None,
                     vals['doi_confirm_ua'] or None, contact.id))
                contact.invalidate_recordset()
                note = self.env._('Subscription confirmed (double opt-in) from IP %s. WARNING: an automation '
                                  'rule failed on confirmation, so no welcome email was sent. Check the server log.', ip or '?')
            contact.message_post(body=note)

    def _doi_unsubscribe(self):
        """ Unsubscribe from everything: opt out of every list and blacklist the address. """
        for contact in self.sudo():
            contact.subscription_ids.filtered(lambda s: not s.opt_out).write({'opt_out': True})
            if contact.email_normalized:
                self.env['mail.blacklist'].sudo()._add(
                    contact.email_normalized, message=self.env._('Unsubscribed through the newsletter unsubscribe link'))

    @api.model
    def _doi_find_by_token(self, field, token):
        if not token or len(token) < 20:
            return self.browse()
        return self.sudo().search([(field, '=', token)], limit=1)

    # ------------------------------------------------------------
    # CRON — one reminder, then cleanup
    # ------------------------------------------------------------

    @api.model
    def _cron_doi(self):
        now = fields.Datetime.now()
        remind_before = now - timedelta(hours=self._doi_param('reminder_hours', 48))
        expire_before = now - timedelta(days=self._doi_param('expire_days', 7))
        Contact = self.sudo()

        to_remind = Contact.search([
            ('doi_state', '=', 'pending'),
            ('doi_reminded_at', '=', False),
            ('doi_requested_at', '<', remind_before),
            ('doi_requested_at', '>=', expire_before),
        ])
        to_remind._doi_request(reminder=True)

        expired = Contact.search([
            ('doi_state', '=', 'pending'),
            ('doi_requested_at', '<', expire_before),
        ])
        # contacts carrying a "keep" tag (e.g. they paid a reservation) are kept as expired, never deleted
        keep_tags = {t.strip().lower() for t in self._doi_param_str('keep_tags').split(',') if t.strip()}
        keep = expired.filtered(lambda c: keep_tags & {(t.name or '').strip().lower() for t in c.tag_ids})
        keep.with_context(doi_skip=True).write({'doi_state': 'expired', 'doi_token': False})
        (expired - keep).unlink()
        _logger.info('mailing double opt-in cron: %s reminded, %s expired kept, %s deleted',
                     len(to_remind), len(keep), len(expired - keep))
