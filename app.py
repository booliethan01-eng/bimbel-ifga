from flask import Flask, render_template_string, abort, request, session, redirect, url_for, jsonify
from datetime import timedelta, date
import urllib.request
import json
import sqlite3
import random
import socket
import os

app = Flask(__name__)
app.secret_key = "kunci-rahasia-bimbel-ifga-eksklusif-2026"
app.permanent_session_lifetime = timedelta(days=30)

NAMA_BIMBEL = "IFGA Kids"
WHATSAPP = "6281345305510"       # ganti dengan nomor WA ibu (awali 62)
PIN_GURU = "9999"                # PIN rahasia untuk ruang guru (/guru)
GEMINI_API_KEY = "AQ.Ab8RN6LQbO6vz1CPjrbu-_4Jg68cw_kBNHPlOfcY7qzTRoIiFA"  # tempel ulang API key kamu di sini
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database_bimbel.db")

# ================= DATABASE (VERIFIKASI, STREAK HARIAN, & PR GURU) =================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nama TEXT UNIQUE NOT NULL,
                pin TEXT NOT NULL,
                avatar TEXT DEFAULT '🐱',
                poin INTEGER DEFAULT 0,
                soal_benar INTEGER DEFAULT 0,
                soal_salah INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                streak INTEGER DEFAULT 0,
                terakhir_belajar TEXT DEFAULT ''
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS nilai_bab (
                user_id INTEGER,
                kode_bab TEXT,
                nilai INTEGER,
                PRIMARY KEY (user_id, kode_bab)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS tugas_pr (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kelas INTEGER,
                slug TEXT,
                judul_bab TEXT,
                catatan TEXT
            )
        """)

init_db()

def perbarui_streak_harian(user_id):
    hari_ini = date.today()
    kemarin = hari_ini - timedelta(days=1)
    str_hari_ini = hari_ini.isoformat()
    str_kemarin = kemarin.isoformat()

    with get_db() as db:
        u = db.execute("SELECT streak, terakhir_belajar FROM users WHERE id = ?", (user_id,)).fetchone()
        if not u or u["terakhir_belajar"] == str_hari_ini:
            return 0
        streak_baru = (u["streak"] + 1) if u["terakhir_belajar"] == str_kemarin else 1
        bonus = 15
        db.execute("""
            UPDATE users
            SET streak = ?, terakhir_belajar = ?, poin = poin + ?
            WHERE id = ?
        """, (streak_baru, str_hari_ini, bonus, user_id))
        return bonus

HADIAH_PERINGKAT = {
    1: {"ikon": "👑", "nama": "Mahkota Raja", "tier": "LEGENDARY", "warna": "#eab308", "bg": "#fef08a", "border": "3px solid #eab308"},
    2: {"ikon": "💎", "nama": "Kristal Epik", "tier": "EPIC", "warna": "#9333ea", "bg": "#f3e8ff", "border": "3px solid #a855f7"},
    3: {"ikon": "🔥", "nama": "Aura Api", "tier": "RARE", "warna": "#2563eb", "bg": "#dbeafe", "border": "3px solid #3b82f6"},
    4: {"ikon": "🎩", "nama": "Topi Sulap", "tier": "SPECIAL", "warna": "#059669", "bg": "#d1fae5", "border": "2px solid #10b981"},
    5: {"ikon": "🎓", "nama": "Topi Pintar", "tier": "SPECIAL", "warna": "#0284c7", "bg": "#e0f2fe", "border": "2px solid #0ea5e9"},
}

def ambil_leaderboard():
    with get_db() as db:
        rows = db.execute("""
            SELECT id, nama, avatar, poin, soal_benar, soal_salah, streak
            FROM users WHERE status = 'aktif'
            ORDER BY poin DESC, soal_benar DESC, id ASC
        """).fetchall()
    hasil = []
    for idx, r in enumerate(rows, start=1):
        hadiah = HADIAH_PERINGKAT.get(idx)
        total_soal = r["soal_benar"] + r["soal_salah"]
        akurasi = round((r["soal_benar"] / total_soal) * 100) if total_soal > 0 else 0
        hasil.append({
            "rank": idx, "id": r["id"], "nama": r["nama"], "avatar": r["avatar"],
            "poin": r["poin"], "benar": r["soal_benar"], "salah": r["soal_salah"],
            "streak": r["streak"], "total_soal": total_soal, "akurasi": akurasi, "hadiah": hadiah
        })
    return hasil

def get_user_aktif():
    uid = session.get("user_id")
    if not uid:
        return None
    lb = ambil_leaderboard()
    return next((u for u in lb if u["id"] == uid), None)

# ================= ILUSTRASI BANGUN DATAR (SVG) =================
SVG_BANGUN = """
<div style="display:flex; gap:18px; flex-wrap:wrap; margin:14px 0;">
  <div style="text-align:center; background:#fff; padding:12px 18px; border-radius:14px; border:2px solid #cbd5e1;">
    <svg width="76" height="70"><polygon points="38,5 5,65 71,65" fill="#fde047" stroke="#ca8a04" stroke-width="3"/></svg>
    <div style="font-size:0.9rem; font-weight:800;">Segitiga</div>
    <div style="font-size:0.8rem; color:#64748b;">3 Sisi, 3 Sudut</div>
  </div>
  <div style="text-align:center; background:#fff; padding:12px 18px; border-radius:14px; border:2px solid #cbd5e1;">
    <svg width="76" height="70"><rect x="8" y="8" width="60" height="54" rx="4" fill="#93c5fd" stroke="#2563eb" stroke-width="3"/></svg>
    <div style="font-size:0.9rem; font-weight:800;">Segi Empat</div>
    <div style="font-size:0.8rem; color:#64748b;">4 Sisi, 4 Sudut</div>
  </div>
  <div style="text-align:center; background:#fff; padding:12px 18px; border-radius:14px; border:2px solid #cbd5e1;">
    <svg width="76" height="70"><circle cx="38" cy="35" r="29" fill="#fca5a5" stroke="#dc2626" stroke-width="3"/></svg>
    <div style="font-size:0.9rem; font-weight:800;">Lingkaran</div>
    <div style="font-size:0.8rem; color:#64748b;">1 Sisi Lengkung</div>
  </div>
</div>
"""

# ================= DATA MATERI TERPERINCI (36 BAB: KELAS 1 - 6) =================
MATERI = [
    # KELAS 1
    {"kelas": 1, "slug": "penjumlahan-1-sampai-20", "judul": "Bab 1: Penjumlahan Bilangan 1 sampai 20",
     "isi": "<h3>1. Konsep Penjumlahan</h3><p><strong>Penjumlahan (+)</strong> artinya menggabungkan dua kelompok benda menjadi lebih banyak.</p><h3>2. Langkah Mudah</h3><ol><li>Simpan angka terbesar di kepala.</li><li>Buka jari sebanyak angka kecil, lalu hitung maju.</li></ol><div class='contoh'>Contoh: 8 + 5 = 13 (mulai dari 8, hitung maju: 9, 10, 11, 12, 13)</div>"},
    {"kelas": 1, "slug": "pengurangan-1-sampai-20", "judul": "Bab 2: Pengurangan Bilangan 1 sampai 20",
     "isi": "<h3>1. Konsep Pengurangan</h3><p><strong>Pengurangan (-)</strong> artinya mengambil sebagian benda sehingga sisanya lebih sedikit.</p><div class='contoh'>Contoh: 14 - 6 = 8 (mulai dari 14, hitung mundur 6 langkah: 13, 12, 11, 10, 9, 8)</div>"},
    {"kelas": 1, "slug": "nilai-tempat-puluhan-satuan", "judul": "Bab 3: Mengenal Puluhan dan Satuan",
     "isi": "<h3>1. Rumah Nilai Tempat</h3><p>Angka depan (kiri) adalah <strong>Puluhan</strong>, angka belakang (kanan) adalah <strong>Satuan</strong>.</p><div class='contoh'>17 = 1 puluhan + 7 satuan (10 + 7)</div>"},
    {"kelas": 1, "slug": "membandingkan-bilangan", "judul": "Bab 4: Membandingkan & Mengurutkan Bilangan",
     "isi": "<h3>1. Cara Membandingkan</h3><p>Lihat angka puluhannya dulu; jika sama, baru bandingkan angka satuannya.</p><div class='contoh'>18 lebih besar dari 12 &nbsp;|&nbsp; Urutan kecil ke besar: 9, 11, 14, 19</div>"},
    {"kelas": 1, "slug": "mengenal-waktu-jam", "judul": "Bab 5: Mengenal Waktu dan Jam Tepat",
     "isi": "<h3>1. Jarum Jam</h3><p><strong>Jarum pendek</strong> menunjuk jam, <strong>jarum panjang</strong> di angka 12 berarti tepat (.00).</p><div class='contoh'>Jarum pendek di 4, jarum panjang di 12 = Pukul 04.00</div>"},
    {"kelas": 1, "slug": "bangun-datar-sederhana", "judul": "Bab 6: Mengenal Bentuk Bangun Datar",
     "isi": SVG_BANGUN + "<ul><li><strong>Segitiga:</strong> 3 sisi &amp; 3 sudut.</li><li><strong>Segi Empat:</strong> 4 sisi &amp; 4 sudut.</li><li><strong>Lingkaran:</strong> 1 sisi melengkung tanpa sudut.</li></ul>"},

    # KELAS 2
    {"kelas": 2, "slug": "penjumlahan-bersusun", "judul": "Bab 1: Penjumlahan Bersusun Ratusan",
     "isi": "<h3>1. Aturan Bersusun</h3><p>Luruskan satuan dengan satuan, puluhan dengan puluhan, lalu jumlahkan dari belakang.</p><div class='contoh'>126 + 57 = 183 (6 + 7 = 13 &rarr; tulis 3, simpan 1 ke puluhan)</div>"},
    {"kelas": 2, "slug": "pengurangan-bersusun", "judul": "Bab 2: Pengurangan Bersusun & Teknik Meminjam",
     "isi": "<h3>1. Teknik Meminjam</h3><p>Jika angka atas lebih kecil dari bawah, pinjam 1 puluhan (10) dari angka di sebelah kirinya.</p><div class='contoh'>72 - 37 = 35 (12 - 7 = 5, lalu 6 - 3 = 3)</div>"},
    {"kelas": 2, "slug": "konsep-perkalian-awal", "judul": "Bab 3: Pengenalan Perkalian Dasar",
     "isi": "<h3>1. Penjumlahan Berulang</h3><p><strong>A x B</strong> artinya angka B dijumlahkan sebanyak A kali.</p><div class='contoh'>3 x 4 = 4 + 4 + 4 = 12</div>"},
    {"kelas": 2, "slug": "pembagian-awal", "judul": "Bab 4: Pengenalan Pembagian Dasar",
     "isi": "<h3>1. Pengurangan Berulang</h3><p>Membagi benda sama banyak sampai habis (0).</p><div class='contoh'>12 : 3 = 4 (12 - 3 - 3 - 3 - 3 = 0)</div>"},
    {"kelas": 2, "slug": "satuan-panjang-berat", "judul": "Bab 5: Pengukuran Panjang (m & cm) dan Berat (kg & g)",
     "isi": "<h3>1. Konversi Satuan</h3><div class='contoh'>1 meter (m) = 100 cm &nbsp;|&nbsp; 1 kilogram (kg) = 1.000 gram</div>"},
    {"kelas": 2, "slug": "nilai-mata-uang", "judul": "Bab 6: Mengenal Nilai Mata Uang Rupiah",
     "isi": "<h3>1. Kesetaraan Uang</h3><div class='contoh'>2 lembar Rp5.000 = Rp10.000 &nbsp;|&nbsp; Rp2.000 + Rp5.000 = Rp7.000</div>"},

    # KELAS 3
    {"kelas": 3, "slug": "perkalian-1-sampai-10", "judul": "Bab 1: Perkalian Bilangan 1 sampai 10",
     "isi": "<h3>1. Sifat Pertukaran</h3><p>Hasil perkalian sama walau posisi ditukar: <strong>7 x 6 = 6 x 7 = 42</strong>.</p><div class='contoh'>Semua angka dikali 0 = 0 | Semua angka dikali 1 = angka itu sendiri</div>"},
    {"kelas": 3, "slug": "pembagian-dasar", "judul": "Bab 2: Pembagian Bilangan",
     "isi": "<h3>1. Kebalikan Perkalian</h3><div class='contoh'>56 : 8 = 7 (karena 8 x 7 = 56)</div>"},
    {"kelas": 3, "slug": "operasi-hitung-campuran", "judul": "Bab 3: Operasi Hitung Campuran (KABATAKU)",
     "isi": "<h3>1. Urutan Pengerjaan</h3><p>Kerjakan tanda kurung dulu, lalu <strong>Kali (x) &amp; Bagi (:)</strong>, terakhir <strong>Tambah (+) &amp; Kurang (-)</strong>.</p><div class='contoh'>10 + 4 x 3 = 10 + 12 = 22</div>"},
    {"kelas": 3, "slug": "pecahan-sederhana", "judul": "Bab 4: Mengenal Pecahan Sederhana",
     "isi": "<h3>1. Pembilang &amp; Penyebut</h3><p>Pada <strong>a/b</strong>, <em>a</em> adalah bagian yang diambil dan <em>b</em> adalah jumlah seluruh potongan sama besar.</p><div class='contoh'>1 kue dipotong 4 sama besar, dimakan 1 = 1/4</div>"},
    {"kelas": 3, "slug": "satuan-waktu-lama", "judul": "Bab 5: Konversi Satuan Waktu (Jam, Menit, Detik)",
     "isi": "<div class='contoh'>1 jam = 60 menit &nbsp;|&nbsp; 1 menit = 60 detik &nbsp;|&nbsp; 1 hari = 24 jam</div>"},
    {"kelas": 3, "slug": "keliling-bangun-datar", "judul": "Bab 6: Keliling Persegi dan Persegi Panjang",
     "isi": SVG_BANGUN + "<div class='contoh'>Keliling Persegi = 4 x sisi &nbsp;|&nbsp; Keliling Persegi Panjang = 2 x (p + l)</div>"},

    # KELAS 4
    {"kelas": 4, "slug": "fpb-dan-kpk", "judul": "Bab 1: Kelipatan dan Faktor Bilangan (KPK & FPB)",
     "isi": "<h3>1. KPK &amp; FPB</h3><p><strong>KPK</strong> = kelipatan sama terkecil | <strong>FPB</strong> = faktor pembagi sama terbesar.</p><div class='contoh'>KPK(4, 6) = 12 &nbsp;|&nbsp; FPB(12, 18) = 6</div>"},
    {"kelas": 4, "slug": "pecahan-senilai", "judul": "Bab 2: Pecahan Senilai dan Penyederhanaan",
     "isi": "<p>Kalikan atau bagi pembilang dan penyebut dengan bilangan yang sama.</p><div class='contoh'>2/3 = 4/6 &nbsp;|&nbsp; 6/8 (:2) = 3/4</div>"},
    {"kelas": 4, "slug": "pembulatan-dan-penaksiran", "judul": "Bab 3: Pembulatan Bilangan ke Puluhan & Ratusan",
     "isi": "<p>Angka &lt; 5 bulatkan ke bawah, angka &ge; 5 bulatkan ke atas.</p><div class='contoh'>47 dibulatkan ke puluhan terdekat = 50</div>"},
    {"kelas": 4, "slug": "luas-bangun-datar", "judul": "Bab 4: Luas Persegi, Persegi Panjang, dan Segitiga",
     "isi": SVG_BANGUN + "<div class='contoh'>Persegi = s x s | Persegi Panjang = p x l | Segitiga = 1/2 x alas x tinggi</div>"},
    {"kelas": 4, "slug": "mengenal-jenis-sudut", "judul": "Bab 5: Mengenal Jenis-Jenis Sudut",
     "isi": "<p><strong>Lancip</strong> (&lt;90°), <strong>Siku-siku</strong> (90°), <strong>Tumpul</strong> (90°–180°), <strong>Lurus</strong> (180°).</p>"},
    {"kelas": 4, "slug": "hubungan-antar-garis", "judul": "Bab 6: Hubungan Antar Garis (Sejajar & Berpotongan)",
     "isi": "<p><strong>Garis Sejajar</strong> tidak pernah berpotongan walau diperpanjang (contoh: rel kereta api).</p>"},

    # KELAS 5
    {"kelas": 5, "slug": "operasi-pecahan-beda-penyebut", "judul": "Bab 1: Penjumlahan & Pengurangan Pecahan Beda Penyebut",
     "isi": "<p>Samakan penyebut menggunakan KPK terlebih dahulu.</p><div class='contoh'>1/2 + 1/3 = 3/6 + 2/6 = 5/6</div>"},
    {"kelas": 5, "slug": "perkalian-pembagian-pecahan", "judul": "Bab 2: Perkalian dan Pembagian Pecahan",
     "isi": "<p><strong>Perkalian:</strong> atas x atas, bawah x bawah. <strong>Pembagian:</strong> balik pecahan kedua lalu kalikan.</p><div class='contoh'>3/4 : 1/2 = 3/4 x 2/1 = 3/2</div>"},
    {"kelas": 5, "slug": "desimal-dan-persen", "judul": "Bab 3: Mengubah Pecahan, Desimal, dan Persen",
     "isi": "<div class='contoh'>1/2 = 0,5 = 50% &nbsp;|&nbsp; 1/4 = 0,25 = 25% &nbsp;|&nbsp; 3/4 = 0,75 = 75%</div>"},
    {"kelas": 5, "slug": "kecepatan-jarak-waktu", "judul": "Bab 4: Kecepatan, Jarak, dan Waktu (Segitiga JKW)",
     "isi": "<div class='contoh'>Jarak = Kecepatan x Waktu | Kecepatan = Jarak : Waktu</div>"},
    {"kelas": 5, "slug": "skala-dan-denah", "judul": "Bab 5: Skala pada Peta dan Denah",
     "isi": "<div class='contoh'>Jarak Sebenarnya = Jarak Peta x Angka Skala (cm &rarr; km bagi 100.000)</div>"},
    {"kelas": 5, "slug": "volume-kubus-dan-balok", "judul": "Bab 6: Volume Kubus dan Balok",
     "isi": "<div class='contoh'>Volume Kubus = r³ &nbsp;|&nbsp; Volume Balok = p x l x t</div>"},

    # KELAS 6
    {"kelas": 6, "slug": "operasi-bilangan-bulat", "judul": "Bab 1: Operasi Hitung Bilangan Bulat Negatif",
     "isi": "<p>Tanda sama hasilnya (+), tanda beda hasilnya (-).</p><div class='contoh'>(-7) + 10 = 3 &nbsp;|&nbsp; (-4) x (-5) = 20</div>"},
    {"kelas": 6, "slug": "hitung-campuran-pecahan-desimal", "judul": "Bab 2: Operasi Campuran Pecahan, Desimal, dan Persen",
     "isi": "<p>Ubah ke bentuk yang sama dulu (desimal semua atau pecahan semua).</p><div class='contoh'>0,5 + 1/4 = 0,5 + 0,25 = 0,75</div>"},
    {"kelas": 6, "slug": "luas-keliling-lingkaran", "judul": "Bab 3: Keliling dan Luas Lingkaran",
     "isi": SVG_BANGUN + "<div class='contoh'>Keliling = 2 x &pi; x r &nbsp;|&nbsp; Luas = &pi; x r x r (&pi; = 22/7 atau 3,14)</div>"},
    {"kelas": 6, "slug": "bangun-ruang-gabungan", "judul": "Bab 4: Volume Tabung dan Prisma",
     "isi": "<div class='contoh'>Volume Tabung = &pi; x r x r x t</div>"},
    {"kelas": 6, "slug": "koordinat-kartesius", "judul": "Bab 5: Sistem Koordinat Kartesius (x, y)",
     "isi": "<p>Baca sumbu mendatar <strong>(x)</strong> terlebih dahulu, lalu sumbu tegak <strong>(y)</strong>.</p>"},
    {"kelas": 6, "slug": "statistika-mean-median-modus", "judul": "Bab 6: Statistika (Mean, Median, dan Modus)",
     "isi": "<p><strong>Mean</strong> = rata-rata | <strong>Median</strong> = nilai tengah setelah diurutkan | <strong>Modus</strong> = nilai terbanyak.</p>"},
]

# ================= GENERATOR SOAL BERTINGKAT (MUDAH, SEDANG, SULIT) =================
def _buat_pilihan(jawaban_benar, satuan="", izinkan_negatif=False):
    salah_set = set()
    while len(salah_set) < 2:
        selisih = random.choice([-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6, 10])
        kandidat = jawaban_benar + selisih
        if kandidat != jawaban_benar and (izinkan_negatif or kandidat > 0):
            salah_set.add(kandidat)
    angka_opsi = [jawaban_benar] + list(salah_set)
    random.shuffle(angka_opsi)
    return [f"{a}{satuan}" for a in angka_opsi], angka_opsi.index(jawaban_benar)

def _buat_pilihan_teks(benar, salah1, salah2):
    opsi = [benar, salah1, salah2]
    random.shuffle(opsi)
    return opsi, opsi.index(benar)

def _generator_satu_soal(slug, level="mudah"):
    # ---- KELAS 1 ----
    if slug == "penjumlahan-1-sampai-20":
        if level == "mudah":
            a, b = random.randint(1, 5), random.randint(1, 5)
            pil, idx = _buat_pilihan(a + b)
            return {"tanya": f"{a} + {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b}."}
        elif level == "sedang":
            a, b = random.randint(6, 12), random.randint(4, 8)
            pil, idx = _buat_pilihan(a + b)
            return {"tanya": f"{a} + {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b}."}
        else:
            a, b = random.randint(5, 11), random.randint(4, 8)
            pil, idx = _buat_pilihan(a + b, " kelereng")
            return {"tanya": f"Budi punya {a} kelereng, lalu diberi Ayah {b} kelereng lagi. Jumlah kelereng Budi sekarang adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b} kelereng."}

    elif slug == "pengurangan-1-sampai-20":
        if level == "mudah":
            a = random.randint(5, 10); b = random.randint(1, a - 1)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        elif level == "sedang":
            a = random.randint(12, 20); b = random.randint(4, 9)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        else:
            a = random.randint(13, 20); b = random.randint(5, 9)
            pil, idx = _buat_pilihan(a - b, " kue")
            return {"tanya": f"Ibu membuat {a} kue donat. Sebanyak {b} kue dimakan adik. Sisa kue ibu adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b} kue."}

    elif slug == "nilai-tempat-puluhan-satuan":
        p, s = random.randint(1, 9), random.randint(1, 9)
        if level == "mudah":
            pil, idx = _buat_pilihan(p)
            return {"tanya": f"Angka PULUHAN pada bilangan {p*10+s} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{p*10+s} terdiri dari {p} puluhan dan {s} satuan."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(s)
            return {"tanya": f"Angka SATUAN pada bilangan {p*10+s} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Angka paling belakang adalah satuan, yaitu {s}."}
        else:
            pil, idx = _buat_pilihan(p * 10 + s)
            return {"tanya": f"Aku adalah bilangan yang terdiri dari {p} puluhan dan {s} satuan. Bilangan berapakah aku?", "pilihan": pil, "jawaban": idx, "bahas": f"{p} puluhan ({p*10}) + {s} satuan = {p*10+s}."}

    elif slug == "membandingkan-bilangan":
        if level == "mudah":
            a, b = random.sample(range(1, 10), 2)
            pil, idx = _buat_pilihan_teks("lebih besar dari" if a > b else "lebih kecil dari", "lebih kecil dari" if a > b else "lebih besar dari", "sama dengan")
            return {"tanya": f"Bilangan {a} ... bilangan {b}.", "pilihan": pil, "jawaban": idx, "bahas": f"{a} {'lebih dari' if a > b else 'kurang dari'} {b}."}
        elif level == "sedang":
            a, b = random.sample(range(11, 20), 2)
            pil, idx = _buat_pilihan_teks("lebih besar dari" if a > b else "lebih kecil dari", "lebih kecil dari" if a > b else "lebih besar dari", "sama dengan")
            return {"tanya": f"Bilangan {a} ... bilangan {b}.", "pilihan": pil, "jawaban": idx, "bahas": f"{a} {'lebih besar dari' if a > b else 'lebih kecil dari'} {b}."}
        else:
            nums = sorted(random.sample(range(8, 20), 3))
            pil, idx = _buat_pilihan_teks(f"{nums[0]}, {nums[1]}, {nums[2]}", f"{nums[2]}, {nums[1]}, {nums[0]}", f"{nums[1]}, {nums[0]}, {nums[2]}")
            return {"tanya": f"Urutan bilangan {nums[1]}, {nums[2]}, {nums[0]} dari yang TERKECIL adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Urutan dari terkecil: {nums[0]}, {nums[1]}, {nums[2]}."}

    elif slug == "mengenal-waktu-jam":
        jam = random.randint(1, 10)
        if level == "mudah":
            pil, idx = _buat_pilihan(jam, ".00")
            return {"tanya": f"Jarum pendek di angka {jam} dan jarum panjang di 12. Sekarang pukul ...", "pilihan": pil, "jawaban": idx, "bahas": f"Pukul {jam}.00."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(jam + 2, ".00")
            return {"tanya": f"Sekarang pukul {jam}.00. Dua jam lagi adalah pukul ...", "pilihan": pil, "jawaban": idx, "bahas": f"{jam} + 2 = pukul {jam+2}.00."}
        else:
            pil, idx = _buat_pilihan(2, " jam")
            return {"tanya": f"Siti belajar mulai pukul {jam}.00 dan selesai pukul {jam+2}.00. Lama Siti belajar adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Dari pukul {jam}.00 ke {jam+2}.00 lamanya 2 jam."}

    elif slug == "bangun-datar-sederhana":
        if level == "mudah":
            benda, bentuk, s1, s2 = random.choice([("Roda sepeda", "Lingkaran", "Segitiga", "Segi Empat"), ("Papan tulis", "Segi Empat", "Lingkaran", "Segitiga")])
            pil, idx = _buat_pilihan_teks(bentuk, s1, s2)
            return {"tanya": f"{benda} memiliki bentuk bangun datar ...", "pilihan": pil, "jawaban": idx, "bahas": f"{benda} berbentuk {bentuk}."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(3, " sisi")
            return {"tanya": "Bangun datar segitiga memiliki jumlah sisi sebanyak ...", "pilihan": pil, "jawaban": idx, "bahas": "Segitiga mempunyai 3 sisi dan 3 sudut."}
        else:
            pil, idx = _buat_pilihan_teks("Lingkaran", "Segitiga", "Segi Empat")
            return {"tanya": "Aku adalah bangun datar yang hanya memiliki 1 sisi melengkung dan tidak punya titik sudut. Aku adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "Lingkaran memiliki 1 sisi lengkung tanpa sudut."}

    # ---- KELAS 2 ----
    elif slug == "penjumlahan-bersusun":
        if level == "mudah":
            a, b = random.randint(20, 50), random.randint(10, 35)
            pil, idx = _buat_pilihan(a + b)
            return {"tanya": f"{a} + {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b}."}
        elif level == "sedang":
            a, b = random.randint(120, 340), random.randint(35, 89)
            pil, idx = _buat_pilihan(a + b)
            return {"tanya": f"{a} + {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b}."}
        else:
            a, b = random.randint(145, 250), random.randint(125, 210)
            pil, idx = _buat_pilihan(a + b, " buku")
            return {"tanya": f"Perpustakaan memiliki {a} buku cerita dan {b} buku pelajaran. Jumlah seluruh buku adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b} buku."}

    elif slug == "pengurangan-bersusun":
        if level == "mudah":
            a = random.randint(45, 89); b = random.randint(11, 34)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        elif level == "sedang":
            a = random.randint(71, 95); b = random.randint(26, 49)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        else:
            a = random.randint(230, 350); b = random.randint(115, 185)
            pil, idx = _buat_pilihan(a - b, " butir")
            return {"tanya": f"Pedagang memiliki {a} butir telur, lalu terjual {b} butir. Sisa telur pedagang adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b} butir."}

    elif slug == "konsep-perkalian-awal":
        if level == "mudah":
            a, b = random.randint(2, 4), random.randint(2, 5)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"{a} x {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b}."}
        elif level == "sedang":
            a, b = random.randint(3, 6), random.randint(4, 7)
            pil, idx = _buat_pilihan_teks(" + ".join([str(b)] * a), " + ".join([str(a)] * (b + 1)), f"{a} + {b}")
            return {"tanya": f"Bentuk penjumlahan berulang dari {a} x {b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} artinya angka {b} dijumlahkan sebanyak {a} kali."}
        else:
            a, b = random.randint(4, 6), random.randint(5, 8)
            pil, idx = _buat_pilihan(a * b, " roda")
            return {"tanya": f"Di tempat parkir ada {a} mobil. Setiap mobil memiliki {b} roda. Jumlah seluruh roda mobil adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b} roda."}

    elif slug == "pembagian-awal":
        if level == "mudah":
            b, h = random.randint(2, 4), random.randint(2, 5)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        elif level == "sedang":
            b, h = random.randint(4, 6), random.randint(4, 7)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        else:
            b, h = random.randint(3, 5), random.randint(4, 7)
            pil, idx = _buat_pilihan(h, " permen")
            return {"tanya": f"Ibu membagi {b*h} permen kepada {b} anak sama banyak. Setiap anak mendapat ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h} permen."}

    elif slug == "satuan-panjang-berat":
        if level == "mudah":
            m = random.randint(2, 7)
            pil, idx = _buat_pilihan(m * 100, " cm")
            return {"tanya": f"{m} meter = ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"{m} x 100 = {m*100} cm."}
        elif level == "sedang":
            kg = random.randint(2, 6)
            pil, idx = _buat_pilihan(kg * 1000, " gram")
            return {"tanya": f"Berat semangka {kg} kg sama dengan ... gram.", "pilihan": pil, "jawaban": idx, "bahas": f"{kg} x 1.000 = {kg*1000} gram."}
        else:
            m, cm = random.randint(2, 4), random.choice([25, 50, 75])
            pil, idx = _buat_pilihan(m * 100 + cm, " cm")
            return {"tanya": f"Panjang pita Rina {m} meter lebih {cm} cm. Panjang seluruh pita Rina adalah ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"{m} m = {m*100} cm, ditambah {cm} cm = {m*100+cm} cm."}

    elif slug == "nilai-mata-uang":
        if level == "mudah":
            a, b = random.choice([(1000, 2000), (2000, 5000), (5000, 5000)])
            pil, idx = _buat_pilihan(a + b, " rupiah")
            return {"tanya": f"Rp{a} + Rp{b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a+b} rupiah."}
        elif level == "sedang":
            lembar = random.randint(3, 5)
            pil, idx = _buat_pilihan(lembar * 2000, " rupiah")
            return {"tanya": f"{lembar} lembar uang Rp2.000 nilainya sama dengan ...", "pilihan": pil, "jawaban": idx, "bahas": f"{lembar} x Rp2.000 = Rp{lembar*2000}."}
        else:
            harga = random.choice([6000, 7000, 8000])
            pil, idx = _buat_pilihan(10000 - harga, " rupiah")
            return {"tanya": f"Andi membeli buku seharga Rp{harga} dengan uang Rp10.000. Uang kembalian Andi adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Rp10.000 - Rp{harga} = Rp{10000-harga}."}

    # ---- KELAS 3 ----
    elif slug == "perkalian-1-sampai-10":
        if level == "mudah":
            a, b = random.randint(2, 5), random.randint(2, 6)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"{a} x {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b}."}
        elif level == "sedang":
            a, b = random.randint(6, 9), random.randint(6, 9)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"{a} x {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b}."}
        else:
            a, b = random.randint(6, 9), random.randint(7, 9)
            pil, idx = _buat_pilihan(a * b, " apel")
            return {"tanya": f"Ayah membeli {a} keranjang apel. Setiap keranjang berisi {b} buah apel. Total apel Ayah adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b} apel."}

    elif slug == "pembagian-dasar":
        if level == "mudah":
            b, h = random.randint(2, 5), random.randint(3, 6)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        elif level == "sedang":
            b, h = random.randint(6, 9), random.randint(6, 9)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        else:
            b, h = random.randint(6, 8), random.randint(7, 9)
            pil, idx = _buat_pilihan(h, " kotak")
            return {"tanya": f"Sebanyak {b*h} kue akan dimasukkan ke dalam kotak, masing-masing berisi {b} kue. Banyak kotak yang dibutuhkan adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h} kotak."}

    elif slug == "operasi-hitung-campuran":
        if level == "mudah":
            a, b, c = random.randint(4, 12), random.randint(2, 4), random.randint(2, 5)
            pil, idx = _buat_pilihan(a + b * c)
            return {"tanya": f"{a} + {b} x {c} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"Kerjakan kali dulu: {b}x{c}={b*c}, lalu +{a} = {a+b*c}."}
        elif level == "sedang":
            a, b, c = random.randint(20, 40), random.randint(3, 6), random.randint(3, 5)
            pil, idx = _buat_pilihan(a - b * c)
            return {"tanya": f"{a} - {b} x {c} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"Kerjakan {b} x {c} = {b*c}, lalu {a} - {b*c} = {a - b*c}."}
        else:
            a, b, c = random.randint(3, 6), random.randint(2, 5), random.randint(3, 6)
            pil, idx = _buat_pilihan((a + b) * c)
            return {"tanya": f"({a} + {b}) x {c} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"Kerjakan dalam kurung dulu: ({a}+{b}) = {a+b}, lalu dikali {c} = {(a+b)*c}."}

    elif slug == "pecahan-sederhana":
        if level == "mudah":
            b = random.randint(3, 6); a = random.randint(1, b - 1)
            pil, idx = _buat_pilihan_teks(f"{a}/{b}", f"{b}/{a}", f"1/{b+1}")
            return {"tanya": f"Roti dipotong {b} bagian sama besar, dimakan {a} bagian. Nilainya ...", "pilihan": pil, "jawaban": idx, "bahas": f"Ditulis {a}/{b}."}
        elif level == "sedang":
            b = random.randint(5, 9); a = random.randint(1, b - 2)
            sisa = b - a
            pil, idx = _buat_pilihan_teks(f"{sisa}/{b}", f"{a}/{b}", f"{b}/{sisa}")
            return {"tanya": f"Pizza dipotong {b} bagian sama besar. Adik makan {a} potong. SISA pizza yang belum dimakan adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Sisa potongan = {b} - {a} = {sisa}, jadi pecahannya {sisa}/{b}."}
        else:
            b = random.randint(5, 9); a1, a2 = random.randint(2, b-1), random.randint(1, b-1)
            if a1 == a2: a1 += 1
            pil, idx = _buat_pilihan_teks(f"{max(a1,a2)}/{b}", f"{min(a1,a2)}/{b}", "Sama besar")
            return {"tanya": f"Manakah pecahan yang nilainya LEBIH BESAR antara {a1}/{b} dan {a2}/{b}?", "pilihan": pil, "jawaban": idx, "bahas": f"Karena penyebut sama ({b}), pembilang lebih besar nilainya lebih besar ({max(a1,a2)}/{b})."}

    elif slug == "satuan-waktu-lama":
        if level == "mudah":
            jam = random.randint(2, 5)
            pil, idx = _buat_pilihan(jam * 60, " menit")
            return {"tanya": f"{jam} jam = ... menit.", "pilihan": pil, "jawaban": idx, "bahas": f"{jam} x 60 = {jam*60} menit."}
        elif level == "sedang":
            jam, mnt = random.randint(1, 3), random.choice([15, 20, 30, 45])
            pil, idx = _buat_pilihan(jam * 60 + mnt, " menit")
            return {"tanya": f"{jam} jam {mnt} menit = ... menit.", "pilihan": pil, "jawaban": idx, "bahas": f"({jam} x 60) + {mnt} = {jam*60 + mnt} menit."}
        else:
            minggu, hari = random.randint(2, 4), random.randint(2, 6)
            pil, idx = _buat_pilihan(minggu * 7 + hari, " hari")
            return {"tanya": f"Liburan sekolah berlangsung selama {minggu} minggu lebih {hari} hari. Total liburan adalah ... hari.", "pilihan": pil, "jawaban": idx, "bahas": f"({minggu} x 7) + {hari} = {minggu*7 + hari} hari."}

    elif slug == "keliling-bangun-datar":
        if level == "mudah":
            s = random.randint(4, 12)
            pil, idx = _buat_pilihan(4 * s, " cm")
            return {"tanya": f"Keliling persegi dengan panjang sisi {s} cm adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"4 x {s} = {4*s} cm."}
        elif level == "sedang":
            p, l = random.randint(8, 15), random.randint(3, 7)
            pil, idx = _buat_pilihan(2 * (p + l), " cm")
            return {"tanya": f"Keliling persegi panjang (p={p} cm, l={l} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"2 x ({p}+{l}) = {2*(p+l)} cm."}
        else:
            s = random.randint(5, 11)
            pil, idx = _buat_pilihan(s, " meter")
            return {"tanya": f"Sebuah taman berbentuk persegi memiliki keliling {4*s} meter. Panjang setiap sisi taman adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Sisi = Keliling : 4 = {4*s} : 4 = {s} meter."}

    # ---- KELAS 4 ----
    elif slug == "fpb-dan-kpk":
        if level == "mudah":
            a, b, kpk, _ = random.choice([(3, 4, 12, 1), (4, 6, 12, 2), (5, 10, 10, 5)])
            pil, idx = _buat_pilihan(kpk)
            return {"tanya": f"KPK dari {a} dan {b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"KPK dari {a} dan {b} adalah {kpk}."}
        elif level == "sedang":
            a, b, _, fpb = random.choice([(12, 18, 36, 6), (16, 24, 48, 8), (15, 25, 75, 5)])
            pil, idx = _buat_pilihan(fpb)
            return {"tanya": f"FPB dari {a} dan {b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Pembagi terbesar yang sama dari {a} dan {b} adalah {fpb}."}
        else:
            a, b, kpk = random.choice([(4, 6, 12), (6, 8, 24), (8, 12, 24)])
            pil, idx = _buat_pilihan(kpk, " detik lagi")
            return {"tanya": f"Lampu A menyala setiap {a} detik, lampu B setiap {b} detik. Keduanya akan menyala bersama setiap ...", "pilihan": pil, "jawaban": idx, "bahas": f"Cari KPK dari {a} dan {b} = {kpk} detik."}

    elif slug == "pecahan-senilai":
        if level == "mudah":
            a, b, k = random.randint(1, 3), random.randint(4, 6), 2
            pil, idx = _buat_pilihan(a * k, f"/{b * k}")
            return {"tanya": f"Pecahan senilai dengan {a}/{b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Kalikan atas & bawah dengan 2: {a*2}/{b*2}."}
        elif level == "sedang":
            a, b, k = random.randint(1, 3), random.randint(4, 7), random.randint(3, 5)
            pil, idx = _buat_pilihan(a, f"/{b}")
            return {"tanya": f"Bentuk paling sederhana dari pecahan {a*k}/{b*k} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Bagi pembilang dan penyebut dengan {k} = {a}/{b}."}
        else:
            a, b, k = random.randint(2, 4), random.randint(5, 8), random.randint(3, 5)
            pil, idx = _buat_pilihan(a * k)
            return {"tanya": f"Jika {a}/{b} = .../{b*k}, angka yang tepat untuk mengisi titik-titik adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Penyebut dikali {k}, maka pembilang juga dikali {k}: {a} x {k} = {a*k}."}

    elif slug == "pembulatan-dan-penaksiran":
        if level == "mudah":
            pul = random.randint(2, 8); sat = random.randint(1, 9)
            angka = pul * 10 + sat
            hasil = (pul + 1) * 10 if sat >= 5 else pul * 10
            pil, idx = _buat_pilihan(hasil)
            return {"tanya": f"{angka} dibulatkan ke puluhan terdekat menjadi ...", "pilihan": pil, "jawaban": idx, "bahas": f"Satuannya {sat}, dibulatkan menjadi {hasil}."}
        elif level == "sedang":
            rat = random.randint(2, 7); pul = random.randint(15, 85)
            angka = rat * 100 + pul
            hasil = (rat + 1) * 100 if pul >= 50 else rat * 100
            pil, idx = _buat_pilihan(hasil)
            return {"tanya": f"{angka} dibulatkan ke ratusan terdekat menjadi ...", "pilihan": pil, "jawaban": idx, "bahas": f"Puluhannya {pul}, dibulatkan ke ratusan terdekat menjadi {hasil}."}
        else:
            pil, idx = _buat_pilihan(80)
            return {"tanya": "Taksirlah hasil penjumlahan 38 + 41 ke puluhan terdekat!", "pilihan": pil, "jawaban": idx, "bahas": "38 dibulatkan jadi 40, 41 dibulatkan jadi 40. 40 + 40 = 80."}

    elif slug == "luas-bangun-datar":
        if level == "mudah":
            p, l = random.randint(5, 10), random.randint(3, 7)
            pil, idx = _buat_pilihan(p * l, " cm²")
            return {"tanya": f"Luas persegi panjang (p={p} cm, l={l} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{p} x {l} = {p*l} cm²."}
        elif level == "sedang":
            a = random.choice([4, 6, 8, 10]); t = random.randint(3, 8)
            pil, idx = _buat_pilihan((a * t) // 2, " cm²")
            return {"tanya": f"Luas segitiga (alas={a} cm, tinggi={t} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"1/2 x {a} x {t} = {(a*t)//2} cm²."}
        else:
            s = random.randint(5, 11)
            pil, idx = _buat_pilihan(s, " cm")
            return {"tanya": f"Sebuah persegi memiliki luas {s*s} cm². Panjang sisi persegi tersebut adalah ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"Karena {s} x {s} = {s*s}, maka sisinya {s} cm."}

    elif slug == "mengenal-jenis-sudut":
        if level == "mudah":
            derajat = random.choice([40, 90, 130])
            jenis = "Sudut Siku-siku" if derajat == 90 else ("Sudut Lancip" if derajat < 90 else "Sudut Tumpul")
            pil, idx = _buat_pilihan_teks(jenis, "Sudut Lurus", "Sudut Lancip" if jenis != "Sudut Lancip" else "Sudut Tumpul")
            return {"tanya": f"Sudut {derajat}° termasuk jenis ...", "pilihan": pil, "jawaban": idx, "bahas": f"{jenis}."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(90, "°")
            return {"tanya": "Besar sudut yang dibentuk jarum jam pada pukul 03.00 tepat adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "Pukul 03.00 membentuk sudut siku-siku sebesar 90°."}
        else:
            pil, idx = _buat_pilihan(180, "°")
            return {"tanya": "Jumlah seluruh sudut pada bangun segitiga selalu sama dengan sudut lurus, yaitu ...", "pilihan": pil, "jawaban": idx, "bahas": "Jumlah sudut segitiga adalah 180°."}

    elif slug == "hubungan-antar-garis":
        if level == "mudah":
            pil, idx = _buat_pilihan_teks("Sejajar", "Berpotongan", "Berimpit")
            return {"tanya": "Dua rel kereta api yang berdampingan adalah contoh garis ...", "pilihan": pil, "jawaban": idx, "bahas": "Garis sejajar."}
        elif level == "sedang":
            pil, idx = _buat_pilihan_teks("Berpotongan tegak lurus", "Sejajar", "Berimpit")
            return {"tanya": "Tanda tambah (+) dibentuk oleh dua garis yang saling ...", "pilihan": pil, "jawaban": idx, "bahas": "Membentuk sudut 90° (berpotongan tegak lurus)."}
        else:
            pil, idx = _buat_pilihan_teks("Tidak akan pernah bertemu", "Bertemu di satu titik", "Membentuk sudut siku-siku")
            return {"tanya": "Jika dua garis sejajar diperpanjang terus-menerus tanpa batas, maka kedua garis tersebut ...", "pilihan": pil, "jawaban": idx, "bahas": "Garis sejajar jaraknya selalu tetap sehingga tidak akan pernah bertemu."}

    # ---- KELAS 5 ----
    elif slug == "operasi-pecahan-beda-penyebut":
        if level == "mudah":
            t_str, pemb, peny, bhs = random.choice([("1/2 + 1/4", 3, 4, "2/4 + 1/4 = 3/4"), ("2/3 - 1/3", 1, 3, "2/3 - 1/3 = 1/3")])
            pil, idx = _buat_pilihan(pemb, f"/{peny}")
            return {"tanya": f"Hasil dari {t_str} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": bhs}
        elif level == "sedang":
            t_str, pemb, peny, bhs = random.choice([("1/2 + 1/3", 5, 6, "3/6 + 2/6 = 5/6"), ("3/4 - 1/2", 1, 4, "3/4 - 2/4 = 1/4")])
            pil, idx = _buat_pilihan(pemb, f"/{peny}")
            return {"tanya": f"Hasil dari {t_str} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": bhs}
        else:
            pil, idx = _buat_pilihan_teks("7/8 kg", "2/6 kg", "5/8 kg")
            return {"tanya": "Ibu membeli 1/2 kg gula dan 3/8 kg tepung. Berat seluruh belanjaan Ibu adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "1/2 + 3/8 = 4/8 + 3/8 = 7/8 kg."}

    elif slug == "perkalian-pembagian-pecahan":
        if level == "mudah":
            pil, idx = _buat_pilihan_teks("2/5", "6/8", "3/5")
            return {"tanya": "Hasil dari 2/3 x 3/5 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "6/15 disederhanakan (:3) menjadi 2/5."}
        elif level == "sedang":
            pil, idx = _buat_pilihan_teks("3/2", "3/8", "2/3")
            return {"tanya": "Hasil dari 3/4 : 1/2 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "3/4 x 2/1 = 6/4 = 3/2."}
        else:
            pil, idx = _buat_pilihan(6, " potong")
            return {"tanya": "Pita sepanjang 3 meter akan dipotong-potong masing-masing 1/2 meter. Banyak potongan pita yang didapat adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "3 : 1/2 = 3 x 2/1 = 6 potong."}

    elif slug == "desimal-dan-persen":
        if level == "mudah":
            pec, persen = random.choice([("1/2", 50), ("1/4", 25), ("3/4", 75), ("1/5", 20)])
            pil, idx = _buat_pilihan(persen, "%")
            return {"tanya": f"Bentuk persen dari {pec} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{persen}%."}
        elif level == "sedang":
            persen, des = random.choice([(25, "0,25"), (50, "0,5"), (75, "0,75"), (40, "0,4")])
            pil, idx = _buat_pilihan_teks(des, "0,05", "2,5")
            return {"tanya": f"Bentuk desimal dari {persen}% adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{persen}/100 = {des}."}
        else:
            harga = random.choice([40000, 60000, 80000])
            potongan = int(harga * 0.25)
            pil, idx = _buat_pilihan(harga - potongan, " rupiah")
            return {"tanya": f"Harga baju Rp{harga} mendapat diskon 25%. Harga yang harus dibayar adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Diskon 25% = 1/4 x {harga} = Rp{potongan}. Bayar = {harga} - {potongan} = Rp{harga-potongan}."}

    elif slug == "kecepatan-jarak-waktu":
        if level == "mudah":
            k = random.choice([40, 50, 60]); w = random.randint(2, 4)
            pil, idx = _buat_pilihan(k * w, " km")
            return {"tanya": f"Kecepatan {k} km/jam selama {w} jam menempuh jarak ... km.", "pilihan": pil, "jawaban": idx, "bahas": f"{k} x {w} = {k*w} km."}
        elif level == "sedang":
            k = random.choice([50, 60, 70]); w = random.randint(2, 5)
            pil, idx = _buat_pilihan(k, " km/jam")
            return {"tanya": f"Bus menempuh jarak {k*w} km dalam waktu {w} jam. Kecepatan bus tersebut adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Kecepatan = Jarak : Waktu = {k*w} : {w} = {k} km/jam."}
        else:
            k = 60; w = random.randint(2, 4)
            pil, idx = _buat_pilihan(7 + w, ".00")
            return {"tanya": f"Ayah berangkat pukul 07.00 ke kota berjarak {k*w} km dengan kecepatan {k} km/jam. Ayah tiba pukul ...", "pilihan": pil, "jawaban": idx, "bahas": f"Waktu = {k*w} : {k} = {w} jam. Tiba = 07.00 + {w} jam = pukul {7+w:02d}.00."}

    elif slug == "skala-dan-denah":
        if level == "mudah":
            jp = random.randint(2, 6)
            pil, idx = _buat_pilihan(jp * 2, " km")
            return {"tanya": f"Skala 1 : 200.000, jarak peta {jp} cm. Jarak sebenarnya = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{jp} x 2 km = {jp*2} km."}
        elif level == "sedang":
            js = random.choice([6, 9, 12, 15])
            pil, idx = _buat_pilihan(js // 3, " cm")
            return {"tanya": f"Jarak dua kota {js} km. Jika skala peta 1 : 300.000, jarak pada peta adalah ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"{js} km = {js*100000} cm. Jarak peta = {js*100000} : 300.000 = {js//3} cm."}
        else:
            pil, idx = _buat_pilihan_teks("1 : 500.000", "1 : 50.000", "1 : 5.000.000")
            return {"tanya": "Jarak sebenarnya 15 km digambar pada peta sepanjang 3 cm. Skala peta tersebut adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "15 km = 1.500.000 cm. Skala = 3 : 1.500.000 = 1 : 500.000."}

    elif slug == "volume-kubus-dan-balok":
        if level == "mudah":
            s = random.randint(3, 6)
            pil, idx = _buat_pilihan(s * s * s, " cm³")
            return {"tanya": f"Volume kubus dengan panjang rusuk {s} cm adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{s} x {s} x {s} = {s**3} cm³."}
        elif level == "sedang":
            p, l, t = random.randint(5, 8), random.randint(3, 5), random.randint(2, 4)
            pil, idx = _buat_pilihan(p * l * t, " cm³")
            return {"tanya": f"Volume balok ({p} x {l} x {t} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{p*l*t} cm³."}
        else:
            p, l, t = 10, 5, random.randint(4, 8)
            vol = p * l * t
            pil, idx = _buat_pilihan(t, " cm")
            return {"tanya": f"Akuarium berbentuk balok berisi {vol} cm³ air. Jika panjangnya {p} cm dan lebarnya {l} cm, tinggi air adalah ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"Tinggi = Volume : (p x l) = {vol} : ({p} x {l}) = {vol} : {p*l} = {t} cm."}

    # ---- KELAS 6 ----
    elif slug == "operasi-bilangan-bulat":
        if level == "mudah":
            a, b = random.randint(-10, -2), random.randint(4, 15)
            pil, idx = _buat_pilihan(a + b, "", True)
            return {"tanya": f"({a}) + {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a+b}."}
        elif level == "sedang":
            a, b = random.randint(-8, -3), random.randint(-7, -2)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"({a}) x ({b}) = ...", "pilihan": pil, "jawaban": idx, "bahas": f"Negatif dikali negatif hasilnya positif: {a*b}."}
        else:
            suhu_awal, naik = random.randint(-6, -2), random.randint(8, 14)
            pil, idx = _buat_pilihan(suhu_awal + naik, "°C")
            return {"tanya": f"Suhu di dalam kulkas {suhu_awal}°C. Saat listrik padam, suhu naik {naik}°C. Suhu kulkas sekarang adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{suhu_awal} + {naik} = {suhu_awal + naik}°C."}

    elif slug == "hitung-campuran-pecahan-desimal":
        if level == "mudah":
            pil, idx = _buat_pilihan_teks("0,75", "0,50", "1,25")
            return {"tanya": "0,5 + 1/4 = ...", "pilihan": pil, "jawaban": idx, "bahas": "0,5 + 0,25 = 0,75."}
        elif level == "sedang":
            pil, idx = _buat_pilihan_teks("1,0", "0,8", "1,2")
            return {"tanya": "0,75 + 25% = ...", "pilihan": pil, "jawaban": idx, "bahas": "0,75 + 0,25 = 1,0."}
        else:
            pil, idx = _buat_pilihan_teks("0,5", "0,25", "1,5")
            return {"tanya": "1,25 - 1/2 - 25% = ...", "pilihan": pil, "jawaban": idx, "bahas": "1,25 - 0,50 - 0,25 = 0,50."}

    elif slug == "luas-keliling-lingkaran":
        if level == "mudah":
            r = random.choice([7, 14])
            pil, idx = _buat_pilihan((2 * 22 * r) // 7, " cm")
            return {"tanya": f"Keliling lingkaran dengan jari-jari {r} cm adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": f"2 x 22/7 x {r} = {(2*22*r)//7} cm."}
        elif level == "sedang":
            r = random.choice([7, 14])
            pil, idx = _buat_pilihan((22 * r * r) // 7, " cm²")
            return {"tanya": f"Luas lingkaran jari-jari {r} cm adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": f"22/7 x {r} x {r} = {(22*r*r)//7} cm²."}
        else:
            d = 14
            pil, idx = _buat_pilihan(154, " cm²")
            return {"tanya": f"Sebuah meja bundar memiliki DIAMETER {d} cm. Luas permukaan meja tersebut adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": f"Diameter {d} cm berarti jari-jari r = {d}:2 = 7 cm. Luas = 22/7 x 7 x 7 = 154 cm²."}

    elif slug == "bangun-ruang-gabungan":
        if level == "mudah":
            t = random.randint(4, 8)
            pil, idx = _buat_pilihan(154 * t, " cm³")
            return {"tanya": f"Volume tabung (luas alas 154 cm², tinggi {t} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"154 x {t} = {154*t} cm³."}
        elif level == "sedang":
            t = random.randint(6, 12)
            pil, idx = _buat_pilihan(154 * t, " cm³")
            return {"tanya": f"Volume tabung (r=7 cm, tinggi={t} cm) adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": f"(22/7 x 7 x 7) x {t} = 154 x {t} = {154*t} cm³."}
        else:
            t = 10
            pil, idx = _buat_pilihan(770, " cm³")
            return {"tanya": f"Kaleng susu berbentuk tabung (r=7 cm, tinggi={t} cm) terisi air SETENGAH bagian. Volume air di dalam kaleng adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Volume penuh = 154 x 10 = 1.540 cm³. Setengahnya = 1.540 : 2 = 770 cm³."}

    elif slug == "koordinat-kartesius":
        x, y = random.randint(2, 8), random.randint(2, 8)
        if level == "mudah":
            pil, idx = _buat_pilihan(x)
            return {"tanya": f"Titik P({x}, {y}), nilai sumbu x (absis) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Angka pertama adalah sumbu x = {x}."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(y)
            return {"tanya": f"Titik Q({x}, {y}), nilai sumbu y (ordinat) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Angka kedua adalah sumbu y = {y}."}
        else:
            geser = random.randint(2, 4)
            pil, idx = _buat_pilihan_teks(f"({x+geser}, {y})", f"({x}, {y+geser})", f"({x-geser}, {y})")
            return {"tanya": f"Titik A({x}, {y}) digeser ke KANAN sejauh {geser} satuan. Koordinat titik A sekarang adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Geser ke kanan menambah sumbu x: ({x}+{geser}, {y}) = ({x+geser}, {y})."}

    else:  # statistika-mean-median-modus
        if level == "mudah":
            pil, idx = _buat_pilihan(8)
            return {"tanya": "Modus (nilai yang paling sering muncul) dari data: 7, 8, 9, 8, 6, 8 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "Angka 8 muncul paling banyak (3 kali)."}
        elif level == "sedang":
            rata = random.randint(7, 12); s = random.randint(1, 3)
            d = [rata - s, rata, rata + s]; random.shuffle(d)
            pil, idx = _buat_pilihan(rata)
            return {"tanya": f"Mean (rata-rata) dari {d[0]}, {d[1]}, dan {d[2]} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"({d[0]}+{d[1]}+{d[2]}) : 3 = {rata}."}
        else:
            pil, idx = _buat_pilihan(8)
            return {"tanya": "Median (nilai tengah) dari data: 9, 6, 8, 10, 7 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "Urutkan dulu dari terkecil: 6, 7, 8, 9, 10. Nilai yang tepat di tengah adalah 8."}

def buat_soal_otomatis(kelas, slug=None, jumlah=6, level="mudah"):
    bab_kelas = [m["slug"] for m in MATERI if m["kelas"] == kelas]
    if slug:
        return [_generator_satu_soal(slug, level=level) for _ in range(jumlah)]
    else:
        urutan_level = ["mudah", "mudah", "sedang", "sedang", "sulit", "sulit"]
        return [_generator_satu_soal(bab_kelas[i % len(bab_kelas)], level=urutan_level[i % len(urutan_level)]) for i in range(jumlah)]

# ================= TUTOR AI PENJELAS SOAL =================
@app.route("/tanya-ai", methods=["POST"])
def tanya_ai():
    data = request.get_json(silent=True) or {}
    soal_teks = data.get("soal", "").strip()
    jawaban_murid = data.get("jawaban_murid", "").strip()
    jawaban_benar = data.get("jawaban_benar", "").strip()
    bahas_dasar = data.get("bahas", "").strip()

    if not soal_teks:
        return jsonify({"jawaban": "Tulis dulu soal matematika yang ingin ditanyakan ya!"})

    prompt = (
        f"Kamu adalah Asisten Tutor Matematika SD yang ramah dan sabar di Bimbel Matematika IFGA. "
        f"Jelaskan cara menyelesaikan soal berikut dengan bahasa sederhana yang mudah dipahami anak SD dalam 3-4 langkah singkat:\n"
        f"Soal: {soal_teks}\n"
        f"{f'Jawaban murid (salah): {jawaban_murid}' if jawaban_murid else ''}\n"
        f"{f'Jawaban yang benar: {jawaban_benar}' if jawaban_benar else ''}"
    )

    if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("ISI_"):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                hasil = json.loads(resp.read().decode("utf-8"))
                teks_ai = hasil["candidates"][0]["content"]["parts"][0]["text"]
                return jsonify({"jawaban": teks_ai})
        except Exception:
            pass

    penjelasan_cadangan = (
        f"Halo! Yuk kita bedah pelan-pelan soal: **{soal_teks}**\n\n"
        f"1️⃣ **Perhatikan angka & kata kuncinya** pada soal tersebut.\n"
        f"2️⃣ **Langkah penyelesaian:** {bahas_dasar or 'Kerjakan sesuai rumus pada ringkasan materi bab ini ya!'}\n"
        f"3️⃣ **Kesimpulan:** Jadi jawaban yang tepat adalah **{jawaban_benar or 'sesuai perhitungan di atas'}**. Tetap semangat berlatih!"
    )
    return jsonify({"jawaban": penjelasan_cadangan})

# ================= DUKUNGAN APLIKASI HP (PWA MANIFEST) =================
@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": NAMA_BIMBEL,
        "short_name": "Bimbel IFGA",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#e0f2fe",
        "theme_color": "#2563eb",
        "icons": [{
            "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='22' fill='%232563eb'/><text y='.9em' x='12' font-size='75'>🧮</text></svg>",
            "sizes": "192x192", "type": "image/svg+xml"
        }]
    })

# ================= TAMPILAN UTAMA =================
TAMPILAN_UTAMA = """<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#2563eb">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <link rel="manifest" href="/manifest.json">
  <title>{{ nama_bimbel }}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@600;700&family=Nunito:wght@600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-langit: #e0f2fe; --putih: #ffffff; --biru: #2563eb; --biru-tua: #1d4ed8;
      --kuning: #facc15; --oranye: #f97316; --hijau: #22c55e; --merah: #ef4444;
      --ungu: #8b5cf6; --teks: #1e293b; --abu: #64748b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; color: var(--teks); font-family: "Nunito", system-ui, sans-serif;
      font-size: 17px; line-height: 1.65;
      background-color: var(--bg-langit);
      background-image: radial-gradient(#bae6fd 2px, transparent 2px);
      background-size: 28px 28px;
    }
    h1, h2, h3, .logo, .pilih-kelas, .tombol-3d, .badge-tier { font-family: "Fredoka", "Nunito", sans-serif; }
    .atas {
      display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
      padding: 12px 24px; background: linear-gradient(135deg, #2563eb, #3b82f6);
      box-shadow: 0 4px 0 #1d4ed8; position: sticky; top: 0; z-index: 10;
    }
    .logo { color: #fff; font-size: 1.35rem; text-decoration: none; text-shadow: 0 2px 0 rgba(0,0,0,0.15); }
    .nav-kanan { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .pill-nav {
      padding: 7px 14px; border-radius: 999px; text-decoration: none; font-size: 0.9rem;
      font-family: "Fredoka", sans-serif; transition: transform 0.1s; display: inline-flex; align-items: center; gap: 6px;
    }
    .pill-nav:active { transform: translateY(3px); }
    .avatar-wrap {
      position: relative; display: inline-flex; align-items: center; justify-content: center;
      font-size: 1.8rem; background: #fff; border-radius: 50%; width: 48px; height: 48px; border: 2px solid #cbd5e1;
    }
    .avatar-topi { position: absolute; top: -16px; font-size: 1.3rem; filter: drop-shadow(0 2px 2px rgba(0,0,0,0.25)); }
    .tier-1 { border: 3px solid #eab308; box-shadow: 0 0 12px rgba(234, 179, 8, 0.7); background: #fefce8; }
    .tier-2 { border: 3px solid #a855f7; box-shadow: 0 0 10px rgba(168, 85, 247, 0.5); background: #faf5ff; }
    .tier-3 { border: 3px solid #3b82f6; box-shadow: 0 0 8px rgba(59, 130, 246, 0.4); background: #eff6ff; }
    .badge-tier { font-size: 0.72rem; padding: 2px 8px; border-radius: 999px; letter-spacing: 0.5px; }
    .wadah {
      max-width: 860px; margin: 28px auto; padding: 28px 32px;
      background: var(--putih); border-radius: 24px; border: 3px solid #bfdbfe;
      box-shadow: 0 10px 0 #bfdbfe;
    }
    h1 { color: var(--biru); font-size: 1.9rem; line-height: 1.2; margin: 0.2em 0 0.5em; }
    h2 { color: #0f172a; font-size: 1.35rem; margin-top: 1.5em; }
    h3 { color: #1d4ed8; font-size: 1.12rem; margin: 1.1em 0 0.3em; }
    a { color: var(--biru); font-weight: 700; }
    .grid-kelas { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 16px; margin-top: 16px; }
    .pilih-kelas {
      padding: 20px 14px; text-align: center; font-size: 1.3rem; border-radius: 20px;
      text-decoration: none; color: #fff; display: flex; flex-direction: column; align-items: center; gap: 6px;
      transition: transform 0.12s;
    }
    .pilih-kelas:hover { transform: translateY(-4px); }
    .k1 { background: #f43f5e; box-shadow: 0 6px 0 #be123c; }
    .k2 { background: #f97316; box-shadow: 0 6px 0 #c2410c; }
    .k3 { background: #eab308; box-shadow: 0 6px 0 #a16207; color: #1e293b; }
    .k4 { background: #22c55e; box-shadow: 0 6px 0 #15803d; }
    .k5 { background: #06b6d4; box-shadow: 0 6px 0 #0e7490; }
    .k6 { background: #8b5cf6; box-shadow: 0 6px 0 #5b21b6; }
    .daftar-materi {
      display: flex; justify-content: space-between; align-items: center; gap: 12px;
      padding: 14px 18px; margin: 10px 0; background: #f8fafc;
      border: 2px solid #cbd5e1; border-radius: 16px; text-decoration: none; color: var(--teks);
      box-shadow: 0 4px 0 #cbd5e1;
    }
    .daftar-materi:hover { background: #eff6ff; border-color: var(--biru); box-shadow: 0 4px 0 var(--biru); }
    .badge-nilai { background: #fef08a; border: 2px solid #eab308; padding: 3px 12px; border-radius: 999px; font-size: 0.85rem; font-weight: 800; }
    .progress-track { width: 100%; height: 14px; background: #e2e8f0; border-radius: 999px; overflow: hidden; margin-top: 6px; }
    .progress-fill { height: 100%; background: linear-gradient(90deg, #22c55e, #3b82f6); border-radius: 999px; transition: width 0.4s; }
    .contoh { background: #ecfdf5; border: 2px dashed #10b981; color: #065f46; display: inline-block; padding: 8px 18px; border-radius: 12px; font-weight: 800; margin: 6px 0; }
    .tombol-3d { display: inline-block; background: var(--biru); color: #fff; padding: 12px 24px; border: none; border-radius: 16px; font-size: 1.05rem; text-decoration: none; cursor: pointer; box-shadow: 0 5px 0 var(--biru-tua); }
    .tombol-3d:active { transform: translateY(4px); box-shadow: none; }
    .tombol-hijau { background: var(--hijau); box-shadow: 0 5px 0 #15803d; }
    .tombol-kuning { background: #eab308; color: #1e293b; box-shadow: 0 5px 0 #a16207; }
    .tombol-merah { background: var(--merah); box-shadow: 0 5px 0 #b91c1c; }
    .nilai-box { background: linear-gradient(135deg, #fef9c3, #fef08a); padding: 18px 22px; border-radius: 18px; margin: 18px 0; border: 3px solid #eab308; text-align: center; }
    .soal { background: #f8fafc; border: 3px solid #e2e8f0; border-radius: 18px; padding: 18px 22px; margin: 18px 0; }
    .soal legend { font-family: "Fredoka", sans-serif; color: #fff; background: var(--biru); padding: 4px 14px; border-radius: 999px; }
    .soal.benar { border-color: var(--hijau); background: #f0fdf4; }
    .soal.salah { border-color: var(--merah); background: #fef2f2; }
    .opsi { display: flex; align-items: center; gap: 10px; padding: 10px 14px; margin: 8px 0; background: #fff; border: 2px solid #cbd5e1; border-radius: 12px; cursor: pointer; font-weight: 700; }
    .bahas { margin-top: 12px; padding: 12px; background: #fff; border-radius: 12px; border-left: 5px solid var(--biru); font-size: 0.95rem; }
    .kotak-ai { margin-top: 10px; padding: 14px; background: #eff6ff; border: 2px solid #93c5fd; border-radius: 12px; font-size: 0.95rem; white-space: pre-line; display: none; }
    .input-box { width: 100%; padding: 12px 14px; border: 2px solid #cbd5e1; border-radius: 12px; font: inherit; margin: 6px 0 14px; }
    .tabel-lb { width: 100%; border-collapse: collapse; margin-top: 16px; }
    .tabel-lb th, .tabel-lb td { padding: 12px 10px; text-align: left; border-bottom: 2px solid #e2e8f0; }
    .stat-card { background: #f8fafc; border: 2px solid #cbd5e1; border-radius: 16px; padding: 14px; text-align: center; }
    footer { text-align: center; padding: 24px; color: var(--abu); font-size: 0.9rem; font-weight: 700; }
  </style>
</head>
<body>
  <header class="atas">
    <a class="logo" href="/">🧮 {{ nama_bimbel }}</a>
    <div class="nav-kanan">
      {% if user %}
        <a class="pill-nav" style="background:#facc15; color:#1e293b; box-shadow:0 3px 0 #ca8a04;" href="/leaderboard">🏆 Leaderboard</a>
        <a class="pill-nav" style="background:#a855f7; color:#fff; box-shadow:0 3px 0 #7e22ce;" href="/minigame">🎮 Mini-Game</a>
        <a class="pill-nav" style="background:#fff; color:#1e293b; border:2px solid #93c5fd;" href="/profil">
          <span>{{ user.hadiah.ikon if user.hadiah else '' }}{{ user.avatar }} <strong>{{ user.nama }}</strong> • 🔥{{ user.streak }}h • {{ user.poin }} pts</span>
        </a>
      {% else %}
        <a class="pill-nav" style="background:#22c55e; color:#fff; box-shadow:0 3px 0 #15803d;" href="/login">🔑 Masuk / Daftar Murid</a>
      {% endif %}
    </div>
  </header>
  <main class="wadah">{{ konten|safe }}</main>
  <footer>
    ✨ {{ nama_bimbel }} (Khusus Murid Terdaftar) — <a href="/guru" style="color:#64748b; font-size:0.85rem;">Ruang Ibu Guru</a> ✨
  </footer>

  <script>
    function bunyiEfek(jenis) {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        if (jenis === 'benar') {
          osc.type = 'sine'; osc.frequency.setValueAtTime(587.33, ctx.currentTime);
          osc.frequency.setValueAtTime(880, ctx.currentTime + 0.1);
          gain.gain.setValueAtTime(0.15, ctx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
          osc.start(); osc.stop(ctx.currentTime + 0.3);
        } else {
          osc.type = 'triangle'; osc.frequency.setValueAtTime(220, ctx.currentTime);
          osc.frequency.setValueAtTime(160, ctx.currentTime + 0.12);
          gain.gain.setValueAtTime(0.15, ctx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
          osc.start(); osc.stop(ctx.currentTime + 0.3);
        }
      } catch(e) {}
    }
  </script>
</body>
</html>"""

def render_halaman(konten_html, **kwargs):
    user = get_user_aktif()
    isi_terender = render_template_string(konten_html, user=user, whatsapp=WHATSAPP, **kwargs)
    return render_template_string(TAMPILAN_UTAMA, nama_bimbel=NAMA_BIMBEL, whatsapp=WHATSAPP, user=user, konten=isi_terender)

# ================= WAJIB LOGIN & WAJIB DISETUJUI GURU =================
@app.before_request
def wajib_login():
    halaman_bebas = ("login", "guru", "manifest", "static")
    if request.endpoint in halaman_bebas:
        return
    uid = session.get("user_id")
    if not uid:
        return redirect(url_for("login"))
    with get_db() as db:
        u = db.execute("SELECT status FROM users WHERE id = ?", (uid,)).fetchone()
    if not u or u["status"] != "aktif":
        session.pop("user_id", None)
        return redirect(url_for("login"))

# ================= RUTE LOGIN, DAFTAR, & PROFIL =================
@app.route("/login", methods=["GET", "POST"])
def login():
    pesan_err = None
    pesan_sukses = None
    if request.method == "POST":
        aksi = request.form.get("aksi")
        nama = request.form.get("nama", "").strip()
        pin = request.form.get("pin", "").strip()
        avatar = request.form.get("avatar", "🐱")

        if not nama or len(pin) != 4 or not pin.isdigit():
            pesan_err = "Nama wajib diisi dan PIN harus berupa 4 angka (contoh: 1234)."
        else:
            with get_db() as db:
                if aksi == "daftar":
                    cek = db.execute("SELECT id FROM users WHERE LOWER(nama) = LOWER(?)", (nama,)).fetchone()
                    if cek:
                        pesan_err = "Nama itu sudah terdaftar. Jika itu akunmu, silakan login di kotak sebelah kiri."
                    else:
                        db.execute("""
                            INSERT INTO users (nama, pin, avatar, poin, soal_benar, soal_salah, status)
                            VALUES (?, ?, ?, 0, 0, 0, 'pending')
                        """, (nama, pin, avatar))
                        pesan_sukses = f"Pendaftaran atas nama '{nama}' berhasil dikirim! Minta Ibu Guru menyetujui akunmu di Ruang Guru, setelah itu kamu baru bisa masuk."
                else:
                    row = db.execute("SELECT id, status FROM users WHERE LOWER(nama) = LOWER(?) AND pin = ?", (nama, pin)).fetchone()
                    if not row:
                        pesan_err = "Nama atau PIN 4 angka salah. Coba cek lagi ya!"
                    elif row["status"] != "aktif":
                        pesan_err = "Akunmu masih MENUNGGU VERIFIKASI dari Ibu Guru. Silakan beri tahu Ibu Guru agar akunmu segera diaktifkan!"
                    else:
                        session.permanent = True
                        session["user_id"] = row["id"]
                        return redirect(url_for("beranda"))

    html = """
    <h1>🔒 Portal Eksklusif Murid Bimbel</h1>
    <p>Aplikasi belajar khusus murid terdaftar di <strong>{{ nama_bimbel }}</strong>. Sekali masuk, akunmu otomatis tersimpan di HP/laptop ini.</p>

    {% if pesan_sukses %}
      <div style="background:#dcfce7; color:#166534; padding:16px; border-radius:14px; border:2px solid #22c55e; font-weight:800; margin-bottom:18px;">
        🎉 {{ pesan_sukses }}<br><br>
        <a class="tombol-3d tombol-hijau" style="padding:8px 16px; font-size:0.95rem;" href="https://wa.me/{{ whatsapp }}?text=Halo%20Bu,%20saya%20sudah%20daftar%20akun%20di%20aplikasi%20Bimbel%20Matematika.%20Mohon%20diverifikasi%20ya!" target="_blank">💬 Konfirmasi ke WA Ibu Guru</a>
      </div>
    {% endif %}
    {% if pesan_err %}
      <div style="background:#fee2e2; color:#991b1b; padding:14px 16px; border-radius:12px; border:2px solid #ef4444; font-weight:800; margin-bottom:16px;">⚠️ {{ pesan_err }}</div>
    {% endif %}

    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px;">
      <form method="post" style="background:#f8fafc; padding:20px; border-radius:18px; border:2px solid #cbd5e1;">
        <h2 style="margin-top:0;">👋 Masuk (Akun Terverifikasi)</h2>
        <input type="hidden" name="aksi" value="masuk">
        <label><strong>Nama Lengkap / Panggilan:</strong></label>
        <input class="input-box" type="text" name="nama" placeholder="Contoh: Budi Santoso" required>
        <label><strong>PIN Rahasia (4 Angka):</strong></label>
        <input class="input-box" type="password" name="pin" maxlength="4" pattern="[0-9]{4}" placeholder="****" required>
        <button class="tombol-3d" type="submit">Masuk &amp; Simpan Akun</button>
        <p style="font-size:0.85rem; color:#64748b; margin-top:12px;">
          Lupa PIN? <a href="https://wa.me/{{ whatsapp }}?text=Halo%20Bu,%20saya%20lupa%20PIN%20akun%20Bimbel%20Matematika" target="_blank">Minta Ibu Guru cek/reset PIN</a>.
        </p>
      </form>

      <form method="post" style="background:#eff6ff; padding:20px; border-radius:18px; border:2px solid #93c5fd;">
        <h2 style="margin-top:0;">📝 Daftar Murid Baru</h2>
        <input type="hidden" name="aksi" value="daftar">
        <label><strong>Nama Lengkap Murid:</strong></label>
        <input class="input-box" type="text" name="nama" placeholder="Tulis nama aslimu agar dikenali Ibu Guru" required>
        <label><strong>Buat PIN 4 Angka:</strong></label>
        <input class="input-box" type="text" name="pin" maxlength="4" pattern="[0-9]{4}" placeholder="Contoh: 1234" required>
        <label><strong>Pilih Karakter Avatar:</strong></label>
        <div style="display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 16px; font-size:1.6rem;">
          {% for av in ['🐱', '🐶', '🐼', '🦊', '🦁', '🐰', '🐯', '🐨', '🐸', '🦄'] %}
            <label style="cursor:pointer;">
              <input type="radio" name="avatar" value="{{ av }}" {% if loop.first %}checked{% endif %}> {{ av }}
            </label>
          {% endfor %}
        </div>
        <button class="tombol-3d tombol-hijau" type="submit">Kirim Pendaftaran</button>
      </form>
    </div>"""
    return render_halaman(html, nama_bimbel=NAMA_BIMBEL, pesan_err=pesan_err, pesan_sukses=pesan_sukses)

@app.route("/profil", methods=["GET", "POST"])
def profil():
    user = get_user_aktif()
    if not user:
        return redirect(url_for("login"))

    pesan_profil = None
    err_profil = None

    if request.method == "POST":
        aksi = request.form.get("aksi")
        if aksi == "ganti_avatar":
            avatar_baru = request.form.get("avatar_baru", "🐱")
            with get_db() as db:
                db.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_baru, user["id"]))
            pesan_profil = "Karakter avatar berhasil diganti!"
            user = get_user_aktif()
        elif aksi == "ganti_pin":
            pin_lama = request.form.get("pin_lama", "").strip()
            pin_baru = request.form.get("pin_baru", "").strip()
            with get_db() as db:
                cek = db.execute("SELECT pin FROM users WHERE id = ?", (user["id"],)).fetchone()
                if not cek or cek["pin"] != pin_lama:
                    err_profil = "PIN lama tidak sesuai!"
                elif len(pin_baru) != 4 or not pin_baru.isdigit():
                    err_profil = "PIN baru harus berupa 4 angka!"
                else:
                    db.execute("UPDATE users SET pin = ? WHERE id = ?", (pin_baru, user["id"]))
                    pesan_profil = "PIN rahasia berhasil diperbarui!"

    with get_db() as db:
        rows = db.execute("SELECT kode_bab, nilai FROM nilai_bab WHERE user_id = ?", (user["id"],)).fetchall()
        riwayat = {r["kode_bab"]: r["nilai"] for r in rows}

    progress_kelas = []
    total_bab_selesai = 0
    for k in range(1, 7):
        bab_k = [m for m in MATERI if m["kelas"] == k]
        selesai = sum(1 for m in bab_k if f"{k}_{m['slug']}" in riwayat)
        total_bab_selesai += selesai
        persen = round((selesai / len(bab_k)) * 100)
        nilai_tryout = riwayat.get(f"{k}_tryout")
        progress_kelas.append({"kelas": k, "selesai": selesai, "total": len(bab_k), "persen": persen, "tryout": nilai_tryout})

    daftar_avatar = ['🐱', '🐶', '🐼', '🦊', '🦁', '🐰', '🐯', '🐨', '🐸', '🦄']

    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    {% if pesan_profil %}<div style="background:#dcfce7; color:#166534; padding:12px 16px; border-radius:12px; font-weight:800; margin-bottom:14px;">✅ {{ pesan_profil }}</div>{% endif %}
    {% if err_profil %}<div style="background:#fee2e2; color:#991b1b; padding:12px 16px; border-radius:12px; font-weight:800; margin-bottom:14px;">⚠️ {{ err_profil }}</div>{% endif %}

    <div style="text-align:center; padding:22px; background:#f8fafc; border-radius:22px; border:2px solid #cbd5e1;">
      <div class="avatar-wrap {% if user.rank <= 3 %}tier-{{ user.rank }}{% endif %}" style="width:94px; height:94px; font-size:3.6rem; margin:0 auto;">
        {% if user.hadiah %}<span class="avatar-topi" style="top:-28px; font-size:2.4rem;">{{ user.hadiah.ikon }}</span>{% endif %}
        <span>{{ user.avatar }}</span>
      </div>
      <h1 style="margin:14px 0 4px;">{{ user.nama }}</h1>
      <p style="margin:0; font-size:1.1rem; color:#475569;">
        Juara <strong>#{{ user.rank }}</strong> &nbsp;|&nbsp;
        Skor: <strong style="color:#2563eb;">{{ user.poin }} pts</strong> &nbsp;|&nbsp;
        Api Semangat: <strong style="color:#ea580c;">🔥 {{ user.streak }} Hari</strong>
      </p>
      {% if user.hadiah %}
        <div style="margin-top:12px; background:{{ user.hadiah.bg }}; border:{{ user.hadiah.border }}; display:inline-block; padding:8px 18px; border-radius:999px; font-weight:800;">
          <span class="badge-tier" style="background:{{ user.hadiah.warna }}; color:#fff;">{{ user.hadiah.tier }}</span>
          &nbsp;{{ user.hadiah.ikon }} {{ user.hadiah.nama }}
        </div>
      {% endif %}
    </div>

    <h2>📊 Statistik Pengerjaan Soal</h2>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px;">
      <div class="stat-card">
        <div style="font-size:1.6rem; font-weight:800; color:#2563eb;">{{ user.total_soal }}</div>
        <div style="font-size:0.9rem; color:#64748b; font-weight:700;">Total Soal</div>
      </div>
      <div class="stat-card" style="background:#f0fdf4; border-color:#86efac;">
        <div style="font-size:1.6rem; font-weight:800; color:#16a34a;">✅ {{ user.benar }}</div>
        <div style="font-size:0.9rem; color:#15803d; font-weight:700;">Benar</div>
      </div>
      <div class="stat-card" style="background:#fef2f2; border-color:#fca5a5;">
        <div style="font-size:1.6rem; font-weight:800; color:#dc2626;">❌ {{ user.salah }}</div>
        <div style="font-size:0.9rem; color:#b91c1c; font-weight:700;">Salah</div>
      </div>
      <div class="stat-card" style="background:#fefce8; border-color:#fde047;">
        <div style="font-size:1.6rem; font-weight:800; color:#ca8a04;">🎯 {{ user.akurasi }}%</div>
        <div style="font-size:0.9rem; color:#854d0e; font-weight:700;">Ketelitian</div>
      </div>
    </div>

    <h2>📈 Perkembangan Belajar ({{ total_bab_selesai }} / 36 Bab Selesai)</h2>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:14px;">
      {% for pk in progress_kelas %}
        <div style="background:#fff; border:2px solid #e2e8f0; border-radius:16px; padding:14px 16px;">
          <div style="display:flex; justify-content:space-between; font-weight:800;">
            <a href="/kelas/{{ pk.kelas }}" style="text-decoration:none;">📘 Kelas {{ pk.kelas }}</a>
            <span>{{ pk.selesai }}/{{ pk.total }} Bab ({{ pk.persen }}%)</span>
          </div>
          <div class="progress-track"><div class="progress-fill" style="width:{{ pk.persen }}%;"></div></div>
          <div style="font-size:0.85rem; color:#64748b; margin-top:8px;">
            Tryout Kelas {{ pk.kelas }}:
            <strong>{{ ('Nilai ' ~ pk.tryout) if pk.tryout is not none else 'Belum dicoba' }}</strong>
          </div>
        </div>
      {% endfor %}
    </div>

    <h2>⚙️ Pengaturan Akun Saya</h2>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:16px;">
      <form method="post" style="background:#f8fafc; padding:18px; border-radius:18px; border:2px solid #cbd5e1;">
        <h3 style="margin-top:0;">🎨 Ganti Karakter Avatar</h3>
        <input type="hidden" name="aksi" value="ganti_avatar">
        <div style="display:flex; gap:10px; flex-wrap:wrap; font-size:1.6rem; margin-bottom:14px;">
          {% for av in daftar_avatar %}
            <label style="cursor:pointer;">
              <input type="radio" name="avatar_baru" value="{{ av }}" {% if user.avatar == av %}checked{% endif %}> {{ av }}
            </label>
          {% endfor %}
        </div>
        <button class="tombol-3d" style="padding:8px 18px; font-size:0.95rem;" type="submit">Simpan Avatar</button>
      </form>

      <form method="post" style="background:#f8fafc; padding:18px; border-radius:18px; border:2px solid #cbd5e1;">
        <h3 style="margin-top:0;">🔒 Ubah PIN Rahasia</h3>
        <input type="hidden" name="aksi" value="ganti_pin">
        <input class="input-box" type="password" name="pin_lama" maxlength="4" pattern="[0-9]{4}" placeholder="PIN Lama (4 angka)" required style="margin-bottom:8px;">
        <input class="input-box" type="text" name="pin_baru" maxlength="4" pattern="[0-9]{4}" placeholder="PIN Baru (4 angka)" required style="margin-bottom:10px;">
        <button class="tombol-3d tombol-hijau" style="padding:8px 18px; font-size:0.95rem;" type="submit">Simpan PIN Baru</button>
      </form>
    </div>

    <div style="margin-top:26px; text-align:right;">
      <a class="tombol-3d tombol-merah" style="font-size:0.95rem;" href="/logout">🚪 Keluar dari Akun</a>
    </div>"""
    return render_halaman(html, progress_kelas=progress_kelas, total_bab_selesai=total_bab_selesai,
                          daftar_avatar=daftar_avatar, pesan_profil=pesan_profil, err_profil=err_profil)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))

# ================= LEADERBOARD LENGKAP =================
@app.route("/leaderboard")
def leaderboard():
    lb = ambil_leaderboard()
    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    <h1>🏆 Papan Peringkat &amp; Hadiah Juara</h1>
    <p>Poin per soal benar: <strong>Mudah (+10 pts)</strong>, <strong>Sedang (+15 pts)</strong>, <strong>Sulit (+20 pts)</strong>, ditambah bonus <em>Streak</em> harian (+15 pts).</p>

    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(145px, 1fr)); gap:10px; margin:16px 0;">
      {% for r, h in hadiah_list.items() %}
        <div style="background:{{ h.bg }}; border:{{ h.border }}; border-radius:14px; padding:10px; text-align:center;">
          <span class="badge-tier" style="background:{{ h.warna }}; color:#fff;">#{{ r }} {{ h.tier }}</span>
          <div style="font-size:1.8rem; margin:4px 0;">{{ h.ikon }}</div>
          <strong style="font-size:0.85rem;">{{ h.nama }}</strong>
        </div>
      {% endfor %}
    </div>

    <div style="overflow-x:auto;">
      <table class="tabel-lb">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Murid &amp; Avatar</th>
            <th>Item Juara</th>
            <th>Streak &amp; Akurasi</th>
            <th>Skor</th>
          </tr>
        </thead>
        <tbody>
          {% for u in lb %}
            <tr style="background:{{ u.hadiah.bg if u.hadiah else '#fff' }};">
              <td><strong>#{{ u.rank }}</strong></td>
              <td style="display:flex; align-items:center; gap:12px;">
                <div class="avatar-wrap {% if u.rank <= 3 %}tier-{{ u.rank }}{% endif %}">
                  {% if u.hadiah %}<span class="avatar-topi">{{ u.hadiah.ikon }}</span>{% endif %}
                  <span>{{ u.avatar }}</span>
                </div>
                <div>
                  <strong>{{ u.nama }}</strong>
                  {% if user and user.id == u.id %}<span style="font-size:0.75rem; background:#2563eb; color:#fff; padding:1px 6px; border-radius:6px;">Kamu</span>{% endif %}
                </div>
              </td>
              <td>
                {% if u.hadiah %}
                  <span class="badge-tier" style="background:{{ u.hadiah.warna }}; color:#fff;">{{ u.hadiah.tier }}</span>
                  <strong>{{ u.hadiah.ikon }} {{ u.hadiah.nama }}</strong>
                {% else %}
                  <span style="color:#94a3b8; font-size:0.85rem;">Peserta Aktif</span>
                {% endif %}
              </td>
              <td style="font-size:0.9rem;">
                <span style="color:#ea580c; font-weight:800;">🔥 {{ u.streak }} hari</span><br>
                <span style="color:#16a34a;">✅{{ u.benar }}</span> / <span style="color:#dc2626;">❌{{ u.salah }}</span>
              </td>
              <td><strong style="color:#2563eb; font-size:1.15rem;">{{ u.poin }}</strong></td>
            </tr>
          {% else %}
            <tr><td colspan="5" style="text-align:center; color:#64748b;">Belum ada murid yang terdaftar.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>"""
    return render_halaman(html, lb=lb, hadiah_list=HADIAH_PERINGKAT)

# ================= BERANDA =================
@app.route("/")
def beranda():
    user = get_user_aktif()
    with get_db() as db:
        daftar_pr = db.execute("SELECT * FROM tugas_pr ORDER BY id DESC").fetchall()
        selesai_rows = db.execute("SELECT kode_bab FROM nilai_bab WHERE user_id = ?", (user["id"],)).fetchall()
        sudah_selesai = {r["kode_bab"] for r in selesai_rows}

    ikon_kelas = {
        1: ("🐣", "Berhitung & Jam"), 2: ("🚀", "Perkalian & Uang"), 3: ("🦁", "Campuran & Keliling"),
        4: ("🦉", "KPK/FPB & Luas"), 5: ("🐬", "Pecahan & Volume"), 6: ("🏆", "Bulat & Lingkaran")
    }
    html = """
    <h1>Halo, {{ user.nama }}! Ayo Belajar Matematika! 🌟</h1>
    <p>Api Semangatmu: <strong style="color:#ea580c;">🔥 {{ user.streak }} Hari Berturut-turut</strong> (kerjakan minimal 1 latihan hari ini untuk bonus <strong>+15 poin</strong>!).</p>

    {% if daftar_pr %}
      <div style="background:#fefce8; border:3px solid #eab308; border-radius:18px; padding:16px 20px; margin:16px 0;">
        <h3 style="margin-top:0; color:#854d0e;">📋 Tugas / PR dari Ibu Guru:</h3>
        {% for pr in daftar_pr %}
          {% set kode = pr.kelas ~ '_' ~ pr.slug %}
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; padding:8px 0; border-bottom:1px dashed #fde047;">
            <div>
              <strong>Kelas {{ pr.kelas }} — {{ pr.judul_bab }}</strong>
              {% if pr.catatan %}<div style="font-size:0.88rem; color:#713f12;">Catatan Ibu: "{{ pr.catatan }}"</div>{% endif %}
            </div>
            {% if kode in sudah_selesai %}
              <span style="background:#22c55e; color:#fff; padding:4px 12px; border-radius:999px; font-size:0.85rem; font-weight:800;">✅ Sudah Selesai</span>
            {% else %}
              <a class="tombol-3d" style="padding:6px 14px; font-size:0.88rem;" href="/kelas/{{ pr.kelas }}/{{ pr.slug }}">Kerjakan PR &rarr;</a>
            {% endif %}
          </div>
        {% endfor %}
      </div>
    {% endif %}

    <div class="grid-kelas">
      {% for k in range(1, 7) %}
        <a class="pilih-kelas k{{ k }}" href="/kelas/{{ k }}">
          <span style="font-size:2.1rem;">{{ ikon_kelas[k][0] }}</span>
          <span>Kelas {{ k }}</span>
          <small style="font-family:'Nunito'; font-size:0.85rem;">{{ ikon_kelas[k][1] }}</small>
        </a>
      {% endfor %}
    </div>"""
    return render_halaman(html, ikon_kelas=ikon_kelas, daftar_pr=daftar_pr, sudah_selesai=sudah_selesai)

@app.route("/kelas/<int:kelas>")
def halaman_kelas(kelas):
    if kelas not in range(1, 7): abort(404)
    materi = [m for m in MATERI if m["kelas"] == kelas]
    riwayat = {}
    user = get_user_aktif()
    if user:
        with get_db() as db:
            rows = db.execute("SELECT kode_bab, nilai FROM nilai_bab WHERE user_id = ?", (user["id"],)).fetchall()
            riwayat = {r["kode_bab"]: r["nilai"] for r in rows}

    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    <h1>📘 Matematika Kelas {{ kelas }}</h1>
    <h2>Daftar Materi &amp; Latihan Per Bab</h2>
    {% for m in materi %}
      {% set skor_bab = riwayat.get(kelas ~ '_' ~ m.slug) %}
      <a class="daftar-materi" href="/kelas/{{ kelas }}/{{ m.slug }}">
        <span>{{ m.judul }}</span>
        {% if skor_bab is not none %}
          <span class="badge-nilai">{% if skor_bab == 100 %}⭐⭐⭐{% elif skor_bab >= 70 %}⭐⭐{% else %}⭐{% endif %} {{ skor_bab }}</span>
        {% else %}
          <span style="color:#94a3b8; font-size:0.85rem;">Pelajari &rarr;</span>
        {% endif %}
      </a>
    {% endfor %}

    <h2>⏱️ Tryout Waktu Kelas {{ kelas }} (10 Menit)</h2>
    <p>Berisi 6 soal campuran bertingkat (2 Mudah, 2 Sedang, 2 Sulit) yang harus diselesaikan dalam 10 menit!</p>
    <a class="tombol-3d tombol-hijau" href="/kelas/{{ kelas }}/latihan">⏱️ Mulai Tryout Waktu Kelas {{ kelas }}</a>"""
    return render_halaman(html, kelas=kelas, materi=materi, riwayat=riwayat)

@app.route("/kelas/<int:kelas>/<slug>")
def halaman_materi(kelas, slug):
    m = next((x for x in MATERI if x["kelas"] == kelas and x["slug"] == slug), None)
    if not m: abort(404)
    html = """
    <p><a href="/kelas/{{ m.kelas }}">&larr; Kembali ke Kelas {{ m.kelas }}</a></p>
    <h1>{{ m.judul }}</h1>
    <div style="background:#f8fafc; padding:20px 24px; border-radius:18px; border:2px solid #cbd5e1;">{{ m.isi|safe }}</div>
    <hr style="margin:24px 0; border:0; border-top:3px dashed #cbd5e1;">

    <h2>🎯 Pilih Tingkat Kesulitan Latihan:</h2>
    <p style="margin-top:0; color:#475569;">Mulailah dari level <strong>Mudah</strong> untuk pemanasan, lalu naik ke <strong>Sedang</strong> dan <strong>Sulit</strong> untuk tantangan soal cerita &amp; poin lebih besar!</p>
    <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:12px;">
      <a class="tombol-3d tombol-hijau" href="/kelas/{{ m.kelas }}/{{ m.slug }}/latihan?level=mudah">🟢 Mudah (+10 pts/soal)</a>
      <a class="tombol-3d tombol-kuning" href="/kelas/{{ m.kelas }}/{{ m.slug }}/latihan?level=sedang">🟡 Sedang (+15 pts/soal)</a>
      <a class="tombol-3d tombol-merah" href="/kelas/{{ m.kelas }}/{{ m.slug }}/latihan?level=sulit">🔴 Sulit / Tantangan (+20 pts/soal)</a>
    </div>"""
    return render_halaman(html, m=m)

@app.route("/kelas/<int:kelas>/latihan", defaults={"slug": None}, methods=["GET", "POST"])
@app.route("/kelas/<int:kelas>/<slug>/latihan", methods=["GET", "POST"])
def halaman_latihan(kelas, slug):
    if kelas not in range(1, 7): abort(404)
    is_tryout = (slug is None)
    level = request.args.get("level", "mudah")
    if level not in ("mudah", "sedang", "sulit"):
        level = "mudah"

    label_level = {"mudah": "🟢 Level Mudah", "sedang": "🟡 Level Sedang", "sulit": "🔴 Level Sulit"}[level]
    judul_latihan = (
        f"⏱️ Tryout Waktu Kelas {kelas} (Campuran)"
        if is_tryout
        else f"✏️ Latihan {next(m['judul'] for m in MATERI if m['kelas']==kelas and m['slug']==slug)} ({label_level})"
    )

    kunci_sesi = f"soal_{kelas}_{slug or 'tryout'}_{level}"
    if request.method == "GET" or kunci_sesi not in session:
        soal = buat_soal_otomatis(kelas, slug=slug, jumlah=6, level=level)
        session[kunci_sesi] = soal
        session[f"sudah_kumpul_{kunci_sesi}"] = False
        hasil = skor = salah_count = nilai = pesan = bintang = None
    else:
        soal = session[kunci_sesi]
        hasil = []
        for i, s in enumerate(soal):
            pilih = request.form.get(f"soal{i}", "")
            pilih = int(pilih) if pilih.isdigit() else None
            hasil.append({"dipilih": pilih, "benar": pilih == s["jawaban"]})
        skor = sum(h["benar"] for h in hasil)
        salah_count = len(soal) - skor
        nilai = round(skor / len(soal) * 100)
        sisa_detik = max(0, min(600, int(request.form.get("sisa_detik", 0) or 0)))

        user = get_user_aktif()
        sudah_kumpul = session.get(f"sudah_kumpul_{kunci_sesi}", False)

        if user and not sudah_kumpul:
            session[f"sudah_kumpul_{kunci_sesi}"] = True
            kode_bab = f"{kelas}_{slug or 'tryout'}"
            bonus_streak = perbarui_streak_harian(user["id"])

            poin_level = {"mudah": 10, "sedang": 15, "sulit": 20}[level]
            if is_tryout:
                poin_level = 15

            with get_db() as db:
                bonus_waktu = (sisa_detik // 20) if (is_tryout and skor > 0) else 0
                perubahan_poin = (skor * poin_level) - (salah_count * 2) + bonus_waktu

                db.execute("""
                    UPDATE users
                    SET poin = MAX(0, poin + ?),
                        soal_benar = soal_benar + ?,
                        soal_salah = soal_salah + ?
                    WHERE id = ?
                """, (perubahan_poin, skor, salah_count, user["id"]))
                db.execute("""
                    INSERT INTO nilai_bab (user_id, kode_bab, nilai) VALUES (?, ?, ?)
                    ON CONFLICT(user_id, kode_bab) DO UPDATE SET nilai = MAX(nilai, excluded.nilai)
                """, (user["id"], kode_bab, nilai))
        else:
            perubahan_poin = 0
            bonus_streak = 0

        bintang = "⭐⭐⭐" if nilai == 100 else ("⭐⭐" if nilai >= 70 else "⭐")
        tanda = "+" if perubahan_poin >= 0 else ""
        teks_streak = f" + 🔥 Bonus Streak Harian (+{bonus_streak} pts)!" if bonus_streak > 0 else ""
        pesan = f"Benar {skor}, Salah {salah_count} ({tanda}{perubahan_poin} Poin){teks_streak}"

    url_ulang = f"/kelas/{kelas}/{slug}/latihan?level={level}" if slug else f"/kelas/{kelas}/latihan"
    url_kembali = f"/kelas/{kelas}/{slug}" if slug else f"/kelas/{kelas}"
    level_berikut = "sedang" if level == "mudah" else ("sulit" if level == "sedang" else None)

    html = """
    <p><a href="{{ url_kembali }}">&larr; Kembali</a></p>
    <h1>{{ judul_latihan }}</h1>

    {% if not is_tryout %}
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px;">
        <a class="pill-nav" style="background:{{ '#22c55e' if level=='mudah' else '#e2e8f0' }}; color:{{ '#fff' if level=='mudah' else '#1e293b' }};" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level=mudah">🟢 Mudah</a>
        <a class="pill-nav" style="background:{{ '#eab308' if level=='sedang' else '#e2e8f0' }}; color:#1e293b;" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level=sedang">🟡 Sedang</a>
        <a class="pill-nav" style="background:{{ '#ef4444' if level=='sulit' else '#e2e8f0' }}; color:{{ '#fff' if level=='sulit' else '#1e293b' }};" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level=sulit">🔴 Sulit</a>
      </div>
    {% endif %}

    {% if is_tryout and not hasil %}
      <div style="background:#1e293b; color:#fff; padding:12px 20px; border-radius:14px; display:flex; justify-content:space-between; align-items:center; font-weight:800; position:sticky; top:70px; z-index:9;">
        <span>⏱️ Sisa Waktu Tryout:</span>
        <span id="tampilan-timer" style="color:#facc15; font-size:1.4rem;">10:00</span>
      </div>
    {% endif %}

    {% if hasil %}
      <div class="nilai-box">
        <div style="font-size:2rem;">{{ bintang }}</div>
        <strong style="font-size:1.4rem;">Nilai: {{ nilai }}</strong><br>
        <span>{{ pesan }}</span>
      </div>
      <script>bunyiEfek("{{ 'benar' if nilai >= 70 else 'salah' }}");</script>
    {% endif %}

    <form id="form-kuis" method="post">
      <input type="hidden" id="sisa-detik" name="sisa_detik" value="600">
      {% for s in soal %}
        {% set i = loop.index0 %}
        <fieldset class="soal {% if hasil %}{{ 'benar' if hasil[i].benar else 'salah' }}{% endif %}">
          <legend>Soal {{ loop.index }}</legend>
          <p style="font-weight:800;">{{ s.tanya }}</p>
          {% for p in s.pilihan %}
            <label class="opsi">
              <input type="radio" name="soal{{ i }}" value="{{ loop.index0 }}" {% if not is_tryout %}required{% endif %}
                {% if hasil %}disabled{% if hasil[i].dipilih == loop.index0 %} checked{% endif %}{% endif %}>
              <span>{{ p }}</span>
            </label>
          {% endfor %}
          {% if hasil %}
            <div class="bahas">
              <strong>{{ '✅ Benar!' if hasil[i].benar else '❌ Jawaban tepat: ' ~ s.pilihan[s.jawaban] ~ '.' }}</strong> {{ s.bahas }}
              {% if not hasil[i].benar %}
                <div style="margin-top:8px;">
                  <button type="button" class="tombol-3d" style="padding:6px 14px; font-size:0.85rem; background:#8b5cf6; box-shadow:0 3px 0 #5b21b6;"
                    data-idx="{{ i }}"
                    data-soal="{{ s.tanya }}"
                    data-murid="{{ s.pilihan[hasil[i].dipilih] if hasil[i].dipilih is not none else 'Kosong' }}"
                    data-benar="{{ s.pilihan[s.jawaban] }}"
                    data-bahas="{{ s.bahas }}"
                    onclick="tanyaTutorAI(this)">
                    🤖 Masih Bingung? Tanya Cara Mengerjakan ke AI
                  </button>
                </div>
                <div id="ai-box-{{ i }}" class="kotak-ai"></div>
              {% endif %}
            </div>
          {% endif %}
        </fieldset>
      {% endfor %}
      {% if hasil %}
        <div style="display:flex; gap:10px; flex-wrap:wrap;">
          <a class="tombol-3d" href="{{ url_ulang }}">🔄 Kerjakan Soal Baru</a>
          {% if not is_tryout and level_berikut and nilai >= 70 %}
            <a class="tombol-3d tombol-merah" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level={{ level_berikut }}">🚀 Lanjut Level {{ level_berikut|capitalize }} &rarr;</a>
          {% endif %}
          <a class="tombol-3d tombol-hijau" href="/profil">📊 Lihat Progress Saya</a>
        </div>
      {% else %}
        <button class="tombol-3d tombol-hijau" type="submit">🚀 Kumpulkan Jawaban</button>
      {% endif %}
    </form>

    <script>
      async function tanyaTutorAI(btn) {
        const idx = btn.dataset.idx;
        const box = document.getElementById('ai-box-' + idx);
        box.style.display = 'block';
        box.innerText = '🤖 Asisten Tutor AI sedang menyiapkan langkah-langkah mudahnya...';
        try {
          const res = await fetch('/tanya-ai', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              soal: btn.dataset.soal,
              jawaban_murid: btn.dataset.murid,
              jawaban_benar: btn.dataset.benar,
              bahas: btn.dataset.bahas
            })
          });
          const data = await res.json();
          box.innerText = data.jawaban;
        } catch(e) {
          box.innerText = '⚠️ Gagal menghubungi AI. Coba periksa koneksi internetmu ya!';
        }
      }
    </script>

    {% if is_tryout and not hasil %}
    <script>
      let detik = 600;
      const el = document.getElementById('tampilan-timer');
      const inputDetik = document.getElementById('sisa-detik');
      const interval = setInterval(() => {
        detik--;
        inputDetik.value = detik;
        let m = String(Math.floor(detik / 60)).padStart(2, '0');
        let s = String(detik % 60).padStart(2, '0');
        el.innerText = m + ':' + s;
        if (detik <= 60) el.style.color = '#ef4444';
        if (detik <= 0) {
          clearInterval(interval);
          alert('Waktu Tryout habis! Jawabanmu otomatis dikumpulkan.');
          document.getElementById('form-kuis').submit();
        }
      }, 1000);
    </script>
    {% endif %}"""
    return render_halaman(html, kelas=kelas, slug=slug, level=level, level_berikut=level_berikut,
                          is_tryout=is_tryout, judul_latihan=judul_latihan, soal=soal, hasil=hasil,
                          skor=skor, nilai=nilai, pesan=pesan, bintang=bintang, url_ulang=url_ulang, url_kembali=url_kembali)

# ================= MINI-GAME =================
@app.route("/minigame", methods=["GET", "POST"])
def minigame():
    if request.method == "POST":
        benar_game = max(0, min(60, int(request.form.get("benar_game", 0) or 0)))
        salah_game = max(0, min(60, int(request.form.get("salah_game", 0) or 0)))
        poin_valid = max(0, (benar_game * 10) - (salah_game * 2))
        user = get_user_aktif()
        if user:
            with get_db() as db:
                db.execute("""
                    UPDATE users
                    SET poin = MAX(0, poin + ?),
                        soal_benar = soal_benar + ?,
                        soal_salah = soal_salah + ?
                    WHERE id = ?
                """, (poin_valid, benar_game, salah_game, user["id"]))
        return redirect(url_for("leaderboard"))

    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    <h1>🎮 Math Blitz: Tantangan 60 Detik!</h1>
    <div id="layar-awal" style="text-align:center; padding:24px; background:#f8fafc; border-radius:20px; border:3px dashed #cbd5e1;">
      <p style="font-weight:800;">Pilih Level Permainan:</p>
      <div style="display:flex; justify-content:center; gap:12px; flex-wrap:wrap; margin:16px 0;">
        <button class="tombol-3d tombol-hijau" onclick="mulaiGame('mudah')">🐣 Mudah (Kelas 1-2)</button>
        <button class="tombol-3d" onclick="mulaiGame('sedang')">🚀 Sedang (Kelas 3-4)</button>
        <button class="tombol-3d tombol-merah" onclick="mulaiGame('sulit')">🔥 Sulit (Kelas 5-6)</button>
      </div>
    </div>

    <div id="layar-main" style="display:none;">
      <div style="display:flex; justify-content:space-between; background:#1e293b; color:#fff; padding:14px 20px; border-radius:16px; margin-bottom:18px; font-weight:800;">
        <div>⏱️ <span id="waktu" style="color:#facc15;">60</span>d</div>
        <div>✅ <span id="b-game" style="color:#4ade80;">0</span> | ❌ <span id="s-game" style="color:#f87171;">0</span></div>
        <div>⭐ Skor: <span id="skor" style="color:#facc15;">0</span></div>
      </div>
      <div style="text-align:center; padding:30px 20px; background:#eff6ff; border:3px solid #3b82f6; border-radius:22px;">
        <div id="teks-soal" style="font-family:'Fredoka',sans-serif; font-size:2.5rem; color:#1e3a8a; margin-bottom:20px;"></div>
        <div id="wadah-opsi" style="display:grid; grid-template-columns:repeat(2, 1fr); gap:14px; max-width:420px; margin:0 auto;"></div>
      </div>
    </div>

    <div id="layar-selesai" style="display:none; text-align:center; padding:28px; background:#fef9c3; border:3px solid #eab308; border-radius:22px;">
      <h2>🏆 Waktu Habis!</h2>
      <p style="font-size:1.2rem;">Benar: <strong id="akhir-benar" style="color:#16a34a;">0</strong> | Salah: <strong id="akhir-salah" style="color:#dc2626;">0</strong></p>
      <p style="font-size:1.3rem;">Skor Didapat: <strong id="skor-akhir" style="color:#2563eb; font-size:1.8rem;">0</strong></p>
      <form method="post">
        <input type="hidden" id="input-benar-game" name="benar_game" value="0">
        <input type="hidden" id="input-salah-game" name="salah_game" value="0">
        <button class="tombol-3d tombol-hijau" type="submit">💾 Simpan Hasil ke Profil &amp; Leaderboard</button>
      </form>
    </div>

    <script>
      let skor = 0, benarCount = 0, salahCount = 0, waktu = 60, timer = null, levelSekarang = 'mudah', jawabanBenar = 0;
      function acak(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }
      function mulaiGame(level) {
        levelSekarang = level; skor = 0; benarCount = 0; salahCount = 0; waktu = 60;
        document.getElementById('layar-awal').style.display = 'none';
        document.getElementById('layar-main').style.display = 'block';
        soalBaru();
        timer = setInterval(() => {
          waktu--; document.getElementById('waktu').innerText = waktu;
          if (waktu <= 0) {
            clearInterval(timer);
            document.getElementById('layar-main').style.display = 'none';
            document.getElementById('layar-selesai').style.display = 'block';
            document.getElementById('skor-akhir').innerText = skor;
            document.getElementById('akhir-benar').innerText = benarCount;
            document.getElementById('akhir-salah').innerText = salahCount;
            document.getElementById('input-benar-game').value = benarCount;
            document.getElementById('input-salah-game').value = salahCount;
          }
        }, 1000);
      }
      function soalBaru() {
        let a, b, teks;
        if (levelSekarang === 'mudah') { a = acak(2, 15); b = acak(2, 15); jawabanBenar = a + b; teks = a + " + " + b; }
        else if (levelSekarang === 'sedang') { a = acak(3, 9); b = acak(3, 9); jawabanBenar = a * b; teks = a + " × " + b; }
        else { a = acak(6, 12); b = acak(6, 12); jawabanBenar = a * b; teks = a + " × " + b; }
        document.getElementById('teks-soal').innerText = teks + " = ?";
        let opsi = new Set([jawabanBenar]);
        while (opsi.size < 4) { let s = jawabanBenar + acak(-6, 6); if (s > 0 && s !== jawabanBenar) opsi.add(s); }
        const wadah = document.getElementById('wadah-opsi'); wadah.innerHTML = '';
        Array.from(opsi).sort(() => Math.random() - 0.5).forEach(n => {
          const btn = document.createElement('button'); btn.className = 'tombol-3d'; btn.style.fontSize = '1.4rem'; btn.innerText = n;
          btn.onclick = () => {
            if (n === jawabanBenar) { benarCount++; skor += 10; bunyiEfek('benar'); }
            else { salahCount++; skor = Math.max(0, skor - 2); bunyiEfek('salah'); }
            document.getElementById('skor').innerText = skor;
            document.getElementById('b-game').innerText = benarCount;
            document.getElementById('s-game').innerText = salahCount;
            soalBaru();
          };
          wadah.appendChild(btn);
        });
      }
    </script>"""
    return render_halaman(html)

# ================= DASHBOARD KHUSUS IBU GURU =================
@app.route("/guru", methods=["GET", "POST"])
def guru():
    pesan_guru = None
    err_guru = None

    if request.method == "POST":
        aksi = request.form.get("aksi")
        if aksi == "login_guru":
            if request.form.get("pin_guru") == PIN_GURU:
                session.permanent = True
                session["is_guru"] = True
            else:
                err_guru = "PIN Ibu Guru salah!"
        elif aksi == "logout_guru":
            session.pop("is_guru", None)
            return redirect(url_for("login"))
        elif session.get("is_guru"):
            uid = request.form.get("user_id")
            if aksi == "setujui_murid":
                with get_db() as db:
                    db.execute("UPDATE users SET status = 'aktif' WHERE id = ?", (uid,))
                pesan_guru = "Akun murid berhasil disetujui!"
            elif aksi == "tambah_pr":
                kode_pilihan = request.form.get("kode_materi", "")
                catatan = request.form.get("catatan", "").strip()
                if "|" in kode_pilihan:
                    k_str, slug_pr = kode_pilihan.split("|", 1)
                    m_obj = next((x for x in MATERI if str(x["kelas"]) == k_str and x["slug"] == slug_pr), None)
                    if m_obj:
                        with get_db() as db:
                            db.execute("INSERT INTO tugas_pr (kelas, slug, judul_bab, catatan) VALUES (?, ?, ?, ?)",
                                       (m_obj["kelas"], m_obj["slug"], m_obj["judul"], catatan))
                        pesan_guru = f"PR baru Kelas {m_obj['kelas']} ({m_obj['judul']}) berhasil dikirim ke beranda murid!"
            elif aksi == "hapus_pr":
                pr_id = request.form.get("pr_id")
                with get_db() as db:
                    db.execute("DELETE FROM tugas_pr WHERE id = ?", (pr_id,))
                pesan_guru = "Tugas PR berhasil dihapus."
            elif aksi == "reset_pin":
                pin_baru = request.form.get("pin_baru", "").strip()
                if len(pin_baru) == 4 and pin_baru.isdigit():
                    with get_db() as db:
                        db.execute("UPDATE users SET pin = ? WHERE id = ?", (pin_baru, uid))
                    pesan_guru = "PIN murid berhasil diperbarui!"
                else:
                    err_guru = "PIN baru harus 4 angka!"
            elif aksi == "hapus_murid":
                with get_db() as db:
                    db.execute("DELETE FROM nilai_bab WHERE user_id = ?", (uid,))
                    db.execute("DELETE FROM users WHERE id = ?", (uid,))
                pesan_guru = "Akun berhasil dihapus/ditolak."

    if not session.get("is_guru"):
        html_login_guru = """
        <p><a href="/login">&larr; Kembali ke Halaman Masuk Murid</a></p>
        <div style="max-width:400px; margin:20px auto; background:#fefce8; padding:24px; border-radius:20px; border:3px solid #eab308;">
          <h1 style="margin-top:0; font-size:1.6rem;">👩‍🏫 Ruang Khusus Ibu Guru</h1>
          <p>Masukkan PIN Rahasia Guru untuk menyetujui murid baru, membuat PR, &amp; memantau nilai.</p>
          {% if err_guru %}<p style="color:#dc2626; font-weight:800;">⚠️ {{ err_guru }}</p>{% endif %}
          <form method="post">
            <input type="hidden" name="aksi" value="login_guru">
            <input class="input-box" type="password" name="pin_guru" placeholder="Masukkan PIN Guru" required>
            <button class="tombol-3d" type="submit">Masuk Dashboard Guru</button>
          </form>
        </div>"""
        return render_halaman(html_login_guru, err_guru=err_guru)

    with get_db() as db:
        antrean_rows = db.execute("SELECT id, nama, pin, avatar FROM users WHERE status = 'pending' ORDER BY id ASC").fetchall()
        pr_rows = db.execute("SELECT * FROM tugas_pr ORDER BY id DESC").fetchall()
        murid_rows = db.execute("""
            SELECT u.id, u.nama, u.pin, u.avatar, u.poin, u.soal_benar, u.soal_salah, u.streak,
                   COUNT(n.kode_bab) AS bab_selesai
            FROM users u
            LEFT JOIN nilai_bab n ON u.id = n.user_id
            WHERE u.status = 'aktif'
            GROUP BY u.id
            ORDER BY u.poin DESC, u.nama ASC
        """).fetchall()

    html_dashboard = """
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
      <h1>👩‍🏫 Dashboard Pantauan Ibu Guru</h1>
      <form method="post" style="margin:0;">
        <input type="hidden" name="aksi" value="logout_guru">
        <button class="tombol-3d" style="background:#64748b; box-shadow:0 4px 0 #475569; padding:8px 16px; font-size:0.9rem;" type="submit">Keluar Mode Guru</button>
      </form>
    </div>

    {% if pesan_guru %}<div style="background:#dcfce7; color:#166534; padding:12px; border-radius:12px; font-weight:800; margin-bottom:14px;">✅ {{ pesan_guru }}</div>{% endif %}
    {% if err_guru %}<div style="background:#fee2e2; color:#991b1b; padding:12px; border-radius:12px; font-weight:800; margin-bottom:14px;">⚠️ {{ err_guru }}</div>{% endif %}

    {% if antrean_rows %}
      <div style="background:#fef9c3; border:3px solid #eab308; border-radius:18px; padding:18px; margin-bottom:22px;">
        <h2 style="margin-top:0; color:#854d0e;">🔔 Pendaftaran Baru Menunggu Persetujuan ({{ antrean_rows|length }})</h2>
        <div style="overflow-x:auto;">
          <table class="tabel-lb" style="margin-top:8px;">
            <thead><tr><th>Calon Murid</th><th>PIN</th><th>Keputusan</th></tr></thead>
            <tbody>
              {% for a in antrean_rows %}
                <tr style="background:#fff;">
                  <td><span style="font-size:1.4rem;">{{ a.avatar }}</span> <strong>{{ a.nama }}</strong></td>
                  <td><code>{{ a.pin }}</code></td>
                  <td>
                    <form method="post" style="display:inline;">
                      <input type="hidden" name="aksi" value="setujui_murid">
                      <input type="hidden" name="user_id" value="{{ a.id }}">
                      <button type="submit" style="background:#22c55e; color:#fff; border:none; padding:6px 14px; border-radius:8px; font-weight:800; cursor:pointer;">✅ Terima</button>
                    </form>
                    <form method="post" style="display:inline;" onsubmit="return confirm('Tolak & hapus pendaftaran {{ a.nama }}?');">
                      <input type="hidden" name="aksi" value="hapus_murid">
                      <input type="hidden" name="user_id" value="{{ a.id }}">
                      <button type="submit" style="background:#ef4444; color:#fff; border:none; padding:6px 12px; border-radius:8px; font-weight:800; cursor:pointer;">❌ Tolak</button>
                    </form>
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
    {% endif %}

    <div style="background:#eff6ff; border:2px solid #93c5fd; border-radius:18px; padding:18px; margin-bottom:22px;">
      <h2 style="margin-top:0;">📋 Beri Tugas / PR ke Murid</h2>
      <form method="post" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
        <input type="hidden" name="aksi" value="tambah_pr">
        <select name="kode_materi" required style="padding:10px; border-radius:10px; border:2px solid #cbd5e1; font:inherit; flex:1; min-width:220px;">
          {% for m in daftar_materi %}
            <option value="{{ m.kelas }}|{{ m.slug }}">Kelas {{ m.kelas }} — {{ m.judul }}</option>
          {% endfor %}
        </select>
        <input type="text" name="catatan" placeholder="Catatan (misal: Kerjakan sebelum Jumat)" style="padding:10px; border-radius:10px; border:2px solid #cbd5e1; font:inherit; flex:1; min-width:200px;">
        <button type="submit" class="tombol-3d" style="padding:10px 18px; font-size:0.95rem;">+ Pasang PR</button>
      </form>
      {% if pr_rows %}
        <div style="margin-top:12px;">
          {% for pr in pr_rows %}
            <div style="display:flex; justify-content:space-between; align-items:center; background:#fff; padding:8px 12px; border-radius:10px; margin-top:6px; border:1px solid #cbd5e1;">
              <span><strong>Kelas {{ pr.kelas }}: {{ pr.judul_bab }}</strong> {% if pr.catatan %}({{ pr.catatan }}){% endif %}</span>
              <form method="post" style="margin:0;">
                <input type="hidden" name="aksi" value="hapus_pr">
                <input type="hidden" name="pr_id" value="{{ pr.id }}">
                <button type="submit" style="background:#ef4444; color:#fff; border:none; padding:4px 10px; border-radius:6px; cursor:pointer; font-size:0.8rem;">Hapus PR</button>
              </form>
            </div>
          {% endfor %}
        </div>
      {% endif %}
    </div>

    <h2>📚 Daftar Murid Bimbel Aktif ({{ murid_rows|length }} anak)</h2>
    <div style="overflow-x:auto;">
      <table class="tabel-lb">
        <thead>
          <tr>
            <th>Murid</th>
            <th>PIN</th>
            <th>Streak</th>
            <th>Progress</th>
            <th>Poin</th>
            <th>Aksi Kelola</th>
          </tr>
        </thead>
        <tbody>
          {% for m in murid_rows %}
            <tr>
              <td><span style="font-size:1.4rem;">{{ m.avatar }}</span> <strong>{{ m.nama }}</strong></td>
              <td><code style="background:#f1f5f9; padding:3px 8px; border-radius:6px; font-weight:800;">{{ m.pin }}</code></td>
              <td>🔥 {{ m.streak }}h</td>
              <td><strong>{{ m.bab_selesai }}</strong> / 36 bab</td>
              <td><strong style="color:#2563eb;">{{ m.poin }}</strong></td>
              <td>
                <form method="post" style="display:inline-flex; gap:4px; align-items:center; margin-bottom:4px;">
                  <input type="hidden" name="aksi" value="reset_pin">
                  <input type="hidden" name="user_id" value="{{ m.id }}">
                  <input type="text" name="pin_baru" maxlength="4" pattern="[0-9]{4}" placeholder="PIN baru" required
                         style="width:76px; padding:4px 6px; border:1px solid #cbd5e1; border-radius:6px; font-size:0.85rem;">
                  <button type="submit" style="background:#eab308; border:none; padding:5px 8px; border-radius:6px; font-weight:700; cursor:pointer; font-size:0.8rem;">Ubah</button>
                </form>
                <form method="post" style="display:inline;" onsubmit="return confirm('Yakin hapus akun {{ m.nama }}?');">
                  <input type="hidden" name="aksi" value="hapus_murid">
                  <input type="hidden" name="user_id" value="{{ m.id }}">
                  <button type="submit" style="background:#ef4444; color:#fff; border:none; padding:5px 8px; border-radius:6px; font-weight:700; cursor:pointer; font-size:0.8rem;">Hapus</button>
                </form>
              </td>
            </tr>
          {% else %}
            <tr><td colspan="6" style="text-align:center; color:#64748b;">Belum ada murid aktif yang disetujui.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>"""
    return render_halaman(html_dashboard, antrean_rows=antrean_rows, pr_rows=pr_rows, daftar_materi=MATERI, murid_rows=murid_rows, pesan_guru=pesan_guru, err_guru=err_guru)

if __name__ == "__main__":
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_lokal = s.getsockname()[0]
        s.close()
    except Exception:
        ip_lokal = "127.0.0.1"
    print(f"\n==========================================")
    print(f"Buka di laptop : http://127.0.0.1:5000")
    print(f"Buka di HP murid (1 Wi-Fi): http://{ip_lokal}:5000")
    print(f"==========================================\n")
    app.run(host="0.0.0.0", port=5000, debug=True)