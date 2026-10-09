# -*- coding: utf-8 -*-
"""
NOVA HOST — Telegram bot hosting dashboard starter
Python 3.10+
Install: pip install -r requirements.txt
Set BOT_TOKEN and ADMIN_IDS as environment variables before running.

Important:
- This is a working Telegram bot UI and project-file manager starter.
- Actually running customer bots safely requires a VPS/container isolation and resource limits.
- Domain search/purchase requires a registrar API; this template records requests only.
- Anonymous chat starts only after both users opt in. Telegram bots cannot message a user
  until that user has opened the bot at least once.
"""
import os
import re
import json
import time
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("nova-host")

TOKEN = os.getenv("BOT_TOKEN", "8987634980:AAHZVMB067LA8XnEtozu3zsd1PZCo9BUMrY").strip()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "7580802072").split(",")
    if x.strip().isdigit()
}
DATA_DIR = Path(os.getenv("NOVA_DATA_DIR", "nova_data"))
PROJECTS_DIR = DATA_DIR / "projects"
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "database.json"

def load_db():
    if DB_FILE.exists():
        try:
            return json.loads(DB_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Could not read database")
    return {"users": {}, "hosting_requests": [], "domain_requests": [], "points": {}, "reminder": {"enabled": False, "text": "🌹 صلّوا على النبي ﷺ", "interval_minutes": 360}}

db = load_db()
db.setdefault("reminder", {"enabled": False, "text": "🌹 صلّوا على النبي ﷺ", "interval_minutes": 360})
def save_db():
    DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

# Anonymous sessions and pending consent requests. These are in-memory and reset on restart.
active_chats = {}      # user_id -> partner_id
pending_anon = {}      # target_id -> requester_id
awaiting = {}          # user_id -> mode
upload_wait = set()

def is_admin(uid):
    return uid in ADMIN_IDS

def main_keyboard(uid):
    rows = [
        [InlineKeyboardButton("🚀 الاستضافة", callback_data="hosting"),
         InlineKeyboardButton("📁 مشاريعي", callback_data="projects")],
        [InlineKeyboardButton("🌐 دوميناتي", callback_data="mydomains"),
         InlineKeyboardButton("➕ إنشاء دومين", callback_data="domain")],
        [InlineKeyboardButton("📊 التحليل المتقدم", callback_data="stats"),
         InlineKeyboardButton("⚡ باقات السرعة", callback_data="speed")],
        [InlineKeyboardButton("🎨 صنع الملصقات", callback_data="stickers"),
         InlineKeyboardButton("🕶️ هوية مجهولة", callback_data="anonymous")],
        [InlineKeyboardButton("🧠 مولد الأفكار", callback_data="ideas"),
         InlineKeyboardButton("💰 نقاطي", callback_data="points")],
        [InlineKeyboardButton("🎁 هدية من البوت", callback_data="gift"),
         InlineKeyboardButton("📨 الدعم الفني", callback_data="support")],
        [InlineKeyboardButton("👤 حسابي", callback_data="account"),
         InlineKeyboardButton("📚 المساعدة", callback_data="help")],
    ]
    if is_admin(uid):
        rows.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]])

def user_record(user):
    uid = str(user.id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "name": user.first_name or "مستخدم",
            "joined": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "files": [],
            "domains": []
        }
        db["points"].setdefault(uid, 0)
        save_db()
    else:
        db["users"][uid]["name"] = user.first_name or "مستخدم"
    return db["users"][uid]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user_record(u)
    await update.message.reply_text(
        "⚡ 🥷 *NOVA HOST* 🥷 ⚡\n\n"
        "🚀 Your Powerful Hosting Platform\n"
        "استضف ملفات مشاريعك ونظّم طلباتك من مكان واحد.\n\n"
        f"💰 رصيدك: {db['points'].get(str(u.id), 0)} نقطة\n"
        f"📅 انضممت في: {user_record(u)['joined']}\n"
        f"🆔 آيديك: `{u.id}`\n\n"
        "اختر خدمة من لوحة التحكم:",
        parse_mode="Markdown",
        reply_markup=main_keyboard(u.id)
    )

async def show_home(q):
    await q.edit_message_text("⚡ *NOVA HOST* — اختر الخدمة المطلوبة:", parse_mode="Markdown",
                              reply_markup=main_keyboard(q.from_user.id))

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data == "home":
        await show_home(q)
    elif data == "hosting":
        await q.edit_message_text(
            "🚀 *الاستضافة*\n\n"
            "ارفع ملف `.py` هنا لتسجيله ضمن مشاريعك.\n"
            "هذه النسخة تحفظ الملفات وتدير الطلبات؛ تشغيل ملفات المستخدمين تلقائيًا يحتاج VPS معزولًا ومراقبة موارد.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 رفع ملف مشروع", callback_data="upload")],
                [InlineKeyboardButton("🧾 طلب استضافة", callback_data="hostreq")],
                [InlineKeyboardButton("📁 مشاريعي", callback_data="projects")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
    elif data == "upload":
        upload_wait.add(uid)
        await q.edit_message_text("📤 أرسل ملف Python بامتداد `.py` كمستند في هذه المحادثة.", reply_markup=back_kb())
    elif data == "hostreq":
        awaiting[uid] = "hostreq"
        await q.edit_message_text("🧾 اكتب تفاصيل الاستضافة المطلوبة في رسالة واحدة (نوع المشروع والموارد).", reply_markup=back_kb())
    elif data == "projects":
        rec = user_record(q.from_user)
        files = rec.get("files", [])
        if not files:
            body = "📁 *مشاريعي*\n\nلا توجد ملفات حتى الآن. افتح الاستضافة ثم اضغط رفع ملف مشروع."
        else:
            body = "📁 *مشاريعي*\n\n" + "\n".join(f"• `{name}`" for name in files[-20:])
        await q.edit_message_text(body, parse_mode="Markdown", reply_markup=back_kb())
    elif data == "domain":
        awaiting[uid] = "domain"
        await q.edit_message_text("🌐 أرسل اسم الدومين المطلوب مثل `example.com`.\nسنسجل الطلب فقط؛ التحقق والشراء يحتاجان API لمزود دومينات.", parse_mode="Markdown", reply_markup=back_kb())
    elif data == "mydomains":
        rec = user_record(q.from_user)
        domains = rec.get("domains", [])
        body = "🌐 *دوميناتي*\n\n" + ("\n".join("• " + d for d in domains) if domains else "لم تسجل أي طلب دومين بعد.")
        await q.edit_message_text(body, parse_mode="Markdown", reply_markup=back_kb())
    elif data == "stats":
        rec = user_record(q.from_user)
        await q.edit_message_text(
            f"📊 *التحليل المتقدم*\n\n📁 عدد ملفاتك: {len(rec.get('files', []))}\n"
            f"🌐 طلبات الدومين: {len(rec.get('domains', []))}\n"
            f"💰 النقاط: {db['points'].get(str(uid), 0)}",
            parse_mode="Markdown", reply_markup=back_kb()
        )
    elif data == "speed":
        await q.edit_message_text("⚡ *باقات السرعة*\n\nالباقات هنا واجهة مبدئية. لتفعيل موارد فعلية، اربطها بخادم الاستضافة ونظام الفوترة.", parse_mode="Markdown", reply_markup=back_kb())
    elif data == "stickers":
        awaiting[uid] = "sticker"
        await q.edit_message_text("🎨 أرسل صورة وسأحوّلها إلى ملف PNG مناسب للتجهيز كملصق. هذه الوظيفة لا تزيل الخلفية تلقائيًا.", reply_markup=back_kb())
    elif data == "anonymous":
        awaiting[uid] = "anon_id"
        await q.edit_message_text(
            "🕶️ *محادثة بهوية مجهولة*\n\nأرسل آيدي المستخدم الرقمي. سيصله طلب قبول/رفض، ولن تبدأ المحادثة إلا بعد موافقته.\n"
            "يجب أن يكون قد فتح البوت من قبل. استخدم /stop لإنهاء المحادثة.",
            parse_mode="Markdown", reply_markup=back_kb()
        )
    elif data.startswith("anon_yes:"):
        requester = int(data.split(":", 1)[1])
        if pending_anon.get(uid) != requester:
            await q.edit_message_text("انتهى الطلب أو لم يعد صالحًا.")
            return
        if uid in active_chats or requester in active_chats:
            pending_anon.pop(uid, None)
            await q.edit_message_text("أحد الطرفين مشغول في محادثة أخرى.")
            return
        pending_anon.pop(uid, None)
        active_chats[uid] = requester
        active_chats[requester] = uid
        await q.edit_message_text("✅ وافقت. بدأت المحادثة المجهولة. أرسل رسائلك هنا واستخدم /stop للإنهاء.")
        try:
            await context.bot.send_message(requester, "✅ وافق الطرف الآخر. بدأت المحادثة المجهولة؛ استخدم /stop للإنهاء.")
        except Exception:
            active_chats.pop(uid, None); active_chats.pop(requester, None)
            await q.message.reply_text("تعذر إخطار الطرف الآخر.")
    elif data.startswith("anon_no:"):
        requester = int(data.split(":", 1)[1])
        pending_anon.pop(uid, None)
        await q.edit_message_text("تم رفض طلب المحادثة.")
        try:
            await context.bot.send_message(requester, "❌ الطرف الآخر رفض طلب المحادثة.")
        except Exception:
            pass
    elif data == "ideas":
        await q.edit_message_text("🧠 *مولد الأفكار*\n\nأفكار مشاريع: بوت إدارة مجموعات، بوت تنبيهات، بوت ملفات، بوت أسئلة وأجوبة.\nأرسل وصف فكرتك للدعم لإضافتها.", parse_mode="Markdown", reply_markup=back_kb())
    elif data == "points":
        await q.edit_message_text(f"💰 رصيدك الحالي: {db['points'].get(str(uid), 0)} نقطة.", reply_markup=back_kb())
    elif data == "gift":
        await q.edit_message_text("🎁 نظام الهدايا يحتاج إعداد قواعد النقاط أو الدفع من الأدمن.", reply_markup=back_kb())
    elif data == "support":
        await q.edit_message_text("📨 للدعم: تواصل مع مدير البوت. يمكن تحديد حساب الدعم داخل إعدادات المشروع.", reply_markup=back_kb())
    elif data == "account":
        rec = user_record(q.from_user)
        await q.edit_message_text(f"👤 *حسابي*\n\nالاسم: {rec['name']}\nالآيدي: `{uid}`\nتاريخ الانضمام: {rec['joined']}\nالنقاط: {db['points'].get(str(uid), 0)}", parse_mode="Markdown", reply_markup=back_kb())
    elif data == "help":
        await q.edit_message_text("📚 ارفع ملفات `.py` من قسم الاستضافة، واطلب دومين من قسم الدومينات. المحادثة المجهولة تتطلب موافقة الطرف الآخر. استخدم /stop لإنهاء المحادثة.", reply_markup=back_kb())
    elif data == "admin":
        if not is_admin(uid):
            await q.edit_message_text("غير مسموح.")
            return
        await q.edit_message_text(
            f"👑 *لوحة الأدمن*\n\n👥 المستخدمون المسجلون: {len(db['users'])}\n"
            f"🧾 طلبات الاستضافة: {len(db['hosting_requests'])}\n🌐 طلبات الدومين: {len(db['domain_requests'])}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]])
        )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    partner = active_chats.pop(uid, None)
    if partner:
        active_chats.pop(partner, None)
        await update.message.reply_text("🛑 انتهت المحادثة المجهولة.")
        try:
            await context.bot.send_message(partner, "🛑 أنهى الطرف الآخر المحادثة.")
        except Exception:
            pass
    else:
        await update.message.reply_text("لا توجد محادثة نشطة.", reply_markup=main_keyboard(uid))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    uid = msg.from_user.id
    user_record(msg.from_user)

    # Receive uploaded project files
    if uid in upload_wait and msg.document:
        name = Path(msg.document.file_name or "project.py").name
        if not name.lower().endswith(".py"):
            await msg.reply_text("❌ ارفع ملفًا بامتداد .py فقط.")
            return
        user_dir = PROJECTS_DIR / str(uid)
        user_dir.mkdir(parents=True, exist_ok=True)
        target = user_dir / name
        tgfile = await context.bot.get_file(msg.document.file_id)
        await tgfile.download_to_drive(custom_path=str(target))
        rec = user_record(msg.from_user)
        if name not in rec["files"]:
            rec["files"].append(name)
        upload_wait.discard(uid)
        save_db()
        await msg.reply_text(f"✅ تم حفظ الملف: {name}\n⚠️ تم حفظه فقط؛ لم يتم تشغيله تلقائيًا.")
        return

    mode = awaiting.get(uid)
    if mode == "reminder_text" and msg.text:
        if not is_admin(uid):
            awaiting.pop(uid, None)
            await msg.reply_text("غير مسموح.")
            return
        new_text = msg.text.strip()
        if not new_text:
            await msg.reply_text("النص لا يمكن أن يكون فارغًا.")
            return
        db["reminder"]["text"] = new_text
        awaiting.pop(uid, None)
        save_db()
        await msg.reply_text("✅ تم تحديث نص التنبيه التلقائي.")
        return
    if mode == "reminder_interval" and msg.text:
        if not is_admin(uid):
            awaiting.pop(uid, None)
            await msg.reply_text("غير مسموح.")
            return
        try:
            minutes = int(msg.text.strip())
        except ValueError:
            await msg.reply_text("أرسل رقمًا صحيحًا بالدقائق.")
            return
        if not 15 <= minutes <= 10080:
            await msg.reply_text("اختر مدة من 15 إلى 10080 دقيقة.")
            return
        db["reminder"]["interval_minutes"] = minutes
        awaiting.pop(uid, None)
        save_db()
        # Reschedule the repeating job immediately
        job = context.job_queue.get_jobs_by_name("auto_reminder")
        for item in job:
            item.schedule_removal()
        if db["reminder"].get("enabled"):
            context.job_queue.run_repeating(send_auto_reminder, interval=minutes * 60, first=minutes * 60, name="auto_reminder")
        await msg.reply_text(f"✅ تم ضبط التنبيه كل {minutes} دقيقة.")
        return
    if mode == "hostreq" and msg.text:
        db["hosting_requests"].append({"user_id": uid, "text": msg.text, "time": int(time.time())})
        awaiting.pop(uid, None); save_db()
        await msg.reply_text("✅ تم تسجيل طلب الاستضافة. التنفيذ يحتاج إعداد خادم الاستضافة.")
        for admin in ADMIN_IDS:
            try: await context.bot.send_message(admin, f"🧾 طلب استضافة جديد من {uid}:\n{msg.text}")
            except Exception: pass
        return
    if mode == "domain" and msg.text:
        domain = msg.text.strip().lower()
        if not re.fullmatch(r"(?=.{3,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}", domain):
            await msg.reply_text("❌ صيغة الدومين غير صحيحة. مثال: example.com")
            return
        db["domain_requests"].append({"user_id": uid, "domain": domain, "time": int(time.time())})
        rec = user_record(msg.from_user); rec["domains"].append(domain)
        awaiting.pop(uid, None); save_db()
        await msg.reply_text(f"✅ سجلت طلب الدومين {domain}. لم يتم التحقق من توفره أو شراؤه.")
        for admin in ADMIN_IDS:
            try: await context.bot.send_message(admin, f"🌐 طلب دومين من {uid}: {domain}")
            except Exception: pass
        return
    if mode == "anon_id" and msg.text:
        try: target = int(msg.text.strip())
        except ValueError:
            await msg.reply_text("أرسل آيدي رقميًا صحيحًا."); return
        awaiting.pop(uid, None)
        if target == uid:
            await msg.reply_text("لا يمكنك مراسلة نفسك."); return
        if uid in active_chats:
            await msg.reply_text("أنهِ محادثتك الحالية باستخدام /stop أولًا."); return
        try:
            await context.bot.send_message(
                target, "🕶️ لديك طلب محادثة مجهولة. هل توافق؟",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ قبول", callback_data=f"anon_yes:{uid}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"anon_no:{uid}")
                ]])
            )
            pending_anon[target] = uid
            await msg.reply_text("📨 أرسلت الطلب. انتظر رد الطرف الآخر.")
        except Exception:
            await msg.reply_text("تعذر إرسال الطلب. تأكد أن الآيدي صحيح وأن الطرف الآخر فتح البوت من قبل.")
        return
    if mode == "sticker":
        if msg.photo:
            photo = msg.photo[-1]
            f = await context.bot.get_file(photo.file_id)
            from io import BytesIO
            buf = BytesIO()
            await f.download_to_memory(out=buf)
            buf.seek(0)
            await msg.reply_document(document=buf, filename="nova_sticker_source.jpg",
                                     caption="🎨 صورتك جاهزة للتجهيز كملصق. أرسل /start للعودة للقائمة.")
        else:
            await msg.reply_text("أرسل صورة كصورة عادية، وليس كنص.")
        return

    # Relay content anonymously. Never forward sender metadata.
    partner = active_chats.get(uid)
    if partner:
        try:
            if msg.text:
                await context.bot.send_message(partner, msg.text)
            elif msg.photo:
                await context.bot.send_photo(partner, msg.photo[-1].file_id, caption=msg.caption)
            elif msg.sticker:
                await context.bot.send_sticker(partner, msg.sticker.file_id)
            elif msg.document:
                await context.bot.send_document(partner, msg.document.file_id, caption=msg.caption)
            elif msg.voice:
                await context.bot.send_voice(partner, msg.voice.file_id, caption=msg.caption)
            elif msg.video:
                await context.bot.send_video(partner, msg.video.file_id, caption=msg.caption)
            else:
                await msg.reply_text("نوع الرسالة هذا غير مدعوم في المحادثة المجهولة.")
        except Exception:
            await msg.reply_text("تعذر إرسال الرسالة للطرف الآخر.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    awaiting.pop(uid, None)
    upload_wait.discard(uid)
    await update.message.reply_text("تم الإلغاء.", reply_markup=main_keyboard(uid))

async def send_auto_reminder(context: ContextTypes.DEFAULT_TYPE):
    text_to_send = db.get("reminder", {}).get("text", "").strip()
    if not text_to_send:
        return
    # Send only to users who have previously started the bot.
    for user_id in list(db.get("users", {}).keys()):
        try:
            await context.bot.send_message(chat_id=int(user_id), text=text_to_send)
        except Exception as exc:
            log.info("Reminder not delivered to %s: %s", user_id, exc)

def main():
    if not TOKEN:
        raise SystemExit("ضع BOT_TOKEN في متغيرات البيئة قبل التشغيل.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    # Start the saved reminder schedule, if enabled.
    if db.get("reminder", {}).get("enabled"):
        minutes = max(15, int(db["reminder"].get("interval_minutes", 360)))
        app.job_queue.run_repeating(send_auto_reminder, interval=minutes * 60, first=minutes * 60, name="auto_reminder")
    log.info("NOVA HOST started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
