from odoo import http
from odoo.http import request


class MailingDoubleOptin(http.Controller):
    """ GET never changes anything: link scanners and click-tracking redirects follow links.
    Confirmation and unsubscribe happen on POST (form button, CSRF-protected), except the
    RFC 8058 one-click POST that mail clients send without a session. """

    def _render(self, template, values=None):
        Contact = request.env['mailing.contact']
        values = dict(values or {}, doi_info=Contact._doi_public_info())
        if Contact._doi_param('minimal_layout', 1):
            # transactional pages: no site header/footer (stock ones may still carry placeholder content)
            values.update(no_header=True, no_footer=True, no_copyright=True)
        return request.render(f'isolpa_mailing_double_optin.{template}', values)

    def _client(self):
        req = request.httprequest
        return req.remote_addr, (req.headers.get('User-Agent') or '')[:500]

    def _contact(self, field, token):
        return request.env['mailing.contact']._doi_find_by_token(field, token)

    # ---- confirm -------------------------------------------------------

    @http.route('/newsletter/confirm/<string:token>', type='http', auth='public', website=True,
                methods=['GET'], sitemap=False)
    def doi_confirm_page(self, token, **kw):
        contact = self._contact('doi_token', token)
        if not contact or contact.doi_state != 'pending':
            return self._render('page_link_invalid')
        return self._render('page_confirm', {'token': token})

    @http.route('/newsletter/confirm/<string:token>', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def doi_confirm_post(self, token, **kw):
        contact = self._contact('doi_token', token)
        if not contact or contact.doi_state != 'pending':
            return self._render('page_link_invalid')
        ip, ua = self._client()
        contact._doi_confirm(ip=ip, user_agent=ua)
        return self._render('page_confirmed')

    # ---- unsubscribe ---------------------------------------------------

    @http.route('/newsletter/unsubscribe/<string:token>', type='http', auth='public', website=True,
                methods=['GET'], sitemap=False)
    def doi_unsubscribe_page(self, token, **kw):
        if not self._contact('doi_unsub_token', token):
            return self._render('page_link_invalid')
        return self._render('page_unsubscribe', {'token': token})

    @http.route('/newsletter/unsubscribe/<string:token>', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def doi_unsubscribe_post(self, token, **kw):
        contact = self._contact('doi_unsub_token', token)
        if contact:
            contact._doi_unsubscribe()
        return self._render('page_unsubscribed')

    # csrf disabled: called by the mail client (List-Unsubscribe-Post), no session
    @http.route('/newsletter/unsubscribe/<string:token>/one-click', type='http', auth='public',
                methods=['POST'], csrf=False, sitemap=False)
    def doi_unsubscribe_oneclick(self, token, **kw):
        contact = self._contact('doi_unsub_token', token)
        if contact:
            contact._doi_unsubscribe()
        return request.make_response('', status=200)
