"""Normalise les modèles et l'habillage des emails.

Revision ID: 0089_normalize_email_configuration
Revises: 0088_library_analytics_snapshot
"""

from alembic import op
import sqlalchemy as sa

revision = "0089_normalize_email_configuration"
down_revision = "0088_library_analytics_snapshot"
branch_labels = None
depends_on = None

EVENTS = (
    "request", "available", "upgrade", "failure", "correction",
    "episode_available", "season_started", "season_partial",
    "season_complete", "series_partial", "series_complete",
)
VISUAL_EVENTS = {"request", "available", "upgrade", "failure", "correction"}
BRANDING = {
    "header_brand": "email_header_brand",
    "header_subtitle": "email_header_subtitle",
    "footer_template": "email_footer_template",
    "templates_backup": "email_templates_backup",
    "show_poster": "email_show_poster",
    "show_genres": "email_show_genres",
    "show_requester": "email_show_requester",
    "requester_label": "email_requester_label",
    "brand_color": "email_brand_color",
    "show_header_subtitle": "email_show_header_subtitle",
    "poster_width": "email_poster_width",
    "media_layout": "email_media_layout",
    "bg_color": "email_bg_color",
    "card_bg_color": "email_card_bg_color",
    "font_family": "email_font_family",
    "card_width": "email_card_width",
    "card_border_radius": "email_card_border_radius",
    "synopsis_font_size": "email_synopsis_font_size",
    "show_tmdb_link": "email_show_tmdb_link",
    "show_plex_button": "email_show_plex_button",
}


def upgrade() -> None:
    op.create_table(
        "email_branding",
        sa.Column("settings_id", sa.Integer(), nullable=False),
        *[
            sa.Column(name, sa.Integer() if name in {"poster_width", "card_width", "card_border_radius"}
                      else sa.Boolean() if name.startswith("show_")
                      else sa.Text() if name in {"footer_template", "templates_backup"}
                      else sa.String(), nullable=True)
            for name in BRANDING
        ],
        sa.ForeignKeyConstraint(["settings_id"], ["settings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("settings_id"),
    )
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("settings_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("template", sa.Text()),
        sa.Column("subject", sa.String()),
        sa.Column("accent_color", sa.String()),
        sa.Column("badge_text", sa.String()),
        sa.Column("headline_text", sa.String()),
        sa.Column("show_synopsis", sa.Boolean()),
        sa.ForeignKeyConstraint(["settings_id"], ["settings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settings_id", "event", name="uq_email_template_event"),
    )

    target_cols = ", ".join(["settings_id", *BRANDING])
    source_cols = ", ".join(["id", *BRANDING.values()])
    op.execute(sa.text(
        f"INSERT INTO email_branding ({target_cols}) SELECT {source_cols} FROM settings"
    ))
    for event in EVENTS:
        cols = ["settings_id", "event", "template", "subject"]
        values = ["id", f"'{event}'", f"email_{event}_template", f"email_{event}_subject"]
        if event in VISUAL_EVENTS:
            cols += ["accent_color", "badge_text", "headline_text", "show_synopsis"]
            values += [
                f"email_{event}_accent_color", f"email_{event}_badge_text",
                f"email_{event}_headline_text", f"email_{event}_show_synopsis",
            ]
        op.execute(sa.text(
            f"INSERT INTO email_templates ({', '.join(cols)}) "
            f"SELECT {', '.join(values)} FROM settings"
        ))

    old_columns = list(BRANDING.values())
    for event in EVENTS:
        old_columns += [f"email_{event}_template", f"email_{event}_subject"]
        if event in VISUAL_EVENTS:
            old_columns += [
                f"email_{event}_accent_color", f"email_{event}_badge_text",
                f"email_{event}_headline_text", f"email_{event}_show_synopsis",
            ]
    with op.batch_alter_table("settings") as batch:
        for name in old_columns:
            batch.drop_column(name)


def downgrade() -> None:
    boolean_names = {
        *[source for target, source in BRANDING.items() if target.startswith("show_")],
        *[f"email_{event}_show_synopsis" for event in VISUAL_EVENTS],
    }
    integer_names = {
        "email_poster_width", "email_card_width", "email_card_border_radius",
    }
    text_names = {
        "email_footer_template", "email_templates_backup",
        *[f"email_{event}_template" for event in EVENTS],
    }
    names = list(BRANDING.values())
    for event in EVENTS:
        names += [f"email_{event}_template", f"email_{event}_subject"]
        if event in VISUAL_EVENTS:
            names += [
                f"email_{event}_accent_color", f"email_{event}_badge_text",
                f"email_{event}_headline_text", f"email_{event}_show_synopsis",
            ]
    with op.batch_alter_table("settings") as batch:
        for name in names:
            kind = sa.Boolean() if name in boolean_names else sa.Integer() if name in integer_names else sa.Text() if name in text_names else sa.String()
            batch.add_column(sa.Column(name, kind, nullable=True))

    for target, source in BRANDING.items():
        op.execute(sa.text(
            f"UPDATE settings SET {source} = "
            f"(SELECT {target} FROM email_branding WHERE settings_id = settings.id)"
        ))
    for event in EVENTS:
        fields = ["template", "subject"]
        if event in VISUAL_EVENTS:
            fields += ["accent_color", "badge_text", "headline_text", "show_synopsis"]
        for field in fields:
            op.execute(sa.text(
                f"UPDATE settings SET email_{event}_{field} = "
                f"(SELECT {field} FROM email_templates "
                f"WHERE settings_id = settings.id AND event = '{event}')"
            ))
    op.drop_table("email_templates")
    op.drop_table("email_branding")
