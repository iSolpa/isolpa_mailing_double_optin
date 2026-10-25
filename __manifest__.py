{
    'name': 'Mailing double opt-in',
    'version': '20.0.1.0.0',
    'category': 'Marketing/Email Marketing',
    'summary': 'Double opt-in, consent evidence and one-click unsubscribe for mailing contacts',
    'description': """
Contacts that join a mailing list marked "Double opt-in" stay pending (not mailable) until
they confirm through a link (/newsletter/confirm/<token>). Confirmation stores date, IP and
user agent next to the signup evidence (source, IP, consent text and version). One reminder,
then cleanup. Templates marked "Marketing (double opt-in)" only reach confirmed, subscribed,
non-blacklisted contacts and carry an unsubscribe link plus RFC 8058 one-click headers.
A landing page subscribes people through mailing.contact.doi_signup (JSON-2 or JSON-RPC).

Nothing is client specific: sender, name, address and links come from the company / website
and from the mailing_doi.* system parameters. Page texts are editable in the website editor.
Source: https://github.com/iSolpa/isolpa_mailing_double_optin
""",
    'author': 'Independent Solutions, S.A.',
    'website': 'https://github.com/iSolpa/isolpa_mailing_double_optin',
    'license': 'LGPL-3',
    'depends': ['mass_mailing', 'website'],
    'data': [
        'data/ir_config_parameter.xml',
        'data/mail_template.xml',
        'data/ir_cron.xml',
        'views/templates.xml',
        'views/backend_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
