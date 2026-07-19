SUPPORTED_LOCALES = {"fr", "en"}
DEFAULT_LOCALE = "fr"

CATALOGS = {
    "fr": {
        "media.issue.report": "Signaler un probleme",
        "media.issue.saved": "Signalement enregistre",
        "media.issue.type_prompt": "Type de probleme (audio, sous-titres, mauvais media, qualite, autre)",
        "media.issue.detail_prompt": "Detail du probleme constate",
    },
    "en": {
        "media.issue.report": "Report an issue",
        "media.issue.saved": "Issue report saved",
        "media.issue.type_prompt": "Issue type (audio, subtitles, wrong media, quality, other)",
        "media.issue.detail_prompt": "Describe the issue",
    },
}


def normalize_locale(locale: str | None) -> str:
    if not locale:
        return DEFAULT_LOCALE
    short = locale.split(",")[0].split("-")[0].strip().lower()
    return short if short in SUPPORTED_LOCALES else DEFAULT_LOCALE


def catalog(locale: str | None) -> dict[str, str]:
    resolved = normalize_locale(locale)
    return CATALOGS[resolved]
