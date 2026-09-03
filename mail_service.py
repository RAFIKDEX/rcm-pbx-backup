import smtplib
import ssl
import os
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from cryptography.fernet import Fernet
import db

# 32-byte URL-safe base64 key
SECRET_KEY = b'G_LpX5V9wZf8jY7d1_mK8vP3nQs2xT4a-B6c9d0e1f2='
fernet = Fernet(SECRET_KEY)

def encrypt_password(password: str) -> str:
    if not password:
        return ""
    return fernet.encrypt(password.encode('utf-8')).decode('utf-8')

def decrypt_password(encrypted_pw: str) -> str:
    if not encrypted_pw:
        return ""
    try:
        return fernet.decrypt(encrypted_pw.encode('utf-8')).decode('utf-8')
    except Exception:
        return ""

def send_email(receiver_email, subject, body_html, body_text="", attachments=None, feature="Test"):
    """
    Sends an email using the central SMTP mail server settings.
    attachments: list of dicts with keys 'path' and 'filename'
    """
    settings = db.get_mail_settings()
    if not settings:
        err = "Mail Server settings not configured."
        db.log_email(receiver_email, "", subject, "Failed", err, feature)
        return False, err
        
    sender_email = settings.get("sender_email") or ""
    smtp_server = settings.get("smtp_server") or ""
    smtp_port = settings.get("smtp_port") or 25
    encryption = settings.get("encryption") or "none"
    username = settings.get("username") or ""
    encrypted_pw = settings.get("password") or ""
    password = decrypt_password(encrypted_pw)
    
    if not smtp_server or not sender_email:
        err = "SMTP server address and sender email are required."
        db.log_email(receiver_email, sender_email, subject, "Failed", err, feature)
        return False, err

    # Create message container
    msg = MIMEMultipart('alternative' if not attachments else 'mixed')
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_email
    
    # Attach bodies
    if attachments:
        # If we have attachments, the outer message is 'mixed'
        # The body parts should be nested inside an 'alternative' part
        body_part = MIMEMultipart('alternative')
        if body_text:
            body_part.attach(MIMEText(body_text, 'plain', 'utf-8'))
        body_part.attach(MIMEText(body_html, 'html', 'utf-8'))
        msg.attach(body_part)
    else:
        if body_text:
            msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

    # Attach files
    if attachments:
        for att in attachments:
            path = att.get("path")
            filename = att.get("filename") or os.path.basename(path)
            if os.path.exists(path):
                try:
                    with open(path, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                    msg.attach(part)
                except Exception as e:
                    print(f"Error attaching file {path}: {e}")

    try:
        # Establish connection
        if encryption == "ssl":
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            if encryption == "tls":
                context = ssl.create_default_context()
                server.starttls(context=context)

        # Authenticate if username/password are set
        if username and password:
            server.login(username, password)
            
        # Send
        server.sendmail(sender_email, [receiver_email], msg.as_string())
        server.quit()
        
        # Log success
        db.log_email(receiver_email, sender_email, subject, "Success", "", feature)
        return True, ""
    except Exception as e:
        err_msg = str(e)
        db.log_email(receiver_email, sender_email, subject, "Failed", err_msg, feature)
        return False, err_msg
