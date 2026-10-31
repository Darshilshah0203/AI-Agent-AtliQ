"""Gmail API dispatcher with MIME building, TEST_INBOX redirection, and attachments."""

import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import Config, load_config


GMAIL_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]


class GmailDeliveryError(Exception):
    """Raised when email delivery fails."""
    pass


def send_email_via_gmail(
    recipient: str,
    subject: str,
    html_body: str,
    plain_text: str,
    attachment_path: Optional[str] = None,
    cc_recipients: Optional[List[str]] = None,
    config: Optional[Config] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Send MIME email with attachment using Gmail API send-only access.
    
    Rules (PRD 8, 9, 10):
    - Uses Gmail API send permission (https://www.googleapis.com/auth/gmail.send).
    - If TEST_INBOX is set, redirect all delivery to TEST_INBOX and note original recipient.
    - Delivery is confirmed (OK) ONLY when Gmail returns a message ID.
    - Returns (success_bool, gmail_message_id, error_message).
    """
    if config is None:
        config = load_config()

    if not config.google_refresh_token or config.google_refresh_token.startswith("mock_"):
        return False, None, "Google OAuth refresh token not configured in .env."

    try:
        creds = Credentials(
            token=None,
            refresh_token=config.google_refresh_token,
            client_id=config.google_client_id,
            client_secret=config.google_client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=GMAIL_SCOPE,
        )
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        # Build outer multipart/mixed container
        msg = MIMEMultipart("mixed")
        msg["From"] = config.email_from

        effective_to = recipient
        effective_cc = cc_recipients or []

        # Handle TEST_INBOX redirection (PRD 9 & 10)
        if config.test_inbox:
            actual_recipients_str = f"To: {recipient}"
            if effective_cc:
                actual_recipients_str += f", CC: {', '.join(effective_cc)}"

            msg["To"] = config.test_inbox
            msg["Subject"] = f"[TEST DEMO -> {recipient}] {subject}"

            banner_html = (
                f'<div style="background-color: #FFF9C4; border: 1px solid #FBC02D; border-radius: 4px; padding: 10px; margin-bottom: 12px; font-size: 12px; color: #555;">'
                f'<strong>[TEST INBOX DEMO REDIRECTION]</strong><br>'
                f'<strong>Intended Recipient(s):</strong> {actual_recipients_str}<br>'
                f'<strong>Delivered to Demo Inbox:</strong> {config.test_inbox}'
                f'</div>'
            )
            html_body = banner_html + html_body

            banner_text = (
                f"[TEST INBOX DEMO REDIRECTION]\n"
                f"Intended Recipient(s): {actual_recipients_str}\n"
                f"Delivered to Demo Inbox: {config.test_inbox}\n"
                f"{'-' * 60}\n"
            )
            plain_text = banner_text + plain_text
        else:
            msg["To"] = recipient
            msg["Subject"] = subject
            if effective_cc:
                msg["Cc"] = ", ".join(effective_cc)

        # Build alternative part (plain text + HTML)
        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(plain_text, "plain", "utf-8"))
        alt_part.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt_part)

        # Attach Word document (.docx) if provided
        if attachment_path and os.path.exists(attachment_path):
            filename = os.path.basename(attachment_path)
            with open(attachment_path, "rb") as f:
                attachment_data = f.read()

            part = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
            part.set_payload(attachment_data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(part)

        # Encode and send via Gmail API
        raw_msg = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        result = service.users().messages().send(userId="me", body={"raw": raw_msg}).execute()

        msg_id = result.get("id")
        if msg_id:
            print(f"  [Gmail Success] Message delivered to {msg['To']}. Gmail Message ID: {msg_id}")
            return True, msg_id, None
        else:
            return False, None, "Gmail API accepted message but returned no message ID."

    except HttpError as he:
        err_msg = f"Gmail API HTTP error ({he.resp.status}): {he.content.decode('utf-8', errors='ignore')}"
        print(f"  [Gmail Failure] {err_msg}")
        return False, None, err_msg
    except Exception as ex:
        err_msg = f"Gmail send error: {ex}"
        print(f"  [Gmail Failure] {err_msg}")
        return False, None, err_msg

