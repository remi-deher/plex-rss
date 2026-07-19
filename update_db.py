from app.database import SessionLocal
from app.models import Settings

db = SessionLocal()
s = db.query(Settings).first()
if s:
    if s.email_available_template and "{qualite}" in s.email_available_template:
        s.email_available_template = s.email_available_template.replace("{qualite}", "{langue}")
    if s.email_upgrade_template and "{qualite}" in s.email_upgrade_template:
        s.email_upgrade_template = s.email_upgrade_template.replace("{qualite}", "{langue}")
    db.commit()
db.close()
