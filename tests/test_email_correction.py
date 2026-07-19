from app.models import LibraryItem, Settings
from app.services.email_service import build_correction_email


def test_build_correction_email_renders_corrections_and_note():
    settings = Settings(
        smtp_from="plex@example.com",
        email_correction_template=None,
        email_correction_subject=None,
    )
    media = LibraryItem(
        title="Inception",
        year=2010,
        media_type="movie",
        poster_url="https://example.com/poster.jpg",
        overview="A thief who steals corporate secrets.",
        tmdb_id="27205",
    )

    subject, html = build_correction_email(
        settings,
        media,
        "Alice",
        ["Son corrigé", "Sous-titres corrigés"],
        "Le fichier a été remplacé.",
        plex_deep_link="#",
    )

    assert subject == "[Plexarr] Correction : Inception"
    assert "Alice" in html
    assert "Son corrigé" in html
    assert "Sous-titres corrigés" in html
    assert "Le fichier a été remplacé." in html
