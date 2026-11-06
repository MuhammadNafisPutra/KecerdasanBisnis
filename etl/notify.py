"""Notifikasi email saat batch gagal. Bila SMTP belum diatur, pesan hanya ditulis ke log."""
import logging
import smtplib
from email.message import EmailMessage

from etl import config

log = logging.getLogger("fitzone.notify")


def send_alert(subject: str, body: str) -> bool:
    if not (config.SMTP_HOST and config.ALERT_EMAIL_TO):
        log.warning("[ALERT tanpa email] %s - %s", subject, body)
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[FitZone ETL] {subject}"
    msg["From"] = config.SMTP_USER or "etl@fitzone.local"
    msg["To"] = config.ALERT_EMAIL_TO
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as exc:  # gagal kirim email tidak boleh menghentikan pipeline
        log.error("Gagal mengirim email notifikasi: %s", exc)
        return False
