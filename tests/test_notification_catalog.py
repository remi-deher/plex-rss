from app.services.notification_catalog import event_mail_flags, get_event, template_fields


def test_catalog_exposes_vo_vf_event_metadata():
    event = get_event("vf_available")
    assert event.label == "VF ajoutée plus tard"
    assert event.group == "Suivi VO/VF"
    assert event.mail_flags == ("vf_available_mail_sent",)
    assert event.preview_context["language_reason"] == "VF film complet"


def test_catalog_template_fields_are_deduplicated():
    fields = template_fields()
    assert "email_vf_upgrade_template" in fields
    assert "email_vf_upgrade_subject" in fields
    assert fields.count("email_vf_upgrade_template") == 1


def test_catalog_mail_flags_keep_merged_available_vo_tracking_contract():
    assert event_mail_flags("available_vo_tracking") == ("available_mail_sent", "vo_only_mail_sent")
