"""Sends picture cards to Telegram."""
import io, json, logging
from . import config, data

log = logging.getLogger("trishul.telegram")


def _png(img):
    b = io.BytesIO()
    img.save(b, "PNG", optimize=True)
    b.seek(0)
    return b


def send_photo(img, caption=""):
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("no TELEGRAM_BOT_TOKEN - not sending")
        return False
    u = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
    r = data.S.post(u, data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                    files={"photo": ("card.png", _png(img), "image/png")}, timeout=60)
    if not r.ok:
        log.warning("telegram sendPhoto failed %s %s", r.status_code, r.text[:300])
    return r.ok


def send_album(imgs, caption=""):
    if len(imgs) == 1:
        return send_photo(imgs[0], caption)
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("no TELEGRAM_BOT_TOKEN - not sending")
        return False
    ok = True
    for start in range(0, len(imgs), 10):
        part = imgs[start:start + 10]
        media, files = [], {}
        for i, im in enumerate(part):
            key = f"p{i}"
            files[key] = (f"{key}.png", _png(im), "image/png")
            m = {"type": "photo", "media": f"attach://{key}"}
            if i == 0 and start == 0 and caption:
                m["caption"] = caption[:1000]
            media.append(m)
        u = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMediaGroup"
        r = data.S.post(u, data={"chat_id": config.TELEGRAM_CHAT_ID, "media": json.dumps(media)}, files=files, timeout=120)
        if not r.ok:
            log.warning("telegram sendMediaGroup failed %s %s", r.status_code, r.text[:300])
            ok = False
    return ok


def send_text(text):
    if not config.TELEGRAM_BOT_TOKEN:
        return False
    r = data.S.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    data={"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:4000]}, timeout=30)
    return r.ok


def send_document(path, caption=""):
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("no TELEGRAM_BOT_TOKEN - not sending")
        return False
    import os
    with open(path, "rb") as f:
        r = data.S.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument",
                        data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                        files={"document": (os.path.basename(path), f, "application/pdf")}, timeout=120)
    if not r.ok:
        log.warning("telegram sendDocument failed %s %s", r.status_code, r.text[:300])
    return r.ok
