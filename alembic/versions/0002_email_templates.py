"""Add email templates to settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_REQUEST_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#e5a00d;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">🎬 Nouvelle demande Plex</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#e5a00d">Type :</strong> {{ media_type_label }}&nbsp;&nbsp;
      <strong style="color:#e5a00d">Demandé par :</strong> {{ plex_user }}
    </p>
    {% if genres %}<p style="margin:4px 0;color:#888;font-size:13px">{{ genres }}</p>{% endif %}
    {% if overview %}
    <p style="margin:16px 0 0;color:#ccc;font-size:14px;line-height:1.6;clear:both">{{ overview }}</p>
    {% endif %}
    <hr style="border:none;border-top:1px solid #333;margin:20px 0">
    <p style="color:#888;font-size:12px;margin:0">
      Vous recevrez un autre email dès que le contenu sera disponible sur votre serveur Plex.
    </p>
  </td></tr>
</table>
</body></html>"""

DEFAULT_AVAILABLE_TEMPLATE = """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#141414;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:auto">
  <tr><td style="background:#1db954;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:22px">✅ Disponible sur Plex !</h1>
  </td></tr>
  <tr><td style="background:#1f1f1f;padding:28px;color:#fff">
    {% if poster_url %}
    <img src="{{ poster_url }}" style="width:110px;float:right;border-radius:8px;margin:0 0 12px 20px" alt="poster">
    {% endif %}
    <h2 style="margin:0 0 8px">{{ title }}{% if year %} <span style="color:#aaa;font-weight:normal">({{ year }})</span>{% endif %}</h2>
    <p style="margin:4px 0;color:#aaa">
      <strong style="color:#1db954">Demandé par :</strong> {{ plex_user }}
    </p>
    {% if genres %}<p style="margin:4px 0;color:#888;font-size:13px">{{ genres }}</p>{% endif %}
    <p style="margin:20px 0 0;font-size:16px">
      🎉 {{ media_type_label_cap }} est maintenant disponible sur votre serveur Plex. Bonne séance !
    </p>
    <hr style="border:none;border-top:1px solid #333;margin:20px 0;clear:both">
    <p style="color:#888;font-size:12px;margin:0">Géré par Plex RSS Monitor</p>
  </td></tr>
</table>
</body></html>"""


def upgrade() -> None:
    op.add_column("settings", sa.Column("email_request_template", sa.Text(), nullable=True))
    op.add_column("settings", sa.Column("email_available_template", sa.Text(), nullable=True))
    op.execute(
        f"UPDATE settings SET email_request_template = '{DEFAULT_REQUEST_TEMPLATE.replace(chr(39), chr(39) * 2)}' WHERE id = 1"
    )
    op.execute(
        f"UPDATE settings SET email_available_template = '{DEFAULT_AVAILABLE_TEMPLATE.replace(chr(39), chr(39) * 2)}' WHERE id = 1"
    )


def downgrade() -> None:
    op.drop_column("settings", "email_request_template")
    op.drop_column("settings", "email_available_template")
