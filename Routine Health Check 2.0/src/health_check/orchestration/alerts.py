"""Email alerting for the NeGD myScheme health-check suite.

Reuses the SMTP account configured for the sibling 'Daily Health Check'
project (smtp.gmail.com, STARTTLS). Server / sender / recipients live in
alert_config.json next to this file; the SMTP_USER / SMTP_PASS credentials
are read from the environment first, then from the .env referenced by
alert_config.json's `env_file` — so the secret is never duplicated here.

send_email() never raises: a broken mailer must not crash a monitor.
"""
import json
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from health_check.paths import ALERT_CONFIG

CONFIG = str(ALERT_CONFIG)


def _load_config():
    with open(CONFIG) as f:
        return json.load(f)


def _parse_env_file(path):
    """Parse `export KEY="value"` / `KEY=value` lines from a .env file."""
    creds = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return creds


def _smtp_credentials(cfg):
    """SMTP_USER / SMTP_PASS — environment first, then the reused .env file."""
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASS") or os.environ.get("SMTP_PASSWORD")
    if not (user and pw):
        env = _parse_env_file(cfg.get("env_file", ""))
        user = user or env.get("SMTP_USER")
        pw = pw or env.get("SMTP_PASS") or env.get("SMTP_PASSWORD")
    return user, pw


def smtp_selfcheck():
    """Verify SMTP connectivity + login WITHOUT sending mail.
    Returns (ok: bool, message: str)."""
    try:
        cfg = _load_config()
    except Exception as e:
        return False, f"cannot read alert_config.json: {e}"
    user, pw = _smtp_credentials(cfg)
    if not (user and pw):
        return False, "SMTP_USER / SMTP_PASS not available (env or env_file)"
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg.get("smtp_server", "smtp.gmail.com"),
                          int(cfg.get("smtp_port", 587)), timeout=30) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(user, pw)
        return True, f"SMTP login OK as {user} -> {cfg.get('smtp_server')}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def send_email(subject, html_body, text_body=None):
    """Send an alert email. Returns True on success, False otherwise.
    Never raises — alerting must not crash the monitor."""
    try:
        cfg = _load_config()
    except Exception as e:
        print(f"[alert] cannot read alert_config.json: {e}", flush=True)
        return False
    user, pw = _smtp_credentials(cfg)
    sender = cfg.get("sender") or user
    recipients = cfg.get("recipients") or []
    if not (user and pw):
        print("[alert] SMTP_USER / SMTP_PASS not available — email not sent.", flush=True)
        return False
    if not recipients:
        print("[alert] no recipients configured — email not sent.", flush=True)
        return False
    prefix = (cfg.get("subject_prefix") or "").strip()
    full_subject = f"{prefix} {subject}".strip() if prefix else subject

    msg = MIMEMultipart("alternative")
    msg["Subject"] = full_subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body or "See the HTML version of this alert.", "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg.get("smtp_server", "smtp.gmail.com"),
                          int(cfg.get("smtp_port", 587)), timeout=30) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(user, pw)
            server.sendmail(sender, recipients, msg.as_string())
        print(f"[alert] email sent to {', '.join(recipients)}: {full_subject}", flush=True)
        return True
    except Exception as e:
        print(f"[alert] email send failed: {type(e).__name__}: {e}", flush=True)
        return False


if __name__ == "__main__":
    # `python3 alerts.py`            -> connectivity self-check (no mail sent)
    # `python3 alerts.py --send-test` -> send one test email to the recipients
    import sys
    if "--send-test" in sys.argv:
        ok = send_email(
            "Test alert — please ignore",
            "<h2>myScheme Health Check — test alert</h2>"
            "<p>This confirms email alerting is wired up correctly.</p>",
            "myScheme Health Check test alert — email alerting is wired up correctly.")
        sys.exit(0 if ok else 1)
    ok, msg = smtp_selfcheck()
    print(("[ok] " if ok else "[fail] ") + msg)
    sys.exit(0 if ok else 1)
