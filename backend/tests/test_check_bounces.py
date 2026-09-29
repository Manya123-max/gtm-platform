import imaplib
import email
from app.core.config import settings

def main():
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    mail.select("inbox")

    status, search_data = mail.search(None, "ALL")
    if search_data and search_data[0]:
        msg_ids = search_data[0].split()
        recent = msg_ids[-15:]
        print(f"Checking last {len(recent)} messages in INBOX for bounce notifications:")
        for mid in recent:
            res, data = mail.fetch(mid, "(RFC822.HEADER)")
            if data and data[0]:
                msg = email.message_from_bytes(data[0][1])
                print(f"UID: {mid.decode()} | From: {msg.get('From')} | Subject: {msg.get('Subject')}")
    mail.logout()

if __name__ == "__main__":
    main()
