# Mailing double opt-in (`isolpa_mailing_double_optin`) — Odoo 20

Double opt-in, consent evidence and one-click unsubscribe for Odoo Email Marketing
(`mass_mailing`). Generic: sender, company name, postal address and links come from the
company, the website and the `mailing_doi.*` system parameters; nothing is tied to one client.

Depends on `mass_mailing` and `website`. Tested on Odoo 20.0 Community. License LGPL-3.
Author: Independent Solutions, S.A. (iSolpa).

## What it does
| Piece | Behaviour |
|---|---|
| Mailing list → **Double opt-in** checkbox | Anyone added to the list (API, website form, import, by hand) is `pending` and gets no mass mailing until they confirm. Pending is *not* opt-out: the subscription exists, it is just not mailable yet. |
| Confirmation email | Template «Mailing: confirm your subscription». From = company email (the outgoing server's `from_filter` rewrites it if needed), Reply-To = catchall. Sent within seconds (the mail queue cron is triggered). Neutral English text, editable. |
| `/newsletter/confirm/<token>` | GET shows a page with a button (link scanners and click trackers open links); POST with CSRF confirms and stores date, real IP and user agent. Random 256-bit token, expires after `expire_days`. If an automation rule fails on confirmation, the confirmation is still saved and a note is posted on the contact. |
| Template → **Marketing (double opt-in)** checkbox | Only reaches confirmed, subscribed, non-blacklisted contacts. Footer: `object.doi_sender_footer` (name + postal address) and link `object.doi_unsubscribe_url`. |
| List-Unsubscribe headers | Every template email sent to a mailing contact carries `List-Unsubscribe` + `List-Unsubscribe-Post: One-Click` (RFC 8058) pointing to Odoo. This also stops SMTP relays that add their own unsubscribe header (e.g. Brevo) from adding one that would block the address at the relay. |
| `/newsletter/unsubscribe/<token>` | GET shows a page; POST or one-click = unsubscribed from every list + blacklisted. |
| Hourly cron | One reminder after `reminder_hours`; after `expire_days` the pending contact is deleted, unless it carries a tag listed in `keep_tags` (then it stays as `expired`). |
| `mailing.contact.doi_signup(...)` | Signup from a landing page (JSON-2 `POST /json/2/mailing.contact/doi_signup` or JSON-RPC): `email, name, list_ids` (double opt-in lists only), `source, ip, user_agent, consent_text, consent_version`. Returns `{contact_id, state, sent}`. Resend throttled to one per `resend_throttle_minutes`. Works with an internal user that has no rights on contacts. |
| `mailing.contact.doi_record_customer(...)` | A purchase (e.g. payment webhook): `email, name, tag_names, source, reference`. Tags the customer **without** subscribing them or recording marketing consent. Requires the Email Marketing user group (a landing key cannot call it). |

## Marketing vs. service email
- **Marketing** (news, nurture, launch): double opt-in only → templates with the Marketing checkbox.
- **Service / transactional** (what the customer bought: access link, order notices): needs no
  marketing opt-in (CAN-SPAM: a message that delivers what a transaction agreed to). Use a template
  *without* the checkbox, sent to the customer tag. Keep it service-only: no promotion in subject or body.
- A payment is not marketing consent. Offer an optional, unticked checkbox at checkout that goes
  through `doi_signup` if you also want buyers on the marketing list.

## System parameters (prefix `mailing_doi.`)
`reminder_hours` (48) · `expire_days` (7) · `resend_throttle_minutes` (60) · `minimal_layout`
(1 = public pages without the website header/footer) · `keep_tags` (comma-separated tag names) ·
`signup_url` · `terms_url` · `privacy_url`. Parameters are per database.

## Sequences
- Welcome: automation rule on *Mailing Contact*, trigger «on create and edit», field **Double opt-in**,
  before `!= confirmed`, after `= confirmed`, Python action
  `for r in records: env['mail.template'].browse(<id>).send_mail(r.id)`.
- Every N days: rule «based on date field» on **Confirmed on**.
- Do not use the automation «Send email» action for these: on mail.thread models it posts to the
  chatter and bypasses the marketing gate.

## Install / update
Put the folder on the addons path, then `odoo -d <db> -i isolpa_mailing_double_optin --stop-after-init`
(or `-u` to update) and restart. Install it in each database that needs it.

Odoo 20 notes: API keys used for RPC need `scope='rpc'`; `ir.config_parameter` has
`get_int/get_str/set_str`; `on_time` automation rules evaluate the window from `last_run`;
`mail.template.body_html` is translatable, so search every language when replacing placeholders.
