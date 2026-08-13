"""
Unit test murni untuk logika verifikasi KRS (tanpa jaringan / tanpa Flask).

Cakupan:
    * is_allowed_domain — whitelist domain & anti-SSRF
    * _clean / _norm_kelas — normalisasi
    * _parse_fields — ekstraksi Nama/NPM/Kelas dari teks KRS
    * cross_check — pencocokan input pemilih vs KRS asli
"""

import pytest

from evoting.engines.krs_verifier import KRSVerifier, _clean, _norm_kelas


# --------------------------------------------------------------------------- #
# is_allowed_domain (anti-SSRF)
# --------------------------------------------------------------------------- #
class TestIsAllowedDomain:
    @pytest.mark.parametrize("url", [
        "https://gunadarma.ac.id/krs/123",
        "https://baak.gunadarma.ac.id/validasi/546634",
        "https://sub.deep.gunadarma.ac.id/x",
    ])
    def test_domain_dan_subdomain_diterima(self, verifier, url):
        assert verifier.is_allowed_domain(url) is True

    @pytest.mark.parametrize("url", [
        "http://gunadarma.ac.id/krs/123",          # bukan HTTPS
        "https://evilgunadarma.ac.id/x",           # bukan subdomain sah
        "https://gunadarma.ac.id.evil.com/x",      # domain tempelan
        "https://example.com/krs",                 # domain lain
        "https://192.168.0.1/internal",            # IP literal
        "https://127.0.0.1/x",                     # loopback literal
        "ftp://gunadarma.ac.id/x",                 # skema salah
        "not-a-url",                               # sampah
        "",                                        # kosong
    ])
    def test_url_tidak_sah_ditolak(self, verifier, url):
        assert verifier.is_allowed_domain(url) is False

    def test_whitelist_case_insensitive(self, verifier):
        assert verifier.is_allowed_domain("https://GunaDarma.AC.ID/krs") is True


# --------------------------------------------------------------------------- #
# Normalisasi
# --------------------------------------------------------------------------- #
class TestNormalisasi:
    def test_clean_upper_dan_rapikan_spasi(self):
        assert _clean("  budi   santoso ") == "BUDI SANTOSO"

    def test_clean_none_jadi_string_kosong(self):
        assert _clean(None) == ""

    @pytest.mark.parametrize("raw,expected", [
        ("3KA11 (L-p)", "3KA11"),
        ("3-KA-11", "3KA11"),
        (" 3ka11 ", "3KA11"),
    ])
    def test_norm_kelas(self, raw, expected):
        assert _norm_kelas(raw) == expected


# --------------------------------------------------------------------------- #
# _parse_fields
# --------------------------------------------------------------------------- #
class TestParseFields:
    def test_parse_multiline(self, verifier):
        text = "NAMA : BUDI SANTOSO\nNPM : 50411234\nKELAS : 3KA11\n"
        fields = verifier._parse_fields(text)
        assert fields["name"] == "BUDI SANTOSO"
        assert fields["npm"] == "50411234"
        assert fields["kelas"] == "3KA11"

    def test_parse_satu_baris_tidak_menelan_field_lain(self, verifier):
        text = "NAMA : BUDI SANTOSO   NPM : 50411234   KELAS : 3KA11"
        fields = verifier._parse_fields(text)
        assert fields["name"] == "BUDI SANTOSO"
        assert fields["npm"] == "50411234"

    def test_parse_teks_kosong(self, verifier):
        fields = verifier._parse_fields("")
        assert fields == {"name": "", "npm": "", "kelas": ""}


# --------------------------------------------------------------------------- #
# cross_check
# --------------------------------------------------------------------------- #
class TestCrossCheck:
    def test_semua_cocok(self, verifier):
        inp = {"name": "Budi Santoso", "npm": "50411234", "kelas": "3KA11"}
        krs = {"name": "BUDI SANTOSO", "npm": "50411234", "kelas": "3KA11 (L-p)"}
        ok, reason, mismatches = verifier.cross_check(inp, krs)
        assert ok is True
        assert reason is None
        assert mismatches == []

    def test_npm_salah(self, verifier):
        inp = {"name": "Budi", "npm": "50411234", "kelas": "3KA11"}
        krs = {"name": "Budi", "npm": "99999999", "kelas": "3KA11"}
        ok, reason, mismatches = verifier.cross_check(inp, krs)
        assert ok is False
        assert "NPM" in reason
        assert any(m["field"] == "NPM" for m in mismatches)

    def test_beberapa_field_salah_dilaporkan_semua(self, verifier):
        inp = {"name": "Andi", "npm": "111", "kelas": "1IA01"}
        krs = {"name": "Budi", "npm": "222", "kelas": "3KA11"}
        ok, reason, mismatches = verifier.cross_check(inp, krs)
        assert ok is False
        fields = {m["field"] for m in mismatches}
        assert fields == {"NPM", "Nama", "Kelas"}

    def test_kelas_beda_sufiks_tetap_cocok(self, verifier):
        inp = {"name": "Budi", "npm": "111", "kelas": "3KA11"}
        krs = {"name": "Budi", "npm": "111", "kelas": "3KA11 (L-p)"}
        ok, _, mismatches = verifier.cross_check(inp, krs)
        assert ok is True
        assert mismatches == []
