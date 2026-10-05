from datetime import datetime

import pytest

import bot


@pytest.fixture(autouse=True)
def gecici_veri(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "VERI", tmp_path)


def test_turkce_kucuk_harf():
    assert bot.kucuk("ISPARTA İzmir") == "ısparta izmir"


def test_sss_anahtar_kelimeyle_bulunur():
    assert bot.sss_bul("Kredi KARTI geçiyor mu?")["soru"] == "Kartla ödeme alıyor musunuz?"
    assert bot.sss_bul("ÇÖLYAK hastasıyım") is not None
    assert bot.sss_bul("hava nasıl") is None


def test_sepet_teslimat_ucreti_ve_esik():
    _, ara, ucret = bot.sepet_hesapla({"b1": 1, "i1": 1})
    assert (ara, ucret) == (320, 40)
    _, ara, ucret = bot.sepet_hesapla({"b2": 3})
    assert (ara, ucret) == (960, 0)


def test_dolu_saat_listeden_cikar():
    tarih, saat = "2099-01-01", "19:00"
    for _ in range(bot.ISLETME["rezervasyon"]["slot_kapasite"]):
        bot.kayit_ekle("rezervasyonlar.csv", {"zaman": "-", "tarih": tarih, "saat": saat,
                                              "kisi": "2", "iletisim": "Ayşe Çınar 0555"})
    assert saat not in bot.bos_saatler(tarih)
    assert "20:00" in bot.bos_saatler(tarih)


def test_bugunun_gecmis_saatleri_gosterilmez():
    simdi = datetime(2099, 1, 1, 15, 30)
    assert bot.bos_saatler("2099-01-01", simdi) == ["19:00", "20:00", "21:00"]


def test_csv_excel_icin_tek_bom_ve_turkce(tmp_path):
    for n in range(2):
        bot.kayit_ekle("x.csv", {"ad": f"Şükrü {n}"})
    ham = (tmp_path / "x.csv").read_bytes()
    assert ham.count(b"\xef\xbb\xbf") == 1
    assert "Şükrü 1" in ham.decode("utf-8-sig")
