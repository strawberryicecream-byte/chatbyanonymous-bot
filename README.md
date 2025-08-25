# chatbyanonymous-bot
بوت محادثة مجهولة بسيط لتليجرام.

## خطوات سريعة
1. **إبطال التوكن القديم فورًا** عبر BotFather (لو تم مشاركته): `/mybots` -> اختر بوتك -> Edit Bot -> API Token -> Revoke.
2. احصل على توكن جديد من BotFather.
3. حمّل أو انسخ ملفات المشروع (bot.py, requirements.txt, README.md) — أو نزّل ZIP الجاهز من هذه المحادثة.
4. لو هتنشر على Render: ارفع الملفات على GitHub (أو استخدم طريقة رفع الملفات في الويب)، ثم اربط الريبو بـ Render.
   - Start Command: `python bot.py`
   - Instance: Free
   - Environment variable: `TELEGRAM_TOKEN` = (التوكن الجديد)
5. للتشغيل محليًا:
   - ثبت المتطلبات: `pip install -r requirements.txt`
   - على Linux/macOS: `export TELEGRAM_TOKEN="توكنك_الجديد" && python3 bot.py`
   - على Windows PowerShell: `$env:TELEGRAM_TOKEN = "توكنك_الجديد"; python bot.py`

## ملاحظات أمنية
- لا ترفع التوكن في GitHub عام. استخدم متغير بيئة بدل وضعه في الكود.
- الكود الحالي يخزّن الحالة في الذاكرة فقط — لو البوت اتعمله restart كل المحادثات تختفي.
