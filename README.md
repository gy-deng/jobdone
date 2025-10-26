# JobDone – Job Completion Notification Tool

Whether you're compiling kernels, training models, or just waiting for `sleep 600` to finish, JobDone ensures you never miss the moment your job ends—successfully, tragically, or somewhere in between.

---

## 🚀 Quick Start

### Build & Install

```bash
make build
# Binary located at dist/jobdone
make install   # Installs to /usr/local/bin for root, ~/.local/bin for regular users
```

### Configuration (YAML)

- Config file locations:
  - `~/.config/jobdone/config.yaml`
  - `.jobdone.yaml` in project root

- Initialize template:

```bash
mkdir -p ~/.config/jobdone
cp .jobdone.yaml.template ~/.config/jobdone/config.yaml
# Edit channels, webhook, email, etc. as needed
```

---

## 🔔 Notification Examples

### Always Notify

```bash
long_task && jobdone -j long_task -c email
```

### Notify on Success or Failure

```bash
my_job; jobdone -j my_job -e $? --on failure -c email
my_job; jobdone -j my_job -e $? --on success -c email
```

### Use STDIN as Message

```bash
my_job && echo "Task finished" | jobdone --stdin -j my_job -c desktop
```

---

## 📧 Email Notifications

### Via CLI

```bash
jobdone -c email \
  --email-to you@example.com --email-from noreply@example.com \
  --smtp-host smtp.example.com --smtp-port 587 --smtp-user myuser \
  --smtp-pass-prompt -t "Job Done"
```

### Via Environment Variables

```bash
export JOBDONE_SMTP_HOST=smtp.example.com
export JOBDONE_SMTP_PORT=587
export JOBDONE_SMTP_USER=myuser
export JOBDONE_SMTP_PASS=secret
export JOBDONE_EMAIL_FROM=noreply@example.com
export JOBDONE_EMAIL_TO=me@example.com
jobdone -c email -j build
```

---

## 🌐 Webhook Notifications

- Request format: `POST` to `--webhook-url` with `application/json`
- Example payload:

```json
{
  "title": "Job Done",
  "message": "Job testjob finished with exit code 0.",
  "context": {
    "job": "testjob",
    "status": "success",
    "exit_code": 0,
    "host": "xxx",
    "user": "xxx",
    "timestamp": "2025-10-18T12:34:56Z",
    "source": "jobdone"
  }
}
```

- Custom headers:
  - CLI: `--header "X-Token: your-token"` (repeatable)
  - YAML: `webhook.headers: { X-Token: ${JOBDONE_WEBHOOK_TOKEN} }`

- Multiple URLs:
  - CLI: repeat `--webhook-url`
  - YAML: `webhook.urls: [url1, url2]`

---

## ⚙️ CLI Options & Defaults

- Configuration priority: `CLI > YAML > ENV`
- YAML search order:
  1. `~/.config/jobdone/config.yaml`
  2. `./.jobdone.yaml`
  3. `./jobdone.yaml`
  4. `./config.yaml`
  5. Or use `--config PATH` to specify

### General Options

| Option | Description |
|--------|-------------|
| `--version` | Print version info |
| `-j, --job` | Job name (default: `job`) |
| `-t, --title` | Notification title (default: `Job Done`) |
| `-m, --message` | Custom message (default: auto-generated) |
| `--stdin` | Read message from STDIN |
| `-e, --exit-code` | Exit code (default: `0`) |
| `--on` | Trigger condition: `success`, `failure`, `always` (default: `always`) |
| `-c, --channel` | Notification channels (default: `webhook,desktop` if webhook configured, else `desktop`) |
| `--timeout` | Timeout in seconds (default: `10.0`) |
| `--retries` | Retry count (default: `0`) |
| `--backoff` | Backoff in seconds (default: `2.0`) |
| `--config` | Path to config file |
| `-v, --verbose` | Verbose logging |
| `--dry-run` | Print payload without sending |

---

## 🌍 Environment Variables

| Variable | Description |
|----------|-------------|
| `JOBDONE_CHANNELS` | Comma-separated list of channels |
| `JOBDONE_WEBHOOK_URLS` | Comma-separated list of webhook URLs |
| `JOBDONE_EMAIL_TO` | Comma-separated list of email recipients |
| `JOBDONE_SMTP_HOST` / `PORT` / `USER` / `PASS` | SMTP configuration |
| `JOBDONE_EMAIL_FROM` | Sender address |
| `JOBDONE_ON` | Trigger condition |
| `JOBDONE_RETRIES` / `BACKOFF` / `TIMEOUT` | Retry/backoff/timeout settings |

---

## 🌐 Webhook Options

| Option | Description |
|--------|-------------|
| `--webhook-url` | Webhook URL (repeatable) |
| `--header` | Custom headers (repeatable) |

> Note: YAML does not support environment variable interpolation. Use CLI for dynamic values like `--header "X-Token: $JOBDONE_WEBHOOK_TOKEN"`.

---

## 📧 Email Options

| Option | Description |
|--------|-------------|
| `--email-to` | Email recipients (repeatable) |
| `--email-subject` | Email subject (default: `--title`) |
| `--smtp-host` / `--smtp-port` / `--smtp-user` / `--smtp-pass` | SMTP settings |
| `--smtp-pass-prompt` | Prompt for password interactively |
| `--email-from` | Sender address |

- Connection strategy:
  - Port `465`: implicit SSL
  - Other ports: plaintext with STARTTLS fallback
- Authentication strategy:
  - Uses `smtp_user` or falls back to `email.from`
  - If authentication fails, sending may still proceed depending on server policy
