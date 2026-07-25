"""Client minimal pour l'API transactionnelle Brevo (ex-Sendinblue).

https://developers.brevo.com/docs/send-a-transactional-email — alternative HTTP
au SMTP : une seule clé API, pas de serveur SMTP à gérer.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.brevo.com/v3"


def _error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return data.get("message") or data.get("code") or resp.text
    except Exception:
        return resp.text


async def send_transactional_email(
    *,
    api_key: str,
    sender_email: str,
    sender_name: str | None,
    to_email: str,
    subject: str,
    html_content: str,
    to_name: str | None = None,
) -> str:
    """Envoie un email transactionnel via l'API Brevo. Retourne le messageId Brevo."""
    sender: dict[str, str] = {"email": sender_email}
    if sender_name:
        sender["name"] = sender_name
    recipient: dict[str, str] = {"email": to_email}
    if to_name:
        recipient["name"] = to_name

    payload = {
        "sender": sender,
        "to": [recipient],
        "subject": subject,
        "htmlContent": html_content,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{BASE_URL}/smtp/email",
            json=payload,
            headers={"api-key": api_key, "content-type": "application/json", "accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Échec de l'envoi via Brevo ({resp.status_code}): {_error_detail(resp)}")
    return (resp.json() or {}).get("messageId", "")
