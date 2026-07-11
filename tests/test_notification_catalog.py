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


def test_legacy_availability_events_are_no_longer_catalogued():
    assert get_event("vf_available").key == "unknown"
    assert event_mail_flags("available_vo_tracking") == ()
