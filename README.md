# 🏔 أوراس — Awrass

<div align="center">

**ChatGPT → OpenAI API مجانية | Free ChatGPT-to-OpenAI-API Proxy**

*نسخة عربية متقدمة من mse_ai_api — مستلهمة ومُحسَّنة بشكل جوهري*

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?logo=fastapi)]()
[![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)]()
[![Docker](https://img.shields.io/badge/Docker-2CA5E0?logo=docker&logoColor=white)]()
[![Tests](https://img.shields.io/badge/tests-20%2F20%20passing-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-brightgreen)]()
[![Arabic](https://img.shields.io/badge/language-العربية-gold)]()

**`github.com/swordenkisk/awrass` | swordenkisk 🇩🇿 | 2026**

</div>

---

## ما هو أوراس؟ | What is Awrass?

أوراس يحوّل ChatGPT Web إلى OpenAI API متوافقة 100% — **بدون تكاليف API**. استخدمه في n8n، أي SDK يدعم OpenAI، أو أي تطبيق يتوقع OpenAI API.

---

## التشغيل | Quick Start

### Docker (موصى به)
```bash
git clone https://github.com/swordenkisk/awrass
cd awrass
docker-compose up --build -d
# API جاهزة على: http://localhost:7777
# Dashboard:      http://localhost:7777/dashboard
```

### تثبيت يدوي
```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

---

## الاستخدام | Usage

```python
# يعمل مع أي OpenAI SDK بدون تعديل
from openai import OpenAI

client = OpenAI(
    api_key="awrass-secret-2026",
    base_url="http://localhost:7777/v1"
)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "مرحبا!"}]
)
print(response.choices[0].message.content)
```

---

## التحسينات عن mse_ai_api | Improvements

| الميزة | mse_ai_api | أوراس |
|--------|-----------|-------|
| جلسات المتصفح | 1 | ✅ Pool قابل للتكوين (N جلسات) |
| إعادة المحاولة | ❌ | ✅ Retry مع exponential backoff |
| انتظار ذكي | polling بسيط | ✅ يكتشف نهاية التوليد بدقة |
| مفاتيح API | مفتاح واحد | ✅ متعدد المفاتيح + أدوار |
| Rate Limiting | ❌ | ✅ حد طلبات لكل مفتاح/دقيقة |
| Dashboard | ❌ | ✅ لوحة تحكم ويب كاملة |
| سجل الطلبات | ❌ | ✅ تتبع كل طلب مع زمن الاستجابة |
| اللغة العربية | ❌ | ✅ وضع عربي مع حقن تعليمات |
| استخراج JSON | regex بسيط | ✅ 3 استراتيجيات + تصحيح تلقائي |
| Vision/Images | ❌ | ✅ استخراج محتوى الصور |
| كوكيز تسجيل الدخول | ❌ | ✅ دعم ملف cookies.json |
| اختبارات | ❌ | ✅ 20 اختبار (كلها تنجح) |
| توثيق | ❌ | ✅ Dashboard + /docs + دليل n8n |

---

## المسارات | Endpoints

| المسار | الوصف |
|--------|-------|
| `POST /v1/chat/completions` | OpenAI Chat Completions API |
| `POST /v1/responses` | OpenAI Responses API |
| `GET  /v1/models` | قائمة النماذج |
| `GET  /health` | حالة الخادم |
| `GET  /stats` | إحصائيات الاستخدام |
| `GET  /dashboard` | لوحة تحكم الويب |
| `GET  /docs` | توثيق API التفاعلي |

---

## متغيرات البيئة | Environment Variables

```bash
AWRASS_API_KEY=awrass-secret-2026   # مفتاح API الرئيسي
AWRASS_EXTRA_KEYS=key2,key3         # مفاتيح إضافية
AWRASS_POOL_SIZE=2                   # عدد جلسات المتصفح
AWRASS_RATE_LIMIT=20                 # طلبات/دقيقة لكل مفتاح
AWRASS_TIMEOUT=120                   # مهلة كل طلب (ثانية)
AWRASS_HEADLESS=true                 # متصفح مخفي
AWRASS_ARABIC_MODE=true              # وضع اللغة العربية
AWRASS_COOKIE_FILE=cookies.json      # ملف كوكيز تسجيل الدخول
```

---

## الاختبارات | Tests

```bash
python tests/test_awrass.py
# 20/20 ✅
```

---

## الترخيص | License

MIT — © 2026 swordenkisk 🇩🇿 — Tlemcen, Algeria

*"أوراس — الجبل الذي يصمد."*
