"""Telegram işletme botu: menü, sipariş, masa rezervasyonu, sık sorulan sorular.

İşletmeye özel her şey isletme.json'dadır; yeni müşteriye uyarlamak için yalnız o
dosya değişir. Siparişler ve rezervasyonlar veri/ altında CSV olarak tutulur
(Excel'de doğrudan açılır) ve işletme sahibine Telegram'dan anında bildirilir.
"""
import csv
import html
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup as KB
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

KOK = Path(__file__).parent
VERI = KOK / "veri"
load_dotenv(KOK / ".env")
ISLETME = json.loads((KOK / "isletme.json").read_text(encoding="utf-8"))
URUNLER = {u["id"]: u for liste in ISLETME["menu"].values() for u in liste}
GUNLER = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")


# ---------------------------------------------------------------- saf mantık

def tl(tutar: float) -> str:
    return f"{tutar:,.0f} TL".replace(",", ".")


def kucuk(metin: str) -> str:
    """Türkçe küçük harf: 'I' → 'ı', 'İ' → 'i' (str.lower ikisini de bozar)."""
    return metin.replace("I", "ı").replace("İ", "i").lower()


def sepet_hesapla(sepet: dict[str, int]) -> tuple[list[str], int, int]:
    """(satırlar, ara toplam, teslimat ücreti)."""
    satirlar = [f"{adet} x {URUNLER[i]['ad']} — {tl(URUNLER[i]['fiyat'] * adet)}"
                for i, adet in sepet.items()]
    ara = sum(URUNLER[i]["fiyat"] * adet for i, adet in sepet.items())
    t = ISLETME["teslimat"]
    return satirlar, ara, 0 if ara >= t["ucretsiz_esik"] else t["ucret"]


def sss_bul(metin: str) -> dict | None:
    m = kucuk(metin)
    return next((s for s in ISLETME["sss"] if any(kucuk(a) in m for a in s["anahtar"])), None)


def kayit_ekle(dosya: str, satir: dict) -> None:
    yol = VERI / dosya
    VERI.mkdir(exist_ok=True)
    if not yol.exists():  # BOM yalnız başa: Excel Türkçe karakterleri doğru açsın
        with yol.open("w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=list(satir)).writeheader()
    with yol.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=list(satir)).writerow(satir)


def dolu_masa(tarih: str, saat: str) -> int:
    yol = VERI / "rezervasyonlar.csv"
    if not yol.exists():
        return 0
    with yol.open(encoding="utf-8-sig") as f:
        return sum(1 for r in csv.DictReader(f) if r["tarih"] == tarih and r["saat"] == saat)


def bos_saatler(tarih: str, simdi: datetime | None = None) -> list[str]:
    """Kapasitesi dolmamış ve (bugünse) geçmemiş saatler."""
    simdi = simdi or datetime.now()
    r = ISLETME["rezervasyon"]
    return [s for s in r["saatler"]
            if dolu_masa(tarih, s) < r["slot_kapasite"]
            and datetime.fromisoformat(f"{tarih}T{s}") > simdi]


# ---------------------------------------------------------------- klavyeler

GERI = [B("« Ana menü", callback_data="ana")]


def ana_klavye() -> KB:
    return KB([
        [B("Menü", callback_data="menu"), B("Sipariş ver", callback_data="siparis")],
        [B("Masa ayırt", callback_data="rez"), B("Sık sorulanlar", callback_data="sss")],
        [B("Adres ve saatler", callback_data="adres"), B("Yetkiliye yaz", callback_data="yetkili")],
    ])


def siparis_klavye(sepet: dict[str, int]) -> KB:
    satirlar = [[B(f"+ {u['ad']} ({tl(u['fiyat'])})", callback_data=f"ekle:{i}")]
                for i, u in URUNLER.items()]
    adet = sum(sepet.values())
    satirlar.append([B(f"Sepetim ({adet})", callback_data="sepet")])
    return KB(satirlar + [GERI])


# ---------------------------------------------------------------- yardımcılar

async def duzenle(q, metin: str, klavye: KB) -> None:
    try:
        await q.edit_message_text(metin, reply_markup=klavye, parse_mode="HTML")
    except BadRequest as e:  # aynı içerikle düzenleme Telegram'da hata sayılıyor
        if "not modified" not in str(e):
            raise


async def yetkiliye_bildir(context: ContextTypes.DEFAULT_TYPE, metin: str) -> None:
    admin = os.getenv("ADMIN_CHAT_ID")
    if admin:
        await context.bot.send_message(admin, metin, parse_mode="HTML")
    else:
        log.warning("ADMIN_CHAT_ID tanımlı değil; bildirim gönderilmedi:\n%s", metin)


def kisi(update: Update) -> str:
    u = update.effective_user
    ad = html.escape(u.full_name)
    return f"{ad} (@{u.username})" if u.username else ad


# ---------------------------------------------------------------- akışlar

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("bekleyen", None)
    await update.message.reply_text(ISLETME["karsilama"], reply_markup=ana_klavye())


async def kimim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """İşletme sahibi bunu yazıp çıkan numarayı .env'deki ADMIN_CHAT_ID'ye koyar."""
    await update.message.reply_text(f"Sohbet numaranız: {update.effective_chat.id}")


async def dugme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    d, ud = q.data, context.user_data
    sepet: dict[str, int] = ud.setdefault("sepet", {})
    bildirim = None

    if d == "ana":
        ud.pop("bekleyen", None)
        await duzenle(q, ISLETME["karsilama"], ana_klavye())

    elif d == "menu":
        bolumler = [f"<b>{html.escape(kat)}</b>\n" + "\n".join(
            f"• {html.escape(u['ad'])} — {tl(u['fiyat'])}" for u in liste)
            for kat, liste in ISLETME["menu"].items()]
        await duzenle(q, "\n\n".join(bolumler), KB([[B("Sipariş ver", callback_data="siparis")], GERI]))

    elif d == "siparis":
        await duzenle(q, "Eklemek istediğiniz ürünlere dokunun:", siparis_klavye(sepet))

    elif d.startswith("ekle:"):
        i = d.split(":", 1)[1]
        sepet[i] = sepet.get(i, 0) + 1
        bildirim = f"{URUNLER[i]['ad']} sepete eklendi"
        await duzenle(q, "Eklemek istediğiniz ürünlere dokunun:", siparis_klavye(sepet))

    elif d == "sepet":
        if not sepet:
            await duzenle(q, "Sepetiniz boş.", KB([[B("Ürün ekle", callback_data="siparis")], GERI]))
        else:
            satirlar, ara, ucret = sepet_hesapla(sepet)
            t = ISLETME["teslimat"]
            metin = "\n".join(html.escape(s) for s in satirlar)
            metin += f"\n\nAra toplam: {tl(ara)}\nTeslimat: {tl(ucret) if ucret else 'ücretsiz'}"
            metin += f"\n<b>Toplam: {tl(ara + ucret)}</b>"
            dugmeler = [[B("Ürün ekle", callback_data="siparis"), B("Sepeti boşalt", callback_data="bosalt")]]
            if ara >= t["min_tutar"]:
                dugmeler.insert(0, [B("Siparişi tamamla", callback_data="tamamla")])
            else:
                metin += f"\n\nMinimum sipariş tutarı {tl(t['min_tutar'])}."
            await duzenle(q, metin, KB(dugmeler + [GERI]))

    elif d == "bosalt":
        sepet.clear()
        await duzenle(q, "Sepetiniz boşaltıldı.", KB([[B("Ürün ekle", callback_data="siparis")], GERI]))

    elif d == "tamamla":
        ud["bekleyen"] = "adres"
        await duzenle(q, "Teslimat adresinizi ve telefon numaranızı tek mesajda yazın.", KB([GERI]))

    elif d == "rez":
        bugun = date.today()
        gunler = [bugun + timedelta(days=n) for n in range(ISLETME["rezervasyon"]["gun_sayisi"])]
        dugmeler = [[B(f"{g:%d.%m} {GUNLER[g.weekday()]}", callback_data=f"rg:{g.isoformat()}")]
                    for g in gunler if bos_saatler(g.isoformat())]
        await duzenle(q, "Hangi gün gelmek istersiniz?", KB(dugmeler + [GERI]))

    elif d.startswith("rg:"):
        tarih = d[3:]
        dugmeler = [[B(s, callback_data=f"rs:{tarih}|{s}")] for s in bos_saatler(tarih)]
        await duzenle(q, "Saat seçin (yalnız boş saatler gösteriliyor):",
                      KB(dugmeler + [[B("« Gün seç", callback_data="rez")], GERI]))

    elif d.startswith("rs:"):
        tarih, saat = d[3:].split("|")
        ud["rez"] = {"tarih": tarih, "saat": saat}
        n = ISLETME["rezervasyon"]["max_kisi"]
        sayilar = [B(str(k), callback_data=f"rk:{k}") for k in range(1, n + 1)]
        satirlar = [r for r in (sayilar[:4], sayilar[4:]) if r]
        await duzenle(q, "Kaç kişi olacaksınız?", KB(satirlar + [GERI]))

    elif d.startswith("rk:"):
        ud.setdefault("rez", {})["kisi"] = d[3:]
        ud["bekleyen"] = "rez_iletisim"
        await duzenle(q, "Rezervasyon için adınızı ve telefon numaranızı yazın.", KB([GERI]))

    elif d == "sss":
        dugmeler = [[B(s["soru"], callback_data=f"s:{n}")] for n, s in enumerate(ISLETME["sss"])]
        await duzenle(q, "Merak ettiğiniz soruyu seçin veya kendi sorunuzu yazın:", KB(dugmeler + [GERI]))

    elif d.startswith("s:"):
        s = ISLETME["sss"][int(d[2:])]
        await duzenle(q, f"<b>{html.escape(s['soru'])}</b>\n\n{html.escape(s['cevap'])}",
                      KB([[B("« Diğer sorular", callback_data="sss")], GERI]))

    elif d == "adres":
        i = ISLETME
        await duzenle(q, f"<b>Adres:</b> {html.escape(i['adres'])}\n<b>Telefon:</b> {i['telefon']}"
                         f"\n<b>Çalışma saatleri:</b> {i['saatler']}", KB([GERI]))

    elif d == "yetkili":
        ud["bekleyen"] = "yetkili"
        await duzenle(q, "Mesajınızı yazın, doğrudan işletme yetkilisine iletilecek.", KB([GERI]))

    await q.answer(bildirim)


async def metin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ud, yazi = context.user_data, update.message.text
    bekleyen = ud.pop("bekleyen", None)
    zaman = datetime.now().strftime("%Y-%m-%d %H:%M")

    if bekleyen == "adres" and ud.get("sepet"):
        satirlar, ara, ucret = sepet_hesapla(ud["sepet"])
        no = datetime.now().strftime("%m%d%H%M%S")
        kayit_ekle("siparisler.csv", {"no": no, "zaman": zaman, "musteri": update.effective_user.full_name,
                                      "urunler": "; ".join(satirlar), "toplam": ara + ucret, "adres_tel": yazi})
        await yetkiliye_bildir(context, f"<b>Yeni sipariş #{no}</b>\n{kisi(update)}\n"
                                        + "\n".join(html.escape(s) for s in satirlar)
                                        + f"\nToplam: {tl(ara + ucret)}\nAdres/tel: {html.escape(yazi)}")
        ud["sepet"] = {}
        await update.message.reply_text(
            f"Siparişiniz alındı (#{no}). Tahmini teslimat: {ISLETME['teslimat']['sure']}. Afiyet olsun!",
            reply_markup=ana_klavye())

    elif bekleyen == "rez_iletisim" and "kisi" in ud.get("rez", {}):
        r = ud.pop("rez")
        if dolu_masa(r["tarih"], r["saat"]) >= ISLETME["rezervasyon"]["slot_kapasite"]:
            await update.message.reply_text("Üzgünüz, bu saat az önce doldu. Lütfen başka bir saat seçin.",
                                            reply_markup=ana_klavye())
            return
        kayit_ekle("rezervasyonlar.csv", {"zaman": zaman, "tarih": r["tarih"], "saat": r["saat"],
                                          "kisi": r["kisi"], "iletisim": yazi})
        gun = date.fromisoformat(r["tarih"])
        await yetkiliye_bildir(context, f"<b>Yeni rezervasyon</b>\n{gun:%d.%m.%Y} {r['saat']} · "
                                        f"{r['kisi']} kişi\n{kisi(update)}\n{html.escape(yazi)}")
        await update.message.reply_text(
            f"Rezervasyonunuz alındı: {gun:%d.%m.%Y} saat {r['saat']}, {r['kisi']} kişi. Görüşmek üzere!",
            reply_markup=ana_klavye())

    elif bekleyen == "yetkili":
        await yetkiliye_bildir(context, f"<b>Müşteri mesajı</b>\n{kisi(update)}\n{html.escape(yazi)}")
        await update.message.reply_text("Mesajınız yetkiliye iletildi, en kısa sürede dönüş yapılacak.",
                                        reply_markup=ana_klavye())

    elif s := sss_bul(yazi):
        await update.message.reply_text(s["cevap"], reply_markup=ana_klavye())

    else:
        await update.message.reply_text(
            "Bunu tam anlayamadım. Aşağıdan seçim yapabilir veya \"Yetkiliye yaz\" ile bize ulaşabilirsiniz.",
            reply_markup=ana_klavye())


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN tanımlı değil: .env.example dosyasını .env olarak kopyalayıp doldurun.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kimim", kimim))
    app.add_handler(CallbackQueryHandler(dugme))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, metin))
    log.info("%s botu çalışıyor", ISLETME["ad"])
    app.run_polling()


if __name__ == "__main__":
    main()
