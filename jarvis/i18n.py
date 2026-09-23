"""Turkish and English for the interface itself.

JARVIS has always *answered* in Turkish — the model does that on its own. The
buttons, the labels and the error messages were English regardless, which is
an odd experience when everything else is in your language.

Only the shell is translated here. Replies are the model's, and telling it
which language to answer in is a separate thing: `set_language` adds a line
to the system prompt so the two stay in step rather than the window being
Turkish while the answers are English.

Anything missing from the table falls back to English rather than showing a
key, because a half-translated interface is still usable and `MISSING_KEY` is
not.
"""

from __future__ import annotations

from .config import get_setting

ENGLISH = "en"
TURKISH = "tr"

LANGUAGES = {
    ENGLISH: "English",
    TURKISH: "Türkçe",
}

# Only the strings a person actually sees in the window.
STRINGS: dict[str, dict[str, str]] = {
    TURKISH: {
        # sidebar
        "Chat": "Sohbet",
        "Image Gen": "Görsel Üret",
        "Code": "Kod",
        "THINKING MODE": "DÜŞÜNME MODU",
        "Settings": "Ayarlar",
        "Check for Updates": "Güncelleme Denetle",
        "Ready": "Hazır",
        "Thinking...": "Düşünüyor...",
        "Listening...": "Dinliyor...",
        "Generating image...": "Görsel üretiliyor...",
        "Stopped": "Durduruldu",
        # buttons
        "Send": "Gönder",
        "Stop": "Durdur",
        "Save": "Kaydet",
        "Close": "Kapat",
        "Allow once": "Bir kez izin ver",
        "Deny": "Reddet",
        "Update now": "Şimdi güncelle",
        "Later": "Daha sonra",
        "Open Folder": "Klasörü aç",
        "Open Image": "Görseli aç",
        "Generate Image": "Görsel üret",
        "Test": "Sına",
        "Copy reply": "Yanıtı kopyala",
        "Copy code": "Kodu kopyala",
        "Find": "Bul",
        "Export": "Dışa aktar",
        "Shortcuts": "Kısayollar",
        # settings
        "API keys": "API anahtarları",
        "Models per mode": "Mod başına model",
        "configured": "tanımlı",
        "not set": "tanımsız",
        "testing…": "sınanıyor…",
        "works": "çalışıyor",
        "key rejected": "anahtar reddedildi",
        "valid, but no credit": "geçerli, ancak kredi yok",
        "rate limited — try again shortly": "hız sınırı — birazdan tekrar deneyin",
        "free": "ücretsiz",
        "paid": "ücretli",
        # permission dialog
        "JARVIS needs permission": "JARVIS izin istiyor",
        "Allow this?": "Buna izin veriyor musunuz?",
        "Run a command on this PC": "Bu bilgisayarda bir komut çalıştır",
        "Write to a file": "Bir dosyaya yaz",
        "Delete a file": "Bir dosyayı sil",
        "Capture your screen": "Ekranınızı yakala",
        "Read a file into the conversation": "Bir dosyayı sohbete oku",
        "Send project code to an AI provider": "Proje kodunu bir yapay zekâ sağlayıcısına gönder",
        "Run this project's test suite": "Bu projenin testlerini çalıştır",
        "Fetch something over the network": "Ağ üzerinden bir şey getir",
        "Let the agent carry out this plan": "Ajanın bu planı uygulamasına izin ver",
        # modes
        "Low": "Düşük",
        "Mid": "Orta",
        "High": "Yüksek",
        "Max": "Azami",
        "Hyperdrive": "Hiper",
        "Security": "Güvenlik",
        # misc
        "Update available": "Güncelleme mevcut",
        "You have": "Mevcut sürüm",
        "Downloading...": "İndiriliyor...",
        "Image generation": "Görsel üretimi",
        "Size:": "Boyut:",
        "Quality:": "Kalite:",
        "Generated image will appear here": "Üretilen görsel burada belirecek",
        "Ask JARVIS anything... (/image prompt to generate)":
            "JARVIS'e her şeyi sorun... (üretmek için /image komutu)",
    },
}

# Told to the model so the answers match the window.
ANSWER_IN = {
    TURKISH: (
        "Kullanıcı Türkçe arayüz kullanıyor. Kullanıcı başka bir dilde "
        "yazmadıkça Türkçe yanıt ver."
    ),
}

_current = ENGLISH


def available() -> dict[str, str]:
    return dict(LANGUAGES)


def current() -> str:
    return _current


def load_from_env() -> str:
    """Pick up JARVIS_LANGUAGE at start-up."""
    global _current
    wanted = get_setting("JARVIS_LANGUAGE", ENGLISH).strip().lower()
    _current = wanted if wanted in LANGUAGES else ENGLISH
    return _current


def set_language(code: str) -> str:
    global _current
    code = (code or "").strip().lower()
    if code not in LANGUAGES:
        names = ", ".join(f"{k} ({v})" for k, v in LANGUAGES.items())
        return f"No such language '{code}'. Available: {names}"
    _current = code
    return code


def t(text: str) -> str:
    """Translate one interface string, or hand back the English."""
    if _current == ENGLISH:
        return text
    return STRINGS.get(_current, {}).get(text, text)


def answer_instruction() -> str:
    """The line added to the system prompt so replies match the window."""
    return ANSWER_IN.get(_current, "")
