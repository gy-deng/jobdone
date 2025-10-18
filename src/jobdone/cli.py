#!/usr/bin/env python3

import argparse
import json
import os
import socket
import getpass
import time
import ssl
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

# All comments in this file are in English by convention.

VERSION = "0.1.0"

class SendResult:
    def __init__(self, ok: bool, error: Optional[str] = None, target: Optional[str] = None, channel: Optional[str] = None):
        self.ok = ok
        self.error = error
        self.target = target
        self.channel = channel

class NotificationContext:
    def __init__(self, job: str, status: str, exit_code: int, host: str, user: str, timestamp: str):
        self.job = job
        self.status = status
        self.exit_code = exit_code
        self.host = host
        self.user = user
        self.timestamp = timestamp

class Notifier:
    def name(self) -> str:
        return self.__class__.__name__

    def send(self, title: str, message: str, context: NotificationContext) -> SendResult:
        raise NotImplementedError

class WebhookNotifier(Notifier):
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 10.0, verbose: bool = False):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.verbose = verbose

    def send(self, title: str, message: str, context: NotificationContext) -> SendResult:
        payload = {
            "title": title,
            "message": message,
            "context": {
                "job": context.job,
                "status": context.status,
                "exit_code": context.exit_code,
                "host": context.host,
                "user": context.user,
                "timestamp": context.timestamp,
                "source": "jobdone",
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = Request(self.url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in self.headers.items():
            req.add_header(k, v)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                if self.verbose:
                    print(f"[webhook] {self.url} -> status {resp.status}")
                if 200 <= resp.status < 300:
                    return SendResult(ok=True, target=self.url, channel="webhook")
                return SendResult(ok=False, error=f"HTTP {resp.status}", target=self.url, channel="webhook")
        except HTTPError as e:
            return SendResult(ok=False, error=f"HTTPError {e.code}", target=self.url, channel="webhook")
        except URLError as e:
            return SendResult(ok=False, error=f"URLError {e.reason}", target=self.url, channel="webhook")
        except Exception as e:
            return SendResult(ok=False, error=str(e), target=self.url, channel="webhook")

class EmailNotifier(Notifier):
    def __init__(self, smtp_host: str, smtp_port: int, smtp_user: Optional[str], smtp_pass: Optional[str], sender: str, recipients: List[str], timeout: float = 10.0, use_tls: bool = True, use_ssl: Optional[bool] = None, verbose: bool = False, subject_override: Optional[str] = None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.sender = sender
        self.recipients = recipients
        self.timeout = timeout
        self.use_tls = use_tls
        self.use_ssl = bool(use_ssl) if use_ssl is not None else False
        self.verbose = verbose
        self.subject_override = subject_override

    def send(self, title: str, message: str, context: NotificationContext) -> SendResult:
        subject = self.subject_override or title
        body = f"{message}\n\nJob: {context.job}\nStatus: {context.status}\nExit code: {context.exit_code}\nHost: {context.host}\nUser: {context.user}\nTime: {context.timestamp}"
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg["Subject"] = subject
        msg.set_content(body)
        stage = "init"
        try:
            # Use implicit SSL for port 465, otherwise plaintext with optional STARTTLS
            if self.use_ssl or self.smtp_port == 465:
                ctx = ssl.create_default_context()
                stage = "connect_ssl"
                smtp = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=self.timeout, context=ctx)
            else:
                stage = "connect_plain"
                smtp = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout)
                smtp.ehlo()
                if self.use_tls:
                    stage = "starttls"
                    ctx = ssl.create_default_context()
                    try:
                        smtp.starttls(context=ctx)
                    except smtplib.SMTPNotSupportedError:
                        # Server may not support STARTTLS; continue without TLS
                        pass
                    smtp.ehlo()
            if self.verbose:
                try:
                    smtp.set_debuglevel(1)
                except Exception:
                    pass
            # Attempt login if credentials are available; default to sender as username if not provided
            login_user = self.smtp_user or self.sender
            if login_user and self.smtp_pass:
                stage = "login"
                try:
                    smtp.login(login_user, self.smtp_pass)
                except smtplib.SMTPException:
                    # Some servers may accept unauthenticated send or require app password; continue to attempt send
                    pass
            stage = "send"
            smtp.send_message(msg)
            smtp.quit()
            if self.verbose:
                print(f"[email] {len(self.recipients)} recipient(s) via {self.smtp_host}:{self.smtp_port}")
            return SendResult(ok=True, target=",".join(self.recipients), channel="email")
        except Exception as e:
            err = str(e)
            # Fallback: if SSL connect timed out, try STARTTLS on 587
            if (self.use_ssl or self.smtp_port == 465) and ("timed out" in err or isinstance(e, smtplib.SMTPServerDisconnected)):
                try:
                    stage = "fallback_connect_plain"
                    alt_port = 587
                    smtp = smtplib.SMTP(self.smtp_host, alt_port, timeout=self.timeout)
                    smtp.ehlo()
                    stage = "fallback_starttls"
                    ctx = ssl.create_default_context()
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                    if self.verbose:
                        try:
                            smtp.set_debuglevel(1)
                        except Exception:
                            pass
                    login_user = self.smtp_user or self.sender
                    if login_user and self.smtp_pass:
                        stage = "fallback_login"
                        try:
                            smtp.login(login_user, self.smtp_pass)
                        except smtplib.SMTPException:
                            pass
                    stage = "fallback_send"
                    smtp.send_message(msg)
                    smtp.quit()
                    return SendResult(ok=True, target=",".join(self.recipients), channel="email")
                except Exception as e2:
                    return SendResult(ok=False, error=f"{err} | fallback failed: {e2} (stage={stage})", target=",".join(self.recipients), channel="email")
            return SendResult(ok=False, error=f"{err} (stage={stage})", target=",".join(self.recipients), channel="email")

class DesktopNotifier(Notifier):
    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def send(self, title: str, message: str, context: NotificationContext) -> SendResult:
        # Linux uses notify-send; macOS/Windows can be added later.
        import subprocess
        # Basic environment checks to provide clearer errors on headless systems
        if not os.environ.get("DISPLAY"):
            return SendResult(ok=False, error="DISPLAY not set (no GUI session)", target="notify-send", channel="desktop")
        try:
            result = subprocess.run(["notify-send", title, message], capture_output=True)
            if result.returncode == 0:
                if self.verbose:
                    print("[desktop] notify-send dispatched")
                return SendResult(ok=True, target="notify-send", channel="desktop")
            # include stderr for better diagnosis
            err = result.stderr.decode("utf-8", errors="ignore") if result.stderr else ""
            return SendResult(ok=False, error=f"notify-send exit {result.returncode} {err}".strip(), target="notify-send", channel="desktop")
        except FileNotFoundError:
            return SendResult(ok=False, error="notify-send not found", target="notify-send", channel="desktop")
        except Exception as e:
            return SendResult(ok=False, error=str(e), target="notify-send", channel="desktop")

# Config helpers

def try_load_yaml(paths: List[str]) -> Dict:
    config: Dict = {}
    try:
        import yaml  # optional dependency
    except Exception:
        return {}
    for p in paths:
        if p and os.path.exists(p) and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    # Shallow merge: later file overrides earlier
                    config.update(data)
            except Exception:
                # Ignore YAML parsing errors by default
                pass
    return config

# New: apply defaults before merge

def apply_defaults(cfg: Dict) -> Dict:
    d = cfg.get("default")
    if isinstance(d, dict):
        merged = dict(cfg)
        for k, v in d.items():
            if k not in merged:
                merged[k] = v
        merged.pop("default", None)
        return merged
    return cfg

def env_config() -> Dict:
    cfg: Dict = {}
    def get(name: str) -> Optional[str]:
        return os.environ.get(name)
    # Channels
    channels = get("JOBDONE_CHANNELS")
    if channels:
        cfg["channels"] = [x.strip() for x in channels.split(",") if x.strip()]
    # Webhook
    webhook_urls = get("JOBDONE_WEBHOOK_URLS")
    if webhook_urls:
        cfg.setdefault("webhook", {})["urls"] = [x.strip() for x in webhook_urls.split(",") if x.strip()]
    # Email
    email_to = get("JOBDONE_EMAIL_TO")
    if email_to:
        cfg.setdefault("email", {})["to"] = [x.strip() for x in email_to.split(",") if x.strip()]
    smtp_host = get("JOBDONE_SMTP_HOST")
    if smtp_host:
        cfg.setdefault("email", {})["smtp_host"] = smtp_host
    smtp_port = get("JOBDONE_SMTP_PORT")
    if smtp_port:
        try:
            cfg.setdefault("email", {})["smtp_port"] = int(smtp_port)
        except ValueError:
            pass
    smtp_user = get("JOBDONE_SMTP_USER")
    if smtp_user:
        cfg.setdefault("email", {})["smtp_user"] = smtp_user
    smtp_pass = get("JOBDONE_SMTP_PASS")
    if smtp_pass:
        cfg.setdefault("email", {})["smtp_pass"] = smtp_pass
    email_from = get("JOBDONE_EMAIL_FROM")
    if email_from:
        cfg.setdefault("email", {})["from"] = email_from
    # General
    on = get("JOBDONE_ON")
    if on:
        cfg["on"] = on
    retries = get("JOBDONE_RETRIES")
    if retries:
        try:
            cfg["retries"] = int(retries)
        except ValueError:
            pass
    backoff = get("JOBDONE_BACKOFF")
    if backoff:
        try:
            cfg["backoff"] = float(backoff)
        except ValueError:
            pass
    timeout = get("JOBDONE_TIMEOUT")
    if timeout:
        try:
            cfg["timeout"] = float(timeout)
        except ValueError:
            pass
    return cfg

# Merge precedence: CLI > YAML > ENV

def merge_config(yaml_cfg: Dict, env_cfg: Dict, cli_cfg: Dict) -> Dict:
    merged = {}
    def deep_update(base: Dict, updates: Dict) -> Dict:
        for k, v in updates.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = deep_update(base[k], v)
            else:
                base[k] = v
        return base
    # Change order to make YAML override ENV, and CLI override both
    merged = deep_update({}, env_cfg)
    merged = deep_update(merged, yaml_cfg)
    merged = deep_update(merged, cli_cfg)
    return merged

# CLI parsing

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jobdone", description="Notify when shell task is done (webhook/email/desktop)")
    p.add_argument("--version", action="version", version=f"jobdone {VERSION}")
    p.add_argument("-j", "--job", default="job", help="Job name")
    p.add_argument("-t", "--title", default="任务完成 / Job Done", help="Notification title")
    p.add_argument("-m", "--message", default=None, help="Notification message")
    p.add_argument("--stdin", action="store_true", help="Read message from STDIN")
    p.add_argument("-e", "--exit-code", type=int, default=0, help="Exit code of the previous task")
    p.add_argument("--on", choices=["success", "failure", "always"], default="always", help="Trigger condition")
    p.add_argument("-c", "--channel", default=None, help="Comma-separated channels: webhook,email,desktop")
    # Webhook
    p.add_argument("--webhook-url", action="append", help="Webhook URL (can be repeated)")
    p.add_argument("--header", action="append", help="Extra header k:v (can be repeated)")
    # Email
    p.add_argument("--email-to", action="append", help="Email recipient (can be repeated)")
    p.add_argument("--email-subject", default=None, help="Email subject override")
    p.add_argument("--smtp-host", default=None, help="SMTP host")
    p.add_argument("--smtp-port", type=int, default=None, help="SMTP port")
    p.add_argument("--smtp-user", default=None, help="SMTP username")
    p.add_argument("--smtp-pass", default=None, help="SMTP password")
    p.add_argument("--smtp-pass-prompt", action="store_true", help="Prompt for SMTP password interactively")
    p.add_argument("--email-from", default=None, help="Email sender address")
    # General
    p.add_argument("--timeout", type=float, default=10.0, help="Per-channel timeout seconds")
    p.add_argument("--retries", type=int, default=0, help="Retries per channel")
    p.add_argument("--backoff", type=float, default=2.0, help="Backoff seconds between retries")
    p.add_argument("--config", default=None, help="Config file path (YAML)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    p.add_argument("--dry-run", action="store_true", help="Do not send, only print actions")
    return p.parse_args(argv)

def parse_headers(header_list: Optional[List[str]]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if not header_list:
        return headers
    for item in header_list:
        if ":" in item:
            k, v = item.split(":", 1)
            headers[k.strip()] = v.strip()
    return headers

# Trigger evaluation

def should_trigger(trigger: str, exit_code: int) -> bool:
    if trigger == "always":
        return True
    if trigger == "success":
        return exit_code == 0
    if trigger == "failure":
        return exit_code != 0
    return False

# Runner with retries and parallel dispatch

def send_with_retry(notifier: Notifier, title: str, message: str, context: NotificationContext, retries: int, backoff: float) -> SendResult:
    attempt = 0
    last_result: Optional[SendResult] = None
    while attempt <= retries:
        result = notifier.send(title, message, context)
        if result.ok:
            return result
        last_result = result
        attempt += 1
        if attempt <= retries:
            time.sleep(backoff)
    return last_result or SendResult(ok=False, error="Unknown error", channel=notifier.name())

# Main entry

def main() -> int:
    args = parse_args(sys.argv[1:])

    if args.stdin:
        try:
            stdin_data = sys.stdin.read()
            args.message = (stdin_data or "").strip()
        except Exception:
            pass

    yaml_paths = [
        os.path.expanduser("~/.config/jobdone/config.yaml"),
        os.path.join(os.getcwd(), ".jobdone.yaml"),
        os.path.join(os.getcwd(), "jobdone.yaml"),
        os.path.join(os.getcwd(), "config.yaml"),
    ]
    if args.config:
        yaml_paths.insert(0, args.config)
    # Verbose: show YAML search order and which files exist
    existing_yaml = [p for p in yaml_paths if p and os.path.exists(p) and os.path.isfile(p)]
    if args.verbose:
        print("[config] yaml search order:")
        for p in yaml_paths:
            mark = " (found)" if p in existing_yaml else ""
            print(f" - {p}{mark}")
        if not existing_yaml:
            print("[warn] no YAML config files found in search paths")
    yaml_cfg = try_load_yaml(yaml_paths)
    yaml_cfg = apply_defaults(yaml_cfg)
    env_cfg = env_config()

    cli_cfg: Dict = {}
    if args.channel:
        cli_cfg["channels"] = [x.strip() for x in args.channel.split(",") if x.strip()]
    if args.webhook_url:
        cli_cfg.setdefault("webhook", {})["urls"] = args.webhook_url
    if args.header:
        cli_cfg.setdefault("webhook", {})["headers"] = parse_headers(args.header)
    if args.email_to:
        cli_cfg.setdefault("email", {})["to"] = args.email_to
    if args.smtp_host:
        cli_cfg.setdefault("email", {})["smtp_host"] = args.smtp_host
    if args.smtp_port is not None:
        cli_cfg.setdefault("email", {})["smtp_port"] = args.smtp_port
    if args.smtp_user:
        cli_cfg.setdefault("email", {})["smtp_user"] = args.smtp_user
    if args.smtp_pass:
        cli_cfg.setdefault("email", {})["smtp_pass"] = args.smtp_pass
    elif getattr(args, "smtp_pass_prompt", False):
        try:
            pw = getpass.getpass("SMTP password: ")
        except Exception:
            pw = ""
        cli_cfg.setdefault("email", {})["smtp_pass"] = pw
    if args.email_from:
        cli_cfg.setdefault("email", {})["from"] = args.email_from
    cli_cfg["on"] = args.on
    cli_cfg["retries"] = args.retries
    cli_cfg["backoff"] = args.backoff
    cli_cfg["timeout"] = args.timeout

    final_cfg = merge_config(yaml_cfg, env_cfg, cli_cfg)

    if args.verbose:
        print("[config] merged:")
        try:
            print(json.dumps(final_cfg, ensure_ascii=False, indent=2))
        except Exception:
            print(final_cfg)

    if not should_trigger(final_cfg.get("on", "always"), args.exit_code):
        if args.verbose:
            print(f"[info] trigger condition not met: on={final_cfg.get('on')} exit_code={args.exit_code}")
        return 0

    title = args.title
    message = args.message or f"Job {args.job} finished with exit code {args.exit_code}."
    context = NotificationContext(
        job=args.job,
        status=("success" if args.exit_code == 0 else "failure"),
        exit_code=args.exit_code,
        host=socket.gethostname(),
        user=getpass.getuser(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    retries = int(final_cfg.get("retries", 0))
    backoff = float(final_cfg.get("backoff", 2.0))
    timeout = float(final_cfg.get("timeout", 10.0))

    # Build notifiers
    notifiers: List[Notifier] = []
    channels = final_cfg.get("channels")
    if not channels:
        # Default to webhook if URLs provided, else desktop
        channels = []
        if final_cfg.get("webhook", {}).get("urls"):
            channels.append("webhook")
        channels.append("desktop")

    if "webhook" in channels:
        urls = final_cfg.get("webhook", {}).get("urls", [])
        headers = final_cfg.get("webhook", {}).get("headers", {})
        for u in urls:
            # Basic sanity check
            parsed = urlparse(u)
            if not parsed.scheme or not parsed.netloc:
                if args.verbose:
                    print(f"[warn] invalid webhook url: {u}")
                continue
            notifiers.append(WebhookNotifier(url=u, headers=headers, timeout=timeout, verbose=args.verbose))
        if args.verbose and not urls:
            print("[warn] no webhook URLs configured")

    if "email" in channels:
        email_cfg = final_cfg.get("email", {})
        recipients = email_cfg.get("to", [])
        smtp_host = email_cfg.get("smtp_host")
        smtp_port = int(email_cfg.get("smtp_port", 587))
        sender = email_cfg.get("from")
        smtp_user = email_cfg.get("smtp_user")
        smtp_pass = email_cfg.get("smtp_pass")
        if not recipients or not smtp_host or not sender:
            if args.verbose:
                print("[warn] email not configured completely (to/smtp_host/from)")
        else:
            use_ssl = (smtp_port == 465)
            notifiers.append(EmailNotifier(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_user=smtp_user,
                smtp_pass=smtp_pass,
                sender=sender,
                recipients=recipients,
                timeout=timeout,
                use_tls=not use_ssl,
                use_ssl=use_ssl,
                verbose=args.verbose,
                subject_override=args.email_subject,
            ))

    if "desktop" in channels:
        notifiers.append(DesktopNotifier(verbose=args.verbose))

    if args.dry_run:
        print("[dry-run] would send:")
        print(f"title: {title}")
        print(f"message: {message}")
        print(f"channels: {[n.name() for n in notifiers]}")
        print(f"context: job={context.job} status={context.status} exit={context.exit_code} host={context.host} user={context.user} time={context.timestamp}")
        return 0

    if not notifiers:
        if args.verbose:
            print("[warn] no notifiers resolved from configuration")
        else:
            print("[error] no notifiers resolved from configuration")
        return 2

    results: List[SendResult] = []
    with ThreadPoolExecutor(max_workers=max(1, len(notifiers))) as pool:
        future_map = {pool.submit(send_with_retry, n, title, message, context, retries, backoff): n for n in notifiers}
        for fut in as_completed(future_map):
            res = fut.result()
            results.append(res)
            status = "ok" if res.ok else f"failed: {res.error}"
            if args.verbose:
                print(f"[result] {res.channel} -> {res.target} {status}")
            else:
                # Print a minimal summary even without verbose for better UX
                prefix = "[ok]" if res.ok else "[error]"
                print(f"{prefix} {res.channel} -> {res.target} {status}")

    all_ok = all(r.ok for r in results)
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())