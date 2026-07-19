from app.services.notification_catalog import event_mail_flags, get_event, template_fields


def test_catalog_exposes_single_available_event_with_structured_preview():
    event = get_event("available")
    assert event.key == "available"
    assert event.mail_flags == ("available_mail_sent",)
    assert event.preview_context == {
        "scope": "episode",
        "language": "vf",
        "is_upgrade": False,
        "season_number": 2,
        "episode_number": 1,
    }


def test_catalog_template_fields_are_reduced_to_three_event_families():
    fields = template_fields()
    assert fields == [
        "email_request_template",
        "email_request_subject",
        "email_available_template",
        "email_available_subject",
        "email_failure_template",
        "email_failure_subject",
    ]


def test_legacy_availability_events_are_no_longer_configurable_but_stay_labeled():
    """Les anciennes clés (pré-fusion du catalogue) ne sont plus des évènements
    configurables (pas de template_fields propre, pas de mail_flags), mais restent
    lisibles dans l'historique au lieu de retomber sur "Événement inconnu"."""
    event = get_event("vf_available")
    assert event.key == "vf_available"
    assert event.label == "VF disponible (mise à jour)"
    assert event.group == "Disponibilité"
    # Hérite du comportement de "available" (même évènement réel, seul le libellé diffère).
    assert event_mail_flags("available_vo_tracking") == ("available_mail_sent",)


def test_unrecognized_event_still_falls_back_to_unknown():
    event = get_event("totally_made_up_event")
    assert event.key == "unknown"
    assert event.label == "Événement inconnu"
