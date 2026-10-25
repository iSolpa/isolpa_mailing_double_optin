import secrets

from . import controllers, models


def post_init_hook(env):
    """ Existing contacts get their unsubscribe token (new ones get it by default). """
    for contact in env['mailing.contact'].sudo().with_context(active_test=False).search([('doi_unsub_token', '=', False)]):
        contact.doi_unsub_token = secrets.token_urlsafe(32)
