import imaplib
import time
from email.mime.text import MIMEText
from app.core.config import settings

def test():
    msg = MIMEText("Test body for sent mail append")
    msg["Subject"] = "IMAP Append Test Direct"
    msg["From"] = settings.SMTP_USER
    msg["To"] = settings.TEST_EMAIL_OVERRIDE

    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    res, data = mail.append('"[Gmail]/Sent Mail"', "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    print("Append result:", res, data)
    mail.logout()

if __name__ == "__main__":
    test()
