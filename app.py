from flask import Flask, render_template_string, abort, request, session, redirect, url_for, jsonify
from datetime import timedelta, date
from contextlib import contextmanager
import urllib.request
import json
import sqlite3
import random
import socket
import os

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kunci-rahasia-bimbel-ifga-eksklusif-2026")
app.permanent_session_lifetime = timedelta(days=30)

NAMA_BIMBEL = "IFGA Kids"
WHATSAPP = os.environ.get("WHATSAPP", "6282367923113")       # ganti nomor WA Ibu Guru (awali 62)
PIN_GURU = os.environ.get("PIN_GURU", "9999")                # ganti PIN rahasia ruang guru (/guru)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database_bimbel.db")

# ================= DATABASE (NEON POSTGRESQL / SQLITE LOKAL) =================
class DBWrapper:
    def __init__(self, conn, is_postgres=False):
        self.conn = conn
        self.is_postgres = is_postgres

    def execute(self, query, params=()):
        if self.is_postgres:
            q = query.replace("?", "%s").replace("MAX(", "GREATEST(")
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(q, params)
            return cur
        return self.conn.execute(query, params)

@contextmanager
def get_db():
    if DATABASE_URL and psycopg2 is not None:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield DBWrapper(conn, is_postgres=True)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield DBWrapper(conn, is_postgres=False)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def init_db():
    pk = "SERIAL PRIMARY KEY" if (DATABASE_URL and psycopg2 is not None) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with get_db() as db:
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id {pk},
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
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS tugas_pr (
                id {pk},
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
    s_ini, s_kmr = hari_ini.isoformat(), kemarin.isoformat()
    with get_db() as db:
        u = db.execute("SELECT streak, terakhir_belajar FROM users WHERE id = ?", (user_id,)).fetchone()
        if not u or u["terakhir_belajar"] == s_ini:
            return 0
        streak_baru = (u["streak"] + 1) if u["terakhir_belajar"] == s_kmr else 1
        db.execute("UPDATE users SET streak = ?, terakhir_belajar = ?, poin = poin + 15 WHERE id = ?",
                   (streak_baru, s_ini, user_id))
        return 15

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
        total = r["soal_benar"] + r["soal_salah"]
        akurasi = round((r["soal_benar"] / total) * 100) if total > 0 else 0
        hasil.append({
            "rank": idx, "id": r["id"], "nama": r["nama"], "avatar": r["avatar"],
            "poin": r["poin"], "benar": r["soal_benar"], "salah": r["soal_salah"],
            "streak": r["streak"], "total_soal": total, "akurasi": akurasi,
            "hadiah": HADIAH_PERINGKAT.get(idx)
        })
    return hasil

def get_user_aktif():
    uid = session.get("user_id")
    if not uid:
        return None
    return next((u for u in ambil_leaderboard() if u["id"] == uid), None)

# ================= ILUSTRASI & ALAT PERAGA INTERAKTIF =================
SVG_BANGUN = """
<div style="display:flex; gap:14px; flex-wrap:wrap; margin:12px 0;">
  <div style="text-align:center; background:#fff; padding:10px 16px; border-radius:14px; border:2px solid #cbd5e1;">
    <svg width="70" height="64"><polygon points="35,4 4,60 66,60" fill="#fde047" stroke="#ca8a04" stroke-width="3"/></svg>
    <div style="font-size:0.85rem; font-weight:800;">Segitiga (3 Sisi)</div>
  </div>
  <div style="text-align:center; background:#fff; padding:10px 16px; border-radius:14px; border:2px solid #cbd5e1;">
    <svg width="70" height="64"><rect x="6" y="6" width="58" height="52" rx="4" fill="#93c5fd" stroke="#2563eb" stroke-width="3"/></svg>
    <div style="font-size:0.85rem; font-weight:800;">Segi Empat (4 Sisi)</div>
  </div>
  <div style="text-align:center; background:#fff; padding:10px 16px; border-radius:14px; border:2px solid #cbd5e1;">
    <svg width="70" height="64"><circle cx="35" cy="32" r="27" fill="#fca5a5" stroke="#dc2626" stroke-width="3"/></svg>
    <div style="font-size:0.85rem; font-weight:800;">Lingkaran (1 Lengkung)</div>
  </div>
</div>"""

WIDGET_NILAI_TEMPAT = """
<div style="background:#eff6ff; border:2px solid #3b82f6; border-radius:16px; padding:16px; margin-top:16px;">
  <h3 style="margin-top:0; color:#1d4ed8;">🧩 Alat Peraga Nilai Tempat Interaktif</h3>
  <p style="margin:4px 0 10px; font-size:0.95rem;">Ketik angka bebas (1 sampai 9999) untuk melihat rumah nilai tempatnya:</p>
  <input type="number" id="inp-nt" value="2458" min="1" max="9999" oninput="hitungNT()"
         style="padding:8px 12px; font-size:1.2rem; font-weight:800; width:140px; border-radius:10px; border:2px solid #2563eb;">
  <div id="hasil-nt" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(110px, 1fr)); gap:10px; margin-top:12px; text-align:center;"></div>
  <div id="uraian-nt" style="margin-top:10px; font-weight:800; color:#1e3a8a; background:#fff; padding:8px 12px; border-radius:10px;"></div>
</div>
<script>
function hitungNT() {
  let n = parseInt(document.getElementById('inp-nt').value) || 0;
  if (n > 9999) n = 9999;
  const rb = Math.floor(n / 1000);
  const rt = Math.floor((n % 1000) / 100);
  const pl = Math.floor((n % 100) / 10);
  const st = n % 10;
  const kartu = [
    {label: 'Ribuan', val: rb, nil: rb*1000, bg: '#fae8ff', bd: '#a855f7'},
    {label: 'Ratusan', val: rt, nil: rt*100, bg: '#fef08a', bd: '#eab308'},
    {label: 'Puluhan', val: pl, nil: pl*10, bg: '#bbf7d0', bd: '#22c55e'},
    {label: 'Satuan', val: st, nil: st, bg: '#fecdd3', bd: '#f43f5e'}
  ];
  document.getElementById('hasil-nt').innerHTML = kartu.map(k =>
    `<div style="background:${k.bg}; border:2px solid ${k.bd}; border-radius:12px; padding:8px;">
      <div style="font-size:0.8rem; font-weight:800;">${k.label}</div>
      <div style="font-size:1.6rem; font-weight:800;">${k.val}</div>
      <div style="font-size:0.8rem;">Nilainya: ${k.nil}</div>
    </div>`
  ).join('');
  document.getElementById('uraian-nt').innerText = `${n} = ${rb*1000} + ${rt*100} + ${pl*10} + ${st}`;
}
hitungNT();
</script>"""

WIDGET_PERKALIAN_SUSUN = """
<div style="background:#f0fdf4; border:2px solid #22c55e; border-radius:16px; padding:16px; margin-top:16px;">
  <h3 style="margin-top:0; color:#15803d;">🧮 Simulator Perkalian Bersusun</h3>
  <p style="margin:4px 0 10px; font-size:0.95rem;">Masukkan dua bilangan untuk melihat cara menghitung perkalian bersusun ke bawah:</p>
  <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
    <input type="number" id="ps-a" value="24" min="2" max="999" oninput="hitungPS()" style="width:90px; padding:8px; font-weight:800; border-radius:10px; border:2px solid #16a34a;">
    <strong>×</strong>
    <input type="number" id="ps-b" value="13" min="2" max="99" oninput="hitungPS()" style="width:90px; padding:8px; font-weight:800; border-radius:10px; border:2px solid #16a34a;">
  </div>
  <pre id="out-ps" style="background:#1e293b; color:#facc15; padding:14px 18px; border-radius:12px; font-size:1.1rem; line-height:1.5; margin-top:12px; overflow-x:auto;"></pre>
</div>
<script>
function hitungPS() {
  let a = parseInt(document.getElementById('ps-a').value) || 0;
  let b = parseInt(document.getElementById('ps-b').value) || 0;
  let sat = b % 10, pul = Math.floor(b / 10);
  let baris1 = a * sat;
  let teks = `    ${String(a).padStart(4)}\n  × ${String(b).padStart(4)}\n  ------\n`;
  if (pul === 0) {
    teks += `    ${String(baris1).padStart(4)}  <-- (${a} × ${sat})`;
  } else {
    let baris2 = a * pul;
    teks += `    ${String(baris1).padStart(4)}  <-- (${a} × ${sat} satuan)\n  + ${String(baris2).padStart(3)}   <-- (${a} × ${pul} puluhan, geser 1 ke kiri)\n  ------\n    ${String(a*b).padStart(4)}  <-- Hasil akhir`;
  }
  document.getElementById('out-ps').innerText = teks;
}
hitungPS();
</script>"""

LINK_TABEL_BOX = """<div style="margin-top:12px;"><a class="tombol-3d tombol-kuning" style="padding:8px 16px; font-size:0.95rem;" href="/tabel">📊 Buka Tabel Perkalian &amp; Pembagian (1–10)</a></div>"""

# ================= DATA MATERI (38 BAB: KELAS 1 - 6) =================
MATERI = [
    # KELAS 1
    {"kelas": 1, "slug": "penjumlahan-1-sampai-20", "judul": "Bab 1: Penjumlahan Bilangan 1 sampai 20",
     "isi": "<p><strong>Penjumlahan (+)</strong> artinya menggabungkan dua kelompok benda menjadi lebih banyak. Simpan angka besar di kepala, lalu hitung maju.</p><div class='contoh'>Contoh: 8 + 5 = 13 (hitung maju dari 8: 9, 10, 11, 12, 13)</div>"},
    {"kelas": 1, "slug": "pengurangan-1-sampai-20", "judul": "Bab 2: Pengurangan Bilangan 1 sampai 20",
     "isi": "<p><strong>Pengurangan (-)</strong> artinya mengambil sebagian benda sehingga sisanya berkurang.</p><div class='contoh'>Contoh: 14 - 6 = 8 (hitung mundur 6 langkah dari 14)</div>"},
    {"kelas": 1, "slug": "nilai-tempat-puluhan-satuan", "judul": "Bab 3: Mengenal Nilai Tempat Puluhan dan Satuan",
     "isi": "<p>Pada bilangan dua angka, angka depan (kiri) menempati <strong>Puluhan</strong> dan angka belakang (kanan) menempati <strong>Satuan</strong>.</p><div class='contoh'>17 = 1 puluhan + 7 satuan (10 + 7)</div>" + WIDGET_NILAI_TEMPAT},
    {"kelas": 1, "slug": "membandingkan-bilangan", "judul": "Bab 4: Membandingkan & Mengurutkan Bilangan",
     "isi": "<p>Bandingkan angka puluhannya terlebih dahulu; jika sama, baru bandingkan angka satuannya.</p><div class='contoh'>18 lebih besar dari 12 &nbsp;|&nbsp; Urutan kecil ke besar: 9, 11, 14, 19</div>"},
    {"kelas": 1, "slug": "mengenal-waktu-jam", "judul": "Bab 5: Mengenal Waktu dan Jam Tepat",
     "isi": "<p><strong>Jarum pendek</strong> menunjuk jam, <strong>jarum panjang</strong> di angka 12 berarti tepat (.00).</p><div class='contoh'>Jarum pendek di 4, jarum panjang di 12 = Pukul 04.00</div>"},
    {"kelas": 1, "slug": "bangun-datar-sederhana", "judul": "Bab 6: Mengenal Bentuk Bangun Datar",
     "isi": SVG_BANGUN + "<p><strong>Segitiga</strong> (3 sisi), <strong>Segi Empat</strong> (4 sisi), <strong>Lingkaran</strong> (1 sisi lengkung).</p>"},

    # KELAS 2
    {"kelas": 2, "slug": "penjumlahan-bersusun", "judul": "Bab 1: Penjumlahan Bersusun Ratusan",
     "isi": "<p>Luruskan satuan dengan satuan, puluhan dengan puluhan, lalu jumlahkan dari belakang.</p><div class='contoh'>126 + 57 = 183 (6 + 7 = 13 &rarr; tulis 3, simpan 1 ke puluhan)</div>"},
    {"kelas": 2, "slug": "pengurangan-bersusun", "judul": "Bab 2: Pengurangan Bersusun & Teknik Meminjam",
     "isi": "<p>Jika angka atas lebih kecil dari bawah, pinjam 1 puluhan (10) dari angka di sebelah kirinya.</p><div class='contoh'>72 - 37 = 35 (12 - 7 = 5, lalu 6 - 3 = 3)</div>"},
    {"kelas": 2, "slug": "konsep-perkalian-awal", "judul": "Bab 3: Pengenalan Perkalian Dasar",
     "isi": "<p><strong>A x B</strong> artinya angka B dijumlahkan secara berulang sebanyak A kali.</p><div class='contoh'>3 x 4 = 4 + 4 + 4 = 12</div>" + LINK_TABEL_BOX},
    {"kelas": 2, "slug": "pembagian-awal", "judul": "Bab 4: Pengenalan Pembagian Dasar",
     "isi": "<p>Membagi benda sama banyak sampai habis (0) dengan pengurangan berulang.</p><div class='contoh'>12 : 3 = 4 (12 - 3 - 3 - 3 - 3 = 0)</div>" + LINK_TABEL_BOX},
    {"kelas": 2, "slug": "satuan-panjang-berat", "judul": "Bab 5: Pengukuran Panjang (m & cm) dan Berat (kg & g)",
     "isi": "<div class='contoh'>1 meter (m) = 100 cm &nbsp;|&nbsp; 1 kilogram (kg) = 1.000 gram</div>"},
    {"kelas": 2, "slug": "nilai-mata-uang", "judul": "Bab 6: Mengenal Nilai Mata Uang Rupiah",
     "isi": "<div class='contoh'>2 lembar Rp5.000 = Rp10.000 &nbsp;|&nbsp; Rp2.000 + Rp5.000 = Rp7.000</div>"},
    {"kelas": 2, "slug": "nilai-tempat-ratusan-ribuan", "judul": "Bab 7: Nilai Tempat Ratusan dan Ribuan",
     "isi": "<p>Urutan rumah nilai tempat dari kiri ke kanan adalah: <strong>Ribuan &rarr; Ratusan &rarr; Puluhan &rarr; Satuan</strong>.</p><div class='contoh'>3.452 = 3 ribuan (3.000) + 4 ratusan (400) + 5 puluhan (50) + 2 satuan (2)</div>" + WIDGET_NILAI_TEMPAT},

    # KELAS 3
    {"kelas": 3, "slug": "perkalian-1-sampai-10", "judul": "Bab 1: Perkalian Bilangan 1 sampai 10",
     "isi": "<p>Sifat pertukaran perkalian: <strong>7 x 6 = 6 x 7 = 42</strong>. Semua angka dikali 0 hasilnya 0.</p><div class='contoh'>8 x 7 = 56 &nbsp;|&nbsp; 9 x 6 = 54</div>" + LINK_TABEL_BOX},
    {"kelas": 3, "slug": "pembagian-dasar", "judul": "Bab 2: Pembagian Bilangan",
     "isi": "<p>Pembagian adalah kebalikan dari perkalian.</p><div class='contoh'>56 : 8 = 7 (karena 8 x 7 = 56)</div>" + LINK_TABEL_BOX},
    {"kelas": 3, "slug": "operasi-hitung-campuran", "judul": "Bab 3: Operasi Hitung Campuran (KABATAKU)",
     "isi": "<p>Kerjakan dalam kurung dulu, lalu <strong>Kali (x) &amp; Bagi (:)</strong>, terakhir <strong>Tambah (+) &amp; Kurang (-)</strong>.</p><div class='contoh'>10 + 4 x 3 = 10 + 12 = 22</div>"},
    {"kelas": 3, "slug": "pecahan-sederhana", "judul": "Bab 4: Mengenal Pecahan Sederhana",
     "isi": "<p>Pada <strong>a/b</strong>, <em>a</em> = pembilang (bagian diambil) dan <em>b</em> = penyebut (seluruh potongan sama besar).</p><div class='contoh'>1 kue dipotong 4, dimakan 1 = 1/4</div>"},
    {"kelas": 3, "slug": "satuan-waktu-lama", "judul": "Bab 5: Konversi Satuan Waktu (Jam, Menit, Detik)",
     "isi": "<div class='contoh'>1 jam = 60 menit &nbsp;|&nbsp; 1 menit = 60 detik &nbsp;|&nbsp; 1 hari = 24 jam</div>"},
    {"kelas": 3, "slug": "keliling-bangun-datar", "judul": "Bab 6: Keliling Persegi dan Persegi Panjang",
     "isi": SVG_BANGUN + "<div class='contoh'>Keliling Persegi = 4 x sisi &nbsp;|&nbsp; Keliling Persegi Panjang = 2 x (p + l)</div>"},
    {"kelas": 3, "slug": "perkalian-bersusun", "judul": "Bab 7: Perkalian Bersusun (Puluhan & Ratusan)",
     "isi": "<h3>Cara Perkalian Bersusun Ke Bawah</h3><ol><li>Kalikan angka atas dengan <strong>satuan</strong> pengali dari belakang (jika hasil &ge; 10, tulis satuannya dan simpan puluhannya).</li><li>Jika pengali 2 angka, kalikan juga dengan <strong>puluhan</strong> pengali, tulis hasilnya bergeser 1 langkah ke kiri, lalu jumlahkan.</li></ol><div class='contoh'>Contoh: 24 x 3 = 72 (4x3=12 tulis 2 simpan 1; 2x3=6 + 1 = 7)</div>" + WIDGET_PERKALIAN_SUSUN},

    # KELAS 4
    {"kelas": 4, "slug": "fpb-dan-kpk", "judul": "Bab 1: Kelipatan dan Faktor Bilangan (KPK & FPB)",
     "isi": "<p><strong>KPK</strong> = kelipatan sama terkecil | <strong>FPB</strong> = faktor pembagi sama terbesar.</p><div class='contoh'>KPK(4, 6) = 12 &nbsp;|&nbsp; FPB(12, 18) = 6</div>"},
    {"kelas": 4, "slug": "pecahan-senilai", "judul": "Bab 2: Pecahan Senilai dan Penyederhanaan",
     "isi": "<p>Kalikan atau bagi pembilang dan penyebut dengan angka yang sama.</p><div class='contoh'>2/3 = 4/6 &nbsp;|&nbsp; 6/8 (:2) = 3/4</div>"},
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
        selisih = random.choice([-12, -10, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 10, 12])
        kandidat = jawaban_benar + selisih
        if kandidat != jawaban_benar and (izinkan_negatif or kandidat > 0):
            salah_set.add(kandidat)
    opsi = [jawaban_benar] + list(salah_set)
    random.shuffle(opsi)
    return [f"{a}{satuan}" for a in opsi], opsi.index(jawaban_benar)

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
        a, b = random.randint(5, 11), random.randint(4, 8)
        pil, idx = _buat_pilihan(a + b, " kelereng")
        return {"tanya": f"Budi punya {a} kelereng, lalu diberi Ayah {b} kelereng lagi. Jumlah kelereng Budi adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b} kelereng."}

    elif slug == "pengurangan-1-sampai-20":
        if level == "mudah":
            a = random.randint(5, 10); b = random.randint(1, a - 1)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        elif level == "sedang":
            a = random.randint(12, 20); b = random.randint(4, 9)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        a = random.randint(13, 20); b = random.randint(5, 9)
        pil, idx = _buat_pilihan(a - b, " kue")
        return {"tanya": f"Ibu membuat {a} kue donat, lalu {b} kue dimakan adik. Sisa kue Ibu adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b} kue."}

    elif slug == "nilai-tempat-puluhan-satuan":
        p, s = random.randint(1, 9), random.randint(1, 9)
        if level == "mudah":
            pil, idx = _buat_pilihan(p)
            return {"tanya": f"Angka PULUHAN pada bilangan {p*10+s} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{p*10+s} = {p} puluhan + {s} satuan."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(s)
            return {"tanya": f"Angka SATUAN pada bilangan {p*10+s} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Angka belakang adalah satuan = {s}."}
        pil, idx = _buat_pilihan(p * 10 + s)
        return {"tanya": f"Bilangan yang terdiri dari {p} puluhan dan {s} satuan adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{p} puluhan ({p*10}) + {s} satuan = {p*10+s}."}

    elif slug == "membandingkan-bilangan":
        if level == "mudah":
            a, b = random.sample(range(1, 10), 2)
            pil, idx = _buat_pilihan_teks("lebih besar dari" if a > b else "lebih kecil dari", "lebih kecil dari" if a > b else "lebih besar dari", "sama dengan")
            return {"tanya": f"Bilangan {a} ... bilangan {b}.", "pilihan": pil, "jawaban": idx, "bahas": f"{a} {'lebih dari' if a > b else 'kurang dari'} {b}."}
        elif level == "sedang":
            a, b = random.sample(range(11, 20), 2)
            pil, idx = _buat_pilihan_teks("lebih besar dari" if a > b else "lebih kecil dari", "lebih kecil dari" if a > b else "lebih besar dari", "sama dengan")
            return {"tanya": f"Bilangan {a} ... bilangan {b}.", "pilihan": pil, "jawaban": idx, "bahas": f"{a} {'lebih besar dari' if a > b else 'lebih kecil dari'} {b}."}
        nums = sorted(random.sample(range(8, 20), 3))
        pil, idx = _buat_pilihan_teks(f"{nums[0]}, {nums[1]}, {nums[2]}", f"{nums[2]}, {nums[1]}, {nums[0]}", f"{nums[1]}, {nums[0]}, {nums[2]}")
        return {"tanya": f"Urutan {nums[1]}, {nums[2]}, {nums[0]} dari TERKECIL adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Urutan terkecil: {nums[0]}, {nums[1]}, {nums[2]}."}

    elif slug == "mengenal-waktu-jam":
        jam = random.randint(1, 10)
        if level == "mudah":
            pil, idx = _buat_pilihan(jam, ".00")
            return {"tanya": f"Jarum pendek di {jam} dan jarum panjang di 12. Sekarang pukul ...", "pilihan": pil, "jawaban": idx, "bahas": f"Pukul {jam}.00."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(jam + 2, ".00")
            return {"tanya": f"Sekarang pukul {jam}.00. Dua jam lagi adalah pukul ...", "pilihan": pil, "jawaban": idx, "bahas": f"{jam} + 2 = pukul {jam+2}.00."}
        pil, idx = _buat_pilihan(2, " jam")
        return {"tanya": f"Siti belajar mulai pukul {jam}.00 sampai pukul {jam+2}.00. Lama belajar Siti adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "Lamanya 2 jam."}

    elif slug == "bangun-datar-sederhana":
        if level == "mudah":
            benda, bentuk, s1, s2 = random.choice([("Roda sepeda", "Lingkaran", "Segitiga", "Segi Empat"), ("Papan tulis", "Segi Empat", "Lingkaran", "Segitiga")])
            pil, idx = _buat_pilihan_teks(bentuk, s1, s2)
            return {"tanya": f"{benda} berbentuk bangun datar ...", "pilihan": pil, "jawaban": idx, "bahas": f"{benda} berbentuk {bentuk}."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(3, " sisi")
            return {"tanya": "Segitiga memiliki jumlah sisi sebanyak ...", "pilihan": pil, "jawaban": idx, "bahas": "Segitiga mempunyai 3 sisi."}
        pil, idx = _buat_pilihan_teks("Lingkaran", "Segitiga", "Segi Empat")
        return {"tanya": "Bangun datar yang memiliki 1 sisi melengkung tanpa titik sudut adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "Lingkaran."}

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
        a, b = random.randint(145, 250), random.randint(125, 210)
        pil, idx = _buat_pilihan(a + b, " buku")
        return {"tanya": f"Perpustakaan punya {a} buku cerita dan {b} buku pelajaran. Jumlah seluruh buku adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} + {b} = {a+b} buku."}

    elif slug == "pengurangan-bersusun":
        if level == "mudah":
            a = random.randint(45, 89); b = random.randint(11, 34)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        elif level == "sedang":
            a = random.randint(71, 95); b = random.randint(26, 49)
            pil, idx = _buat_pilihan(a - b)
            return {"tanya": f"{a} - {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b}."}
        a = random.randint(230, 350); b = random.randint(115, 185)
        pil, idx = _buat_pilihan(a - b, " butir")
        return {"tanya": f"Pedagang punya {a} butir telur, lalu terjual {b} butir. Sisa telur adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - {b} = {a-b} butir."}

    elif slug == "konsep-perkalian-awal":
        if level == "mudah":
            a, b = random.randint(2, 4), random.randint(2, 5)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"{a} x {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b}."}
        elif level == "sedang":
            a, b = random.randint(3, 6), random.randint(4, 7)
            pil, idx = _buat_pilihan_teks(" + ".join([str(b)] * a), " + ".join([str(a)] * (b + 1)), f"{a} + {b}")
            return {"tanya": f"Penjumlahan berulang dari {a} x {b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b} dijumlahkan {a} kali."}
        a, b = random.randint(4, 6), random.randint(5, 8)
        pil, idx = _buat_pilihan(a * b, " roda")
        return {"tanya": f"Ada {a} mobil, masing-masing punya {b} roda. Jumlah seluruh roda adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b} roda."}

    elif slug == "pembagian-awal":
        if level == "mudah":
            b, h = random.randint(2, 4), random.randint(2, 5)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        elif level == "sedang":
            b, h = random.randint(4, 6), random.randint(4, 7)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        b, h = random.randint(3, 5), random.randint(4, 7)
        pil, idx = _buat_pilihan(h, " permen")
        return {"tanya": f"Ibu membagi {b*h} permen kepada {b} anak sama banyak. Tiap anak mendapat ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h} permen."}

    elif slug == "satuan-panjang-berat":
        if level == "mudah":
            m = random.randint(2, 7)
            pil, idx = _buat_pilihan(m * 100, " cm")
            return {"tanya": f"{m} meter = ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"{m} x 100 = {m*100} cm."}
        elif level == "sedang":
            kg = random.randint(2, 6)
            pil, idx = _buat_pilihan(kg * 1000, " gram")
            return {"tanya": f"{kg} kg = ... gram.", "pilihan": pil, "jawaban": idx, "bahas": f"{kg} x 1.000 = {kg*1000} gram."}
        m, cm = random.randint(2, 4), random.choice([25, 50, 75])
        pil, idx = _buat_pilihan(m * 100 + cm, " cm")
        return {"tanya": f"Panjang pita {m} meter lebih {cm} cm. Panjang seluruh pita adalah ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"{m*100} + {cm} = {m*100+cm} cm."}

    elif slug == "nilai-mata-uang":
        if level == "mudah":
            a, b = random.choice([(1000, 2000), (2000, 5000), (5000, 5000)])
            pil, idx = _buat_pilihan(a + b, " rupiah")
            return {"tanya": f"Rp{a} + Rp{b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a+b} rupiah."}
        elif level == "sedang":
            lembar = random.randint(3, 5)
            pil, idx = _buat_pilihan(lembar * 2000, " rupiah")
            return {"tanya": f"{lembar} lembar uang Rp2.000 nilainya ...", "pilihan": pil, "jawaban": idx, "bahas": f"{lembar} x Rp2.000 = Rp{lembar*2000}."}
        harga = random.choice([6000, 7000, 8000])
        pil, idx = _buat_pilihan(10000 - harga, " rupiah")
        return {"tanya": f"Andi beli buku Rp{harga} dengan uang Rp10.000. Kembaliannya adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Rp10.000 - Rp{harga} = Rp{10000-harga}."}

    elif slug == "nilai-tempat-ratusan-ribuan":
        rb, rt, pl, st = random.randint(1, 8), random.randint(1, 9), random.randint(1, 9), random.randint(1, 9)
        if level == "mudah":
            bil = rt * 100 + pl * 10 + st
            pil, idx = _buat_pilihan(rt * 100)
            return {"tanya": f"Nilai angka {rt} pada bilangan {bil} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Angka {rt} menempati ratusan sehingga nilainya {rt*100}."}
        elif level == "sedang":
            bil = rb * 1000 + rt * 100 + pl * 10 + st
            pil, idx = _buat_pilihan(rb)
            return {"tanya": f"Angka yang menempati nilai tempat RIBUAN pada bilangan {bil} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Angka paling depan pada {bil} adalah {rb} (ribuan)."}
        bil = rb * 1000 + rt * 100 + pl * 10 + st
        pil, idx = _buat_pilihan(bil)
        return {"tanya": f"{rb} ribuan + {rt} ratusan + {pl} puluhan + {st} satuan = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{rb*1000} + {rt*100} + {pl*10} + {st} = {bil}."}

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
        a, b = random.randint(6, 9), random.randint(7, 9)
        pil, idx = _buat_pilihan(a * b, " apel")
        return {"tanya": f"Ayah membeli {a} keranjang apel, tiap keranjang berisi {b} apel. Total apel adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b} apel."}

    elif slug == "pembagian-dasar":
        if level == "mudah":
            b, h = random.randint(2, 5), random.randint(3, 6)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        elif level == "sedang":
            b, h = random.randint(6, 9), random.randint(6, 9)
            pil, idx = _buat_pilihan(h)
            return {"tanya": f"{b*h} : {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h}."}
        b, h = random.randint(6, 8), random.randint(7, 9)
        pil, idx = _buat_pilihan(h, " kotak")
        return {"tanya": f"Sebanyak {b*h} kue dimasukkan ke kotak, tiap kotak berisi {b} kue. Banyak kotak adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{b*h} : {b} = {h} kotak."}

    elif slug == "operasi-hitung-campuran":
        if level == "mudah":
            a, b, c = random.randint(4, 12), random.randint(2, 4), random.randint(2, 5)
            pil, idx = _buat_pilihan(a + b * c)
            return {"tanya": f"{a} + {b} x {c} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"Kerjakan kali dulu: {b}x{c}={b*c}, lalu +{a} = {a+b*c}."}
        elif level == "sedang":
            a, b, c = random.randint(20, 40), random.randint(3, 6), random.randint(3, 5)
            pil, idx = _buat_pilihan(a - b * c)
            return {"tanya": f"{a} - {b} x {c} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} - ({b}x{c}) = {a - b*c}."}
        a, b, c = random.randint(3, 6), random.randint(2, 5), random.randint(3, 6)
        pil, idx = _buat_pilihan((a + b) * c)
        return {"tanya": f"({a} + {b}) x {c} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"({a}+{b}) = {a+b}, lalu dikali {c} = {(a+b)*c}."}

    elif slug == "pecahan-sederhana":
        if level == "mudah":
            b = random.randint(3, 6); a = random.randint(1, b - 1)
            pil, idx = _buat_pilihan_teks(f"{a}/{b}", f"{b}/{a}", f"1/{b+1}")
            return {"tanya": f"Roti dipotong {b} bagian sama besar, dimakan {a} bagian. Nilainya ...", "pilihan": pil, "jawaban": idx, "bahas": f"Ditulis {a}/{b}."}
        elif level == "sedang":
            b = random.randint(5, 9); a = random.randint(1, b - 2); sisa = b - a
            pil, idx = _buat_pilihan_teks(f"{sisa}/{b}", f"{a}/{b}", f"{b}/{sisa}")
            return {"tanya": f"Pizza dipotong {b} bagian, dimakan {a} potong. SISA pizza adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Sisa = {sisa}/{b}."}
        b = random.randint(5, 9); a1, a2 = random.randint(2, b-1), random.randint(1, b-1)
        if a1 == a2: a1 += 1
        pil, idx = _buat_pilihan_teks(f"{max(a1,a2)}/{b}", f"{min(a1,a2)}/{b}", "Sama besar")
        return {"tanya": f"Manakah pecahan yang LEBIH BESAR antara {a1}/{b} dan {a2}/{b}?", "pilihan": pil, "jawaban": idx, "bahas": f"{max(a1,a2)}/{b} lebih besar."}

    elif slug == "satuan-waktu-lama":
        if level == "mudah":
            jam = random.randint(2, 5)
            pil, idx = _buat_pilihan(jam * 60, " menit")
            return {"tanya": f"{jam} jam = ... menit.", "pilihan": pil, "jawaban": idx, "bahas": f"{jam} x 60 = {jam*60} menit."}
        elif level == "sedang":
            jam, mnt = random.randint(1, 3), random.choice([15, 20, 30, 45])
            pil, idx = _buat_pilihan(jam * 60 + mnt, " menit")
            return {"tanya": f"{jam} jam {mnt} menit = ... menit.", "pilihan": pil, "jawaban": idx, "bahas": f"({jam} x 60) + {mnt} = {jam*60 + mnt} menit."}
        minggu, hari = random.randint(2, 4), random.randint(2, 6)
        pil, idx = _buat_pilihan(minggu * 7 + hari, " hari")
        return {"tanya": f"Liburan sekolah {minggu} minggu lebih {hari} hari = ... hari.", "pilihan": pil, "jawaban": idx, "bahas": f"({minggu} x 7) + {hari} = {minggu*7 + hari} hari."}

    elif slug == "keliling-bangun-datar":
        if level == "mudah":
            s = random.randint(4, 12)
            pil, idx = _buat_pilihan(4 * s, " cm")
            return {"tanya": f"Keliling persegi dengan sisi {s} cm adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"4 x {s} = {4*s} cm."}
        elif level == "sedang":
            p, l = random.randint(8, 15), random.randint(3, 7)
            pil, idx = _buat_pilihan(2 * (p + l), " cm")
            return {"tanya": f"Keliling persegi panjang (p={p} cm, l={l} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"2 x ({p}+{l}) = {2*(p+l)} cm."}
        s = random.randint(5, 11)
        pil, idx = _buat_pilihan(s, " meter")
        return {"tanya": f"Taman berbentuk persegi kelilingnya {4*s} meter. Panjang sisinya adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{4*s} : 4 = {s} meter."}

    elif slug == "perkalian-bersusun":
        if level == "mudah":
            a, b = random.randint(14, 38), random.randint(3, 6)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"Hitung dengan cara bersusun: {a} x {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"Satuan: {a%10}x{b}={(a%10)*b}, Puluhan: {(a//10)*10}x{b}={(a//10)*10*b}. Total = {a*b}."}
        elif level == "sedang":
            a, b = random.randint(12, 24), random.randint(11, 15)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"Hitung perkalian bersusun 2 angka: {a} x {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"({a} x {b%10}) + ({a} x {(b//10)*10}) = {a*(b%10)} + {a*(b//10)*10} = {a*b}."}
        a, b = random.randint(24, 45), random.randint(6, 9)
        pil, idx = _buat_pilihan(a * b, " buku")
        return {"tanya": f"Ada {b} rak buku, setiap rak berisi {a} buku. Jumlah seluruh buku adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {b} = {a*b} buku."}

    # ---- KELAS 4 ----
    elif slug == "fpb-dan-kpk":
        if level == "mudah":
            a, b, kpk, _ = random.choice([(3, 4, 12, 1), (4, 6, 12, 2), (5, 10, 10, 5)])
            pil, idx = _buat_pilihan(kpk)
            return {"tanya": f"KPK dari {a} dan {b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"KPK = {kpk}."}
        elif level == "sedang":
            a, b, _, fpb = random.choice([(12, 18, 36, 6), (16, 24, 48, 8), (15, 25, 75, 5)])
            pil, idx = _buat_pilihan(fpb)
            return {"tanya": f"FPB dari {a} dan {b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"FPB = {fpb}."}
        a, b, kpk = random.choice([(4, 6, 12), (6, 8, 24), (8, 12, 24)])
        pil, idx = _buat_pilihan(kpk, " detik lagi")
        return {"tanya": f"Lampu A menyala tiap {a} detik, lampu B tiap {b} detik. Menyala bersama setiap ...", "pilihan": pil, "jawaban": idx, "bahas": f"KPK({a}, {b}) = {kpk} detik."}

    elif slug == "pecahan-senilai":
        if level == "mudah":
            a, b = random.randint(1, 3), random.randint(4, 6)
            pil, idx = _buat_pilihan(a * 2, f"/{b * 2}")
            return {"tanya": f"Pecahan senilai dengan {a}/{b} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a*2}/{b*2}."}
        elif level == "sedang":
            a, b, k = random.randint(1, 3), random.randint(4, 7), random.randint(3, 5)
            pil, idx = _buat_pilihan(a, f"/{b}")
            return {"tanya": f"Bentuk paling sederhana dari {a*k}/{b*k} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"Bagi {k} = {a}/{b}."}
        a, b, k = random.randint(2, 4), random.randint(5, 8), random.randint(3, 5)
        pil, idx = _buat_pilihan(a * k)
        return {"tanya": f"Jika {a}/{b} = .../{b*k}, angka pembilangnya adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a} x {k} = {a*k}."}

    elif slug == "pembulatan-dan-penaksiran":
        if level == "mudah":
            pul = random.randint(2, 8); sat = random.randint(1, 9); angka = pul * 10 + sat
            hasil = (pul + 1) * 10 if sat >= 5 else pul * 10
            pil, idx = _buat_pilihan(hasil)
            return {"tanya": f"{angka} dibulatkan ke puluhan terdekat menjadi ...", "pilihan": pil, "jawaban": idx, "bahas": f"Menjadi {hasil}."}
        elif level == "sedang":
            rat = random.randint(2, 7); pul = random.randint(15, 85); angka = rat * 100 + pul
            hasil = (rat + 1) * 100 if pul >= 50 else rat * 100
            pil, idx = _buat_pilihan(hasil)
            return {"tanya": f"{angka} dibulatkan ke ratusan terdekat menjadi ...", "pilihan": pil, "jawaban": idx, "bahas": f"Menjadi {hasil}."}
        pil, idx = _buat_pilihan(80)
        return {"tanya": "Taksirlah hasil 38 + 41 ke puluhan terdekat!", "pilihan": pil, "jawaban": idx, "bahas": "40 + 40 = 80."}

    elif slug == "luas-bangun-datar":
        if level == "mudah":
            p, l = random.randint(5, 10), random.randint(3, 7)
            pil, idx = _buat_pilihan(p * l, " cm²")
            return {"tanya": f"Luas persegi panjang (p={p} cm, l={l} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{p} x {l} = {p*l} cm²."}
        elif level == "sedang":
            a = random.choice([4, 6, 8, 10]); t = random.randint(3, 8)
            pil, idx = _buat_pilihan((a * t) // 2, " cm²")
            return {"tanya": f"Luas segitiga (alas={a} cm, tinggi={t} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"1/2 x {a} x {t} = {(a*t)//2} cm²."}
        s = random.randint(5, 11)
        pil, idx = _buat_pilihan(s, " cm")
        return {"tanya": f"Persegi memiliki luas {s*s} cm². Panjang sisinya adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{s} x {s} = {s*s}, jadi {s} cm."}

    elif slug == "mengenal-jenis-sudut":
        if level == "mudah":
            derajat = random.choice([40, 90, 130])
            jenis = "Sudut Siku-siku" if derajat == 90 else ("Sudut Lancip" if derajat < 90 else "Sudut Tumpul")
            pil, idx = _buat_pilihan_teks(jenis, "Sudut Lurus", "Sudut Lancip" if jenis != "Sudut Lancip" else "Sudut Tumpul")
            return {"tanya": f"Sudut {derajat}° termasuk jenis ...", "pilihan": pil, "jawaban": idx, "bahas": f"{jenis}."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(90, "°")
            return {"tanya": "Besar sudut jarum jam pada pukul 03.00 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "90°."}
        pil, idx = _buat_pilihan(180, "°")
        return {"tanya": "Jumlah seluruh sudut pada bangun segitiga adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "180°."}

    elif slug == "hubungan-antar-garis":
        if level == "mudah":
            pil, idx = _buat_pilihan_teks("Sejajar", "Berpotongan", "Berimpit")
            return {"tanya": "Dua rel kereta api yang berdampingan adalah contoh garis ...", "pilihan": pil, "jawaban": idx, "bahas": "Sejajar."}
        elif level == "sedang":
            pil, idx = _buat_pilihan_teks("Berpotongan tegak lurus", "Sejajar", "Berimpit")
            return {"tanya": "Tanda tambah (+) dibentuk oleh dua garis yang saling ...", "pilihan": pil, "jawaban": idx, "bahas": "Berpotongan tegak lurus."}
        pil, idx = _buat_pilihan_teks("Tidak akan pernah bertemu", "Bertemu di satu titik", "Membentuk sudut siku-siku")
        return {"tanya": "Jika dua garis sejajar diperpanjang terus, maka keduanya ...", "pilihan": pil, "jawaban": idx, "bahas": "Tidak akan pernah bertemu."}

    # ---- KELAS 5 ----
    elif slug == "operasi-pecahan-beda-penyebut":
        if level == "mudah":
            t_str, pemb, peny, bhs = random.choice([("1/2 + 1/4", 3, 4, "2/4 + 1/4 = 3/4"), ("2/3 - 1/3", 1, 3, "1/3")])
            pil, idx = _buat_pilihan(pemb, f"/{peny}")
            return {"tanya": f"Hasil dari {t_str} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": bhs}
        elif level == "sedang":
            t_str, pemb, peny, bhs = random.choice([("1/2 + 1/3", 5, 6, "3/6 + 2/6 = 5/6"), ("3/4 - 1/2", 1, 4, "3/4 - 2/4 = 1/4")])
            pil, idx = _buat_pilihan(pemb, f"/{peny}")
            return {"tanya": f"Hasil dari {t_str} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": bhs}
        pil, idx = _buat_pilihan_teks("7/8 kg", "2/6 kg", "5/8 kg")
        return {"tanya": "Ibu membeli 1/2 kg gula dan 3/8 kg tepung. Total berat belanjaan Ibu adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "4/8 + 3/8 = 7/8 kg."}

    elif slug == "perkalian-pembagian-pecahan":
        if level == "mudah":
            pil, idx = _buat_pilihan_teks("2/5", "6/8", "3/5")
            return {"tanya": "Hasil dari 2/3 x 3/5 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "6/15 = 2/5."}
        elif level == "sedang":
            pil, idx = _buat_pilihan_teks("3/2", "3/8", "2/3")
            return {"tanya": "Hasil dari 3/4 : 1/2 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "3/4 x 2/1 = 3/2."}
        pil, idx = _buat_pilihan(6, " potong")
        return {"tanya": "Pita 3 meter dipotong masing-masing 1/2 meter. Banyak potongan adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "3 : 1/2 = 6 potong."}

    elif slug == "desimal-dan-persen":
        if level == "mudah":
            pec, persen = random.choice([("1/2", 50), ("1/4", 25), ("3/4", 75), ("1/5", 20)])
            pil, idx = _buat_pilihan(persen, "%")
            return {"tanya": f"Bentuk persen dari {pec} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{persen}%."}
        elif level == "sedang":
            persen, des = random.choice([(25, "0,25"), (50, "0,5"), (75, "0,75"), (40, "0,4")])
            pil, idx = _buat_pilihan_teks(des, "0,05", "2,5")
            return {"tanya": f"Bentuk desimal dari {persen}% adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{des}."}
        harga = random.choice([40000, 60000, 80000]); pot = int(harga * 0.25)
        pil, idx = _buat_pilihan(harga - pot, " rupiah")
        return {"tanya": f"Harga baju Rp{harga} diskon 25%. Harga bayarnya adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{harga} - {pot} = Rp{harga-pot}."}

    elif slug == "kecepatan-jarak-waktu":
        if level == "mudah":
            k = random.choice([40, 50, 60]); w = random.randint(2, 4)
            pil, idx = _buat_pilihan(k * w, " km")
            return {"tanya": f"Kecepatan {k} km/jam selama {w} jam menempuh jarak ... km.", "pilihan": pil, "jawaban": idx, "bahas": f"{k*w} km."}
        elif level == "sedang":
            k = random.choice([50, 60, 70]); w = random.randint(2, 5)
            pil, idx = _buat_pilihan(k, " km/jam")
            return {"tanya": f"Bus menempuh {k*w} km dalam {w} jam. Kecepatannya adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{k*w} : {w} = {k} km/jam."}
        k = 60; w = random.randint(2, 4)
        pil, idx = _buat_pilihan(7 + w, ".00")
        return {"tanya": f"Berangkat pukul 07.00 jarak {k*w} km kecepatan {k} km/jam. Tiba pukul ...", "pilihan": pil, "jawaban": idx, "bahas": f"Pukul {7+w:02d}.00."}

    elif slug == "skala-dan-denah":
        if level == "mudah":
            jp = random.randint(2, 6)
            pil, idx = _buat_pilihan(jp * 2, " km")
            return {"tanya": f"Skala 1 : 200.000, jarak peta {jp} cm. Jarak sebenarnya = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{jp*2} km."}
        elif level == "sedang":
            js = random.choice([6, 9, 12, 15])
            pil, idx = _buat_pilihan(js // 3, " cm")
            return {"tanya": f"Jarak sebenarnya {js} km, skala 1 : 300.000. Jarak peta = ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"{js//3} cm."}
        pil, idx = _buat_pilihan_teks("1 : 500.000", "1 : 50.000", "1 : 5.000.000")
        return {"tanya": "Jarak sebenarnya 15 km digambar 3 cm di peta. Skalanya adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "1 : 500.000."}

    elif slug == "volume-kubus-dan-balok":
        if level == "mudah":
            s = random.randint(3, 6)
            pil, idx = _buat_pilihan(s ** 3, " cm³")
            return {"tanya": f"Volume kubus rusuk {s} cm adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{s**3} cm³."}
        elif level == "sedang":
            p, l, t = random.randint(5, 8), random.randint(3, 5), random.randint(2, 4)
            pil, idx = _buat_pilihan(p * l * t, " cm³")
            return {"tanya": f"Volume balok ({p} x {l} x {t} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{p*l*t} cm³."}
        p, l, t = 10, 5, random.randint(4, 8); vol = p * l * t
        pil, idx = _buat_pilihan(t, " cm")
        return {"tanya": f"Balok berisi {vol} cm³ air, p={p} cm, l={l} cm. Tingginya adalah ... cm.", "pilihan": pil, "jawaban": idx, "bahas": f"{vol} : 50 = {t} cm."}

    # ---- KELAS 6 ----
    elif slug == "operasi-bilangan-bulat":
        if level == "mudah":
            a, b = random.randint(-10, -2), random.randint(4, 15)
            pil, idx = _buat_pilihan(a + b, "", True)
            return {"tanya": f"({a}) + {b} = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a+b}."}
        elif level == "sedang":
            a, b = random.randint(-8, -3), random.randint(-7, -2)
            pil, idx = _buat_pilihan(a * b)
            return {"tanya": f"({a}) x ({b}) = ...", "pilihan": pil, "jawaban": idx, "bahas": f"{a*b}."}
        suhu, naik = random.randint(-6, -2), random.randint(8, 14)
        pil, idx = _buat_pilihan(suhu + naik, "°C")
        return {"tanya": f"Suhu awal {suhu}°C lalu naik {naik}°C. Suhu sekarang adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{suhu+naik}°C."}

    elif slug == "hitung-campuran-pecahan-desimal":
        if level == "mudah":
            pil, idx = _buat_pilihan_teks("0,75", "0,50", "1,25")
            return {"tanya": "0,5 + 1/4 = ...", "pilihan": pil, "jawaban": idx, "bahas": "0,75."}
        elif level == "sedang":
            pil, idx = _buat_pilihan_teks("1,0", "0,8", "1,2")
            return {"tanya": "0,75 + 25% = ...", "pilihan": pil, "jawaban": idx, "bahas": "1,0."}
        pil, idx = _buat_pilihan_teks("0,5", "0,25", "1,5")
        return {"tanya": "1,25 - 1/2 - 25% = ...", "pilihan": pil, "jawaban": idx, "bahas": "0,50."}

    elif slug == "luas-keliling-lingkaran":
        if level == "mudah":
            r = random.choice([7, 14])
            pil, idx = _buat_pilihan((2 * 22 * r) // 7, " cm")
            return {"tanya": f"Keliling lingkaran r={r} cm adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": f"{(2*22*r)//7} cm."}
        elif level == "sedang":
            r = random.choice([7, 14])
            pil, idx = _buat_pilihan((22 * r * r) // 7, " cm²")
            return {"tanya": f"Luas lingkaran r={r} cm adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": f"{(22*r*r)//7} cm²."}
        pil, idx = _buat_pilihan(154, " cm²")
        return {"tanya": "Meja bundar DIAMETER 14 cm. Luasnya adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": "r = 7 cm, Luas = 154 cm²."}

    elif slug == "bangun-ruang-gabungan":
        if level == "mudah":
            t = random.randint(4, 8)
            pil, idx = _buat_pilihan(154 * t, " cm³")
            return {"tanya": f"Volume tabung (luas alas 154 cm², tinggi {t} cm) adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{154*t} cm³."}
        elif level == "sedang":
            t = random.randint(6, 12)
            pil, idx = _buat_pilihan(154 * t, " cm³")
            return {"tanya": f"Volume tabung (r=7 cm, t={t} cm) adalah ... (π=22/7)", "pilihan": pil, "jawaban": idx, "bahas": f"{154*t} cm³."}
        pil, idx = _buat_pilihan(770, " cm³")
        return {"tanya": "Tabung (r=7 cm, t=10 cm) terisi air SETENGAH bagian. Volume air adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "1540 : 2 = 770 cm³."}

    elif slug == "koordinat-kartesius":
        x, y = random.randint(2, 8), random.randint(2, 8)
        if level == "mudah":
            pil, idx = _buat_pilihan(x)
            return {"tanya": f"Titik P({x}, {y}), nilai sumbu x adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{x}."}
        elif level == "sedang":
            pil, idx = _buat_pilihan(y)
            return {"tanya": f"Titik Q({x}, {y}), nilai sumbu y adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{y}."}
        geser = random.randint(2, 4)
        pil, idx = _buat_pilihan_teks(f"({x+geser}, {y})", f"({x}, {y+geser})", f"({x-geser}, {y})")
        return {"tanya": f"Titik A({x}, {y}) digeser ke KANAN {geser} satuan menjadi ...", "pilihan": pil, "jawaban": idx, "bahas": f"({x+geser}, {y})."}

    else:  # statistika-mean-median-modus
        if level == "mudah":
            pil, idx = _buat_pilihan(8)
            return {"tanya": "Modus dari data: 7, 8, 9, 8, 6, 8 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "8."}
        elif level == "sedang":
            rata = random.randint(7, 12); s = random.randint(1, 3)
            d = [rata - s, rata, rata + s]; random.shuffle(d)
            pil, idx = _buat_pilihan(rata)
            return {"tanya": f"Mean (rata-rata) dari {d[0]}, {d[1]}, dan {d[2]} adalah ...", "pilihan": pil, "jawaban": idx, "bahas": f"{rata}."}
        pil, idx = _buat_pilihan(8)
        return {"tanya": "Median dari data: 9, 6, 8, 10, 7 adalah ...", "pilihan": pil, "jawaban": idx, "bahas": "Urutkan: 6, 7, 8, 9, 10 -> tengahnya 8."}

def buat_soal_otomatis(kelas, slug=None, jumlah=6, level="mudah"):
    bab_kelas = [m["slug"] for m in MATERI if m["kelas"] == kelas]
    if slug:
        return [_generator_satu_soal(slug, level=level) for _ in range(jumlah)]
    urutan = ["mudah", "mudah", "sedang", "sedang", "sulit", "sulit"]
    return [_generator_satu_soal(bab_kelas[i % len(bab_kelas)], level=urutan[i % len(urutan)]) for i in range(jumlah)]

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
                return jsonify({"jawaban": hasil["candidates"][0]["content"]["parts"][0]["text"]})
        except Exception:
            pass

    cadangan = (
        f"Halo! Yuk kita bedah pelan-pelan soal: {soal_teks}\n\n"
        f"1️⃣ Perhatikan angka & kata kuncinya pada soal tersebut.\n"
        f"2️⃣ Langkah penyelesaian: {bahas_dasar or 'Kerjakan sesuai rumus pada ringkasan materi bab ini ya!'}\n"
        f"3️⃣ Kesimpulan: Jadi jawaban yang tepat adalah {jawaban_benar or 'sesuai perhitungan di atas'}. Tetap semangat!"
    )
    return jsonify({"jawaban": cadangan})

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": NAMA_BIMBEL, "short_name": "Bimbel IFGA", "start_url": "/", "display": "standalone",
        "background_color": "#e0f2fe", "theme_color": "#2563eb",
        "icons": [{"src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='22' fill='%232563eb'/><text y='.9em' x='12' font-size='75'>🧮</text></svg>", "sizes": "192x192", "type": "image/svg+xml"}]
    })

# ================= TAMPILAN UTAMA =================
TAMPILAN_UTAMA = """<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#2563eb">
  <link rel="manifest" href="/manifest.json">
  <title>{{ nama_bimbel }}</title>
  <link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@600;700&family=Nunito:wght@600;700;800&display=swap" rel="stylesheet">
  <style>
    :root { --bg:#e0f2fe; --putih:#fff; --biru:#2563eb; --biru-tua:#1d4ed8; --hijau:#22c55e; --merah:#ef4444; --teks:#1e293b; --abu:#64748b; }
    * { box-sizing: border-box; }
    body { margin:0; color:var(--teks); font-family:"Nunito",sans-serif; font-size:17px; line-height:1.65; background:var(--bg) radial-gradient(#bae6fd 2px, transparent 2px); background-size:28px 28px; }
    h1, h2, h3, .logo, .pilih-kelas, .tombol-3d, .badge-tier { font-family:"Fredoka","Nunito",sans-serif; }
    .atas { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; padding:12px 22px; background:linear-gradient(135deg,#2563eb,#3b82f6); box-shadow:0 4px 0 #1d4ed8; position:sticky; top:0; z-index:10; }
    .logo { color:#fff; font-size:1.3rem; text-decoration:none; }
    .nav-kanan { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    .pill-nav { padding:6px 13px; border-radius:999px; text-decoration:none; font-size:0.88rem; font-family:"Fredoka",sans-serif; display:inline-flex; align-items:center; gap:5px; }
    .avatar-wrap { position:relative; display:inline-flex; align-items:center; justify-content:center; font-size:1.8rem; background:#fff; border-radius:50%; width:48px; height:48px; border:2px solid #cbd5e1; }
    .avatar-topi { position:absolute; top:-16px; font-size:1.3rem; }
    .tier-1 { border:3px solid #eab308; background:#fefce8; } .tier-2 { border:3px solid #a855f7; background:#faf5ff; } .tier-3 { border:3px solid #3b82f6; background:#eff6ff; }
    .badge-tier { font-size:0.72rem; padding:2px 8px; border-radius:999px; }
    .wadah { max-width:860px; margin:26px auto; padding:26px 30px; background:var(--putih); border-radius:24px; border:3px solid #bfdbfe; box-shadow:0 10px 0 #bfdbfe; }
    h1 { color:var(--biru); font-size:1.85rem; line-height:1.2; margin:0.2em 0 0.5em; }
    h2 { font-size:1.3rem; margin-top:1.4em; } h3 { color:#1d4ed8; font-size:1.1rem; }
    a { color:var(--biru); font-weight:700; }
    .grid-kelas { display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:16px; margin-top:16px; }
    .pilih-kelas { padding:20px 14px; text-align:center; font-size:1.3rem; border-radius:20px; text-decoration:none; color:#fff; display:flex; flex-direction:column; align-items:center; gap:6px; transition:transform 0.12s; }
    .pilih-kelas:hover { transform:translateY(-4px); }
    .k1 { background:#f43f5e; box-shadow:0 6px 0 #be123c; } .k2 { background:#f97316; box-shadow:0 6px 0 #c2410c; } .k3 { background:#eab308; box-shadow:0 6px 0 #a16207; color:#1e293b; }
    .k4 { background:#22c55e; box-shadow:0 6px 0 #15803d; } .k5 { background:#06b6d4; box-shadow:0 6px 0 #0e7490; } .k6 { background:#8b5cf6; box-shadow:0 6px 0 #5b21b6; }
    .daftar-materi { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:14px 18px; margin:10px 0; background:#f8fafc; border:2px solid #cbd5e1; border-radius:16px; text-decoration:none; color:var(--teks); box-shadow:0 4px 0 #cbd5e1; }
    .daftar-materi:hover { background:#eff6ff; border-color:var(--biru); }
    .badge-nilai { background:#fef08a; border:2px solid #eab308; padding:3px 12px; border-radius:999px; font-size:0.85rem; font-weight:800; }
    .progress-track { width:100%; height:14px; background:#e2e8f0; border-radius:999px; overflow:hidden; margin-top:6px; }
    .progress-fill { height:100%; background:linear-gradient(90deg,#22c55e,#3b82f6); border-radius:999px; }
    .contoh { background:#ecfdf5; border:2px dashed #10b981; color:#065f46; display:inline-block; padding:8px 16px; border-radius:12px; font-weight:800; margin:6px 0; }
    .tombol-3d { display:inline-block; background:var(--biru); color:#fff; padding:11px 22px; border:none; border-radius:16px; font-size:1.02rem; text-decoration:none; cursor:pointer; box-shadow:0 5px 0 var(--biru-tua); }
    .tombol-3d:active { transform:translateY(3px); box-shadow:none; }
    .tombol-hijau { background:var(--hijau); box-shadow:0 5px 0 #15803d; }
    .tombol-kuning { background:#eab308; color:#1e293b; box-shadow:0 5px 0 #a16207; }
    .tombol-merah { background:var(--merah); box-shadow:0 5px 0 #b91c1c; }
    .nilai-box { background:linear-gradient(135deg,#fef9c3,#fef08a); padding:18px; border-radius:18px; margin:18px 0; border:3px solid #eab308; text-align:center; }
    .soal { background:#f8fafc; border:3px solid #e2e8f0; border-radius:18px; padding:18px 22px; margin:18px 0; }
    .soal legend { font-family:"Fredoka",sans-serif; color:#fff; background:var(--biru); padding:4px 14px; border-radius:999px; }
    .soal.benar { border-color:var(--hijau); background:#f0fdf4; } .soal.salah { border-color:var(--merah); background:#fef2f2; }
    .opsi { display:flex; align-items:center; gap:10px; padding:10px 14px; margin:8px 0; background:#fff; border:2px solid #cbd5e1; border-radius:12px; cursor:pointer; font-weight:700; }
    .bahas { margin-top:12px; padding:12px; background:#fff; border-radius:12px; border-left:5px solid var(--biru); font-size:0.95rem; }
    .kotak-ai { margin-top:10px; padding:14px; background:#eff6ff; border:2px solid #93c5fd; border-radius:12px; font-size:0.95rem; white-space:pre-line; display:none; }
    .input-box { width:100%; padding:11px 13px; border:2px solid #cbd5e1; border-radius:12px; font:inherit; margin:6px 0 14px; }
    .tabel-lb { width:100%; border-collapse:collapse; margin-top:14px; }
    .tabel-lb th, .tabel-lb td { padding:10px 8px; text-align:left; border-bottom:2px solid #e2e8f0; }
    .stat-card { background:#f8fafc; border:2px solid #cbd5e1; border-radius:16px; padding:14px; text-align:center; }
    footer { text-align:center; padding:24px; color:var(--abu); font-size:0.9rem; font-weight:700; }
  </style>
</head>
<body>
  <header class="atas">
    <a class="logo" href="/">🧮 {{ nama_bimbel }}</a>
    <div class="nav-kanan">
      {% if user %}
        <a class="pill-nav" style="background:#38bdf8; color:#0f172a; box-shadow:0 3px 0 #0284c7;" href="/tabel">📊 Tabel × ÷</a>
        <a class="pill-nav" style="background:#facc15; color:#1e293b; box-shadow:0 3px 0 #ca8a04;" href="/leaderboard">🏆 Juara</a>
        <a class="pill-nav" style="background:#a855f7; color:#fff; box-shadow:0 3px 0 #7e22ce;" href="/minigame">🎮 Mini-Game</a>
        <a class="pill-nav" style="background:#fff; color:#1e293b; border:2px solid #93c5fd;" href="/profil">
          <span>{{ user.hadiah.ikon if user.hadiah else '' }}{{ user.avatar }} <strong>{{ user.nama }}</strong> • 🔥{{ user.streak }}h • {{ user.poin }} pts</span>
        </a>
      {% else %}
        <a class="pill-nav" style="background:#22c55e; color:#fff; box-shadow:0 3px 0 #15803d;" href="/login">🔑 Masuk / Daftar</a>
      {% endif %}
    </div>
  </header>
  <main class="wadah">{{ konten|safe }}</main>
  <footer>✨ {{ nama_bimbel }} — <a href="/guru" style="color:#64748b; font-size:0.85rem;">Ruang Ibu Guru</a> ✨</footer>
  <script>
    function bunyiEfek(jenis) {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator(), gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = jenis === 'benar' ? 'sine' : 'triangle';
        osc.frequency.setValueAtTime(jenis === 'benar' ? 587 : 220, ctx.currentTime);
        osc.frequency.setValueAtTime(jenis === 'benar' ? 880 : 160, ctx.currentTime + 0.1);
        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
        osc.start(); osc.stop(ctx.currentTime + 0.3);
      } catch(e) {}
    }
  </script>
</body>
</html>"""

def render_halaman(konten_html, **kwargs):
    user = get_user_aktif()
    isi = render_template_string(konten_html, user=user, whatsapp=WHATSAPP, **kwargs)
    return render_template_string(TAMPILAN_UTAMA, nama_bimbel=NAMA_BIMBEL, whatsapp=WHATSAPP, user=user, konten=isi)

@app.before_request
def wajib_login():
    if request.endpoint in ("login", "guru", "manifest", "static"):
        return
    uid = session.get("user_id")
    if not uid:
        return redirect(url_for("login"))
    with get_db() as db:
        u = db.execute("SELECT status FROM users WHERE id = ?", (uid,)).fetchone()
    if not u or u["status"] != "aktif":
        session.pop("user_id", None)
        return redirect(url_for("login"))

# ================= TABEL PERKALIAN & PEMBAGIAN INTERAKTIF =================
@app.route("/tabel")
def halaman_tabel():
    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    <h1>📊 Tabel Perkalian &amp; Pembagian (1 – 10)</h1>
    <p>Klik salah satu angka di bawah untuk menyorot hafalan perkalian atau pembagian angka tersebut!</p>

    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px;">
      <button type="button" id="btn-mode-kali" class="tombol-3d" style="padding:8px 16px; font-size:0.95rem;" onclick="setMode('kali')">✖️ Tabel Perkalian</button>
      <button type="button" id="btn-mode-bagi" class="tombol-3d" style="padding:8px 16px; font-size:0.95rem; background:#64748b; box-shadow:0 4px 0 #475569;" onclick="setMode('bagi')">➗ Tabel Pembagian</button>
    </div>

    <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px;">
      <button type="button" class="pill-nav" style="background:#facc15; border:2px solid #ca8a04; cursor:pointer;" onclick="setPilih(0)">Semua</button>
      {% for n in range(1, 11) %}
        <button type="button" class="pill-nav" style="background:#e2e8f0; border:2px solid #94a3b8; cursor:pointer;" onclick="setPilih({{ n }})">Angka {{ n }}</button>
      {% endfor %}
    </div>

    <div id="info-sel" style="background:#fef9c3; border:2px solid #eab308; padding:10px 16px; border-radius:12px; font-weight:800; margin-bottom:14px; text-align:center;">
      💡 Ketuk salah satu kotak di tabel untuk melihat cara bacanya!
    </div>

    <div style="overflow-x:auto;">
      <table id="tabel-mat" style="width:100%; border-collapse:collapse; text-align:center; font-size:0.95rem;"></table>
    </div>

    <script>
      let mode = 'kali', pilih = 0;
      function setMode(m) {
        mode = m;
        document.getElementById('btn-mode-kali').style.background = m === 'kali' ? '#2563eb' : '#64748b';
        document.getElementById('btn-mode-bagi').style.background = m === 'bagi' ? '#2563eb' : '#64748b';
        gambarTabel();
      }
      function setPilih(n) { pilih = n; gambarTabel(); }
      function gambarTabel() {
        let html = '<thead><tr style="background:#1e293b; color:#facc15;"><th style="padding:8px; border:1px solid #cbd5e1;">' + (mode === 'kali' ? '×' : '÷') + '</th>';
        for (let c = 1; c <= 10; c++) html += `<th style="padding:8px; border:1px solid #cbd5e1;">${c}</th>`;
        html += '</tr></thead><tbody>';
        for (let r = 1; r <= 10; r++) {
          html += `<tr><th style="background:#eff6ff; padding:8px; border:1px solid #cbd5e1;">${r}</th>`;
          for (let c = 1; c <= 10; c++) {
            const sorot = (pilih > 0 && (r === pilih || c === pilih));
            const bg = sorot ? '#fef08a' : '#fff';
            const fw = sorot ? '800' : '600';
            if (mode === 'kali') {
              const hasil = r * c;
              html += `<td onclick="document.getElementById('info-sel').innerText='✨ ${r} × ${c} = ${hasil}'" style="padding:8px; border:1px solid #cbd5e1; background:${bg}; font-weight:${fw}; cursor:pointer;">${hasil}</td>`;
            } else {
              const dibagi = r * c;
              html += `<td onclick="document.getElementById('info-sel').innerText='✨ ${dibagi} ÷ ${r} = ${c}'" style="padding:8px; border:1px solid #cbd5e1; background:${bg}; font-weight:${fw}; cursor:pointer;">${dibagi}:${r}=<strong>${c}</strong></td>`;
            }
          }
          html += '</tr>';
        }
        html += '</tbody>';
        document.getElementById('tabel-mat').innerHTML = html;
      }
      gambarTabel();
    </script>"""
    return render_halaman(html)

# ================= LOGIN, DAFTAR, & PROFIL =================
@app.route("/login", methods=["GET", "POST"])
def login():
    pesan_err = pesan_sukses = None
    if request.method == "POST":
        aksi = request.form.get("aksi")
        nama = request.form.get("nama", "").strip()
        pin = request.form.get("pin", "").strip()
        avatar = request.form.get("avatar", "🐱")
        if not nama or len(pin) != 4 or not pin.isdigit():
            pesan_err = "Nama wajib diisi dan PIN harus 4 angka."
        else:
            with get_db() as db:
                if aksi == "daftar":
                    if db.execute("SELECT id FROM users WHERE LOWER(nama) = LOWER(?)", (nama,)).fetchone():
                        pesan_err = "Nama sudah terdaftar. Silakan login di kotak sebelah kiri."
                    else:
                        db.execute("INSERT INTO users (nama, pin, avatar, poin, soal_benar, soal_salah, status) VALUES (?, ?, ?, 0, 0, 0, 'pending')", (nama, pin, avatar))
                        pesan_sukses = f"Pendaftaran '{nama}' berhasil! Minta Ibu Guru menyetujui akunmu di Ruang Guru, lalu masuk kembali."
                else:
                    row = db.execute("SELECT id, status FROM users WHERE LOWER(nama) = LOWER(?) AND pin = ?", (nama, pin)).fetchone()
                    if not row:
                        pesan_err = "Nama atau PIN 4 angka salah."
                    elif row["status"] != "aktif":
                        pesan_err = "Akunmu masih MENUNGGU VERIFIKASI dari Ibu Guru."
                    else:
                        session.permanent = True
                        session["user_id"] = row["id"]
                        return redirect(url_for("beranda"))

    html = """
    <h1>🔒 Portal Eksklusif Murid Bimbel</h1>
    <p>Aplikasi belajar khusus murid terdaftar di <strong>{{ nama_bimbel }}</strong>.</p>
    {% if pesan_sukses %}
      <div style="background:#dcfce7; color:#166534; padding:16px; border-radius:14px; border:2px solid #22c55e; font-weight:800; margin-bottom:18px;">
        🎉 {{ pesan_sukses }}<br><br>
        <a class="tombol-3d tombol-hijau" style="padding:8px 16px; font-size:0.95rem;" href="https://wa.me/{{ whatsapp }}?text=Halo%20Bu,%20saya%20sudah%20daftar%20akun%20di%20aplikasi%20Bimbel%20Matematika.%20Mohon%20diverifikasi%20ya!" target="_blank">💬 Konfirmasi ke WA Ibu Guru</a>
      </div>
    {% endif %}
    {% if pesan_err %}
      <div style="background:#fee2e2; color:#991b1b; padding:14px; border-radius:12px; border:2px solid #ef4444; font-weight:800; margin-bottom:16px;">⚠️ {{ pesan_err }}</div>
    {% endif %}
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px;">
      <form method="post" style="background:#f8fafc; padding:20px; border-radius:18px; border:2px solid #cbd5e1;">
        <h2 style="margin-top:0;">👋 Masuk (Akun Terverifikasi)</h2>
        <input type="hidden" name="aksi" value="masuk">
        <label><strong>Nama Lengkap:</strong></label>
        <input class="input-box" type="text" name="nama" placeholder="Contoh: Budi Santoso" required>
        <label><strong>PIN Rahasia (4 Angka):</strong></label>
        <input class="input-box" type="password" name="pin" maxlength="4" pattern="[0-9]{4}" placeholder="****" required>
        <button class="tombol-3d" type="submit">Masuk &amp; Simpan Akun</button>
      </form>
      <form method="post" style="background:#eff6ff; padding:20px; border-radius:18px; border:2px solid #93c5fd;">
        <h2 style="margin-top:0;">📝 Daftar Murid Baru</h2>
        <input type="hidden" name="aksi" value="daftar">
        <label><strong>Nama Lengkap Murid:</strong></label>
        <input class="input-box" type="text" name="nama" placeholder="Tulis nama aslimu" required>
        <label><strong>Buat PIN 4 Angka:</strong></label>
        <input class="input-box" type="text" name="pin" maxlength="4" pattern="[0-9]{4}" placeholder="Contoh: 1234" required>
        <label><strong>Pilih Avatar:</strong></label>
        <div style="display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 16px; font-size:1.5rem;">
          {% for av in ['🐱', '🐶', '🐼', '🦊', '🦁', '🐰', '🐯', '🐨', '🐸', '🦄'] %}
            <label style="cursor:pointer;"><input type="radio" name="avatar" value="{{ av }}" {% if loop.first %}checked{% endif %}> {{ av }}</label>
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
    pesan_profil = err_profil = None
    if request.method == "POST":
        aksi = request.form.get("aksi")
        if aksi == "ganti_avatar":
            with get_db() as db:
                db.execute("UPDATE users SET avatar = ? WHERE id = ?", (request.form.get("avatar_baru", "🐱"), user["id"]))
            pesan_profil = "Avatar berhasil diganti!"
            user = get_user_aktif()
        elif aksi == "ganti_pin":
            lama, baru = request.form.get("pin_lama", "").strip(), request.form.get("pin_baru", "").strip()
            with get_db() as db:
                cek = db.execute("SELECT pin FROM users WHERE id = ?", (user["id"],)).fetchone()
                if not cek or cek["pin"] != lama:
                    err_profil = "PIN lama tidak sesuai!"
                elif len(baru) != 4 or not baru.isdigit():
                    err_profil = "PIN baru harus 4 angka!"
                else:
                    db.execute("UPDATE users SET pin = ? WHERE id = ?", (baru, user["id"]))
                    pesan_profil = "PIN berhasil diperbarui!"

    with get_db() as db:
        riwayat = {r["kode_bab"]: r["nilai"] for r in db.execute("SELECT kode_bab, nilai FROM nilai_bab WHERE user_id = ?", (user["id"],)).fetchall()}

    progress_kelas = []
    total_selesai = 0
    for k in range(1, 7):
        bab_k = [m for m in MATERI if m["kelas"] == k]
        selesai = sum(1 for m in bab_k if f"{k}_{m['slug']}" in riwayat)
        total_selesai += selesai
        progress_kelas.append({"kelas": k, "selesai": selesai, "total": len(bab_k), "persen": round((selesai / len(bab_k)) * 100), "tryout": riwayat.get(f"{k}_tryout")})

    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    {% if pesan_profil %}<div style="background:#dcfce7; color:#166534; padding:12px; border-radius:12px; font-weight:800; margin-bottom:14px;">✅ {{ pesan_profil }}</div>{% endif %}
    {% if err_profil %}<div style="background:#fee2e2; color:#991b1b; padding:12px; border-radius:12px; font-weight:800; margin-bottom:14px;">⚠️ {{ err_profil }}</div>{% endif %}
    <div style="text-align:center; padding:20px; background:#f8fafc; border-radius:22px; border:2px solid #cbd5e1;">
      <div class="avatar-wrap {% if user.rank <= 3 %}tier-{{ user.rank }}{% endif %}" style="width:90px; height:90px; font-size:3.4rem; margin:0 auto;">
        {% if user.hadiah %}<span class="avatar-topi" style="top:-26px; font-size:2.2rem;">{{ user.hadiah.ikon }}</span>{% endif %}
        <span>{{ user.avatar }}</span>
      </div>
      <h1 style="margin:12px 0 4px;">{{ user.nama }}</h1>
      <p style="margin:0;">Juara <strong>#{{ user.rank }}</strong> | Skor: <strong style="color:#2563eb;">{{ user.poin }} pts</strong> | Streak: <strong style="color:#ea580c;">🔥 {{ user.streak }} Hari</strong></p>
    </div>

    <h2>📊 Statistik Soal</h2>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:12px;">
      <div class="stat-card"><div style="font-size:1.5rem; font-weight:800; color:#2563eb;">{{ user.total_soal }}</div><div>Total Soal</div></div>
      <div class="stat-card" style="background:#f0fdf4;"><div style="font-size:1.5rem; font-weight:800; color:#16a34a;">✅ {{ user.benar }}</div><div>Benar</div></div>
      <div class="stat-card" style="background:#fef2f2;"><div style="font-size:1.5rem; font-weight:800; color:#dc2626;">❌ {{ user.salah }}</div><div>Salah</div></div>
      <div class="stat-card" style="background:#fefce8;"><div style="font-size:1.5rem; font-weight:800; color:#ca8a04;">🎯 {{ user.akurasi }}%</div><div>Ketelitian</div></div>
    </div>

    <h2>📈 Progress Belajar ({{ total_selesai }} / {{ total_bab }} Bab Selesai)</h2>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:14px;">
      {% for pk in progress_kelas %}
        <div style="background:#fff; border:2px solid #e2e8f0; border-radius:16px; padding:14px;">
          <div style="display:flex; justify-content:space-between; font-weight:800;">
            <a href="/kelas/{{ pk.kelas }}" style="text-decoration:none;">📘 Kelas {{ pk.kelas }}</a>
            <span>{{ pk.selesai }}/{{ pk.total }} Bab ({{ pk.persen }}%)</span>
          </div>
          <div class="progress-track"><div class="progress-fill" style="width:{{ pk.persen }}%;"></div></div>
          <div style="font-size:0.85rem; color:#64748b; margin-top:6px;">Tryout: <strong>{{ ('Nilai ' ~ pk.tryout) if pk.tryout is not none else 'Belum dicoba' }}</strong></div>
        </div>
      {% endfor %}
    </div>

    <h2>⚙️ Pengaturan Akun</h2>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:16px;">
      <form method="post" style="background:#f8fafc; padding:16px; border-radius:18px; border:2px solid #cbd5e1;">
        <h3 style="margin-top:0;">🎨 Ganti Avatar</h3>
        <input type="hidden" name="aksi" value="ganti_avatar">
        <div style="display:flex; gap:10px; flex-wrap:wrap; font-size:1.5rem; margin-bottom:12px;">
          {% for av in ['🐱', '🐶', '🐼', '🦊', '🦁', '🐰', '🐯', '🐨', '🐸', '🦄'] %}
            <label style="cursor:pointer;"><input type="radio" name="avatar_baru" value="{{ av }}" {% if user.avatar == av %}checked{% endif %}> {{ av }}</label>
          {% endfor %}
        </div>
        <button class="tombol-3d" style="padding:8px 16px; font-size:0.9rem;" type="submit">Simpan Avatar</button>
      </form>
      <form method="post" style="background:#f8fafc; padding:16px; border-radius:18px; border:2px solid #cbd5e1;">
        <h3 style="margin-top:0;">🔒 Ubah PIN</h3>
        <input type="hidden" name="aksi" value="ganti_pin">
        <input class="input-box" type="password" name="pin_lama" maxlength="4" pattern="[0-9]{4}" placeholder="PIN Lama" required>
        <input class="input-box" type="text" name="pin_baru" maxlength="4" pattern="[0-9]{4}" placeholder="PIN Baru" required>
        <button class="tombol-3d tombol-hijau" style="padding:8px 16px; font-size:0.9rem;" type="submit">Simpan PIN</button>
      </form>
    </div>
    <div style="margin-top:20px; text-align:right;"><a class="tombol-3d tombol-merah" style="font-size:0.9rem;" href="/logout">🚪 Keluar Akun</a></div>"""
    return render_halaman(html, progress_kelas=progress_kelas, total_selesai=total_selesai, total_bab=len(MATERI), pesan_profil=pesan_profil, err_profil=err_profil)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))

@app.route("/leaderboard")
def leaderboard():
    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    <h1>🏆 Papan Peringkat &amp; Hadiah Juara</h1>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:10px; margin:14px 0;">
      {% for r, h in hadiah_list.items() %}
        <div style="background:{{ h.bg }}; border:{{ h.border }}; border-radius:14px; padding:10px; text-align:center;">
          <span class="badge-tier" style="background:{{ h.warna }}; color:#fff;">#{{ r }} {{ h.tier }}</span>
          <div style="font-size:1.7rem;">{{ h.ikon }}</div><strong style="font-size:0.85rem;">{{ h.nama }}</strong>
        </div>
      {% endfor %}
    </div>
    <div style="overflow-x:auto;">
      <table class="tabel-lb">
        <thead><tr><th>Rank</th><th>Murid</th><th>Item Juara</th><th>Streak &amp; Akurasi</th><th>Skor</th></tr></thead>
        <tbody>
          {% for u in lb %}
            <tr style="background:{{ u.hadiah.bg if u.hadiah else '#fff' }};">
              <td><strong>#{{ u.rank }}</strong></td>
              <td style="display:flex; align-items:center; gap:10px;">
                <div class="avatar-wrap {% if u.rank <= 3 %}tier-{{ u.rank }}{% endif %}">
                  {% if u.hadiah %}<span class="avatar-topi">{{ u.hadiah.ikon }}</span>{% endif %}<span>{{ u.avatar }}</span>
                </div>
                <strong>{{ u.nama }}</strong>
              </td>
              <td>{% if u.hadiah %}<strong>{{ u.hadiah.ikon }} {{ u.hadiah.nama }}</strong>{% else %}-{% endif %}</td>
              <td>🔥 {{ u.streak }}h | ✅{{ u.benar }} ❌{{ u.salah }}</td>
              <td><strong style="color:#2563eb;">{{ u.poin }}</strong></td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>"""
    return render_halaman(html, lb=ambil_leaderboard(), hadiah_list=HADIAH_PERINGKAT)

# ================= BERANDA, KELAS, MATERI, & LATIHAN =================
@app.route("/")
def beranda():
    user = get_user_aktif()
    with get_db() as db:
        daftar_pr = db.execute("SELECT * FROM tugas_pr ORDER BY id DESC").fetchall()
        sudah_selesai = {r["kode_bab"] for r in db.execute("SELECT kode_bab FROM nilai_bab WHERE user_id = ?", (user["id"],)).fetchall()}
    ikon = {1: ("🐣", "Berhitung & Nilai Tempat"), 2: ("🚀", "Susun, Ratusan & Ribuan"), 3: ("🦁", "Perkalian Susun & Keliling"),
            4: ("🦉", "KPK/FPB & Luas"), 5: ("🐬", "Pecahan & Volume"), 6: ("🏆", "Bulat & Lingkaran")}
    html = """
    <h1>Halo, {{ user.nama }}! Ayo Belajar Matematika! 🌟</h1>
    <p>Api Semangat: <strong style="color:#ea580c;">🔥 {{ user.streak }} Hari Berturut-turut</strong> (latihan hari ini berhadiah bonus <strong>+15 poin</strong>!).</p>
    {% if daftar_pr %}
      <div style="background:#fefce8; border:3px solid #eab308; border-radius:18px; padding:16px; margin:16px 0;">
        <h3 style="margin-top:0; color:#854d0e;">📋 Tugas / PR dari Ibu Guru:</h3>
        {% for pr in daftar_pr %}
          {% set kode = pr.kelas ~ '_' ~ pr.slug %}
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; padding:8px 0; border-bottom:1px dashed #fde047;">
            <div><strong>Kelas {{ pr.kelas }} — {{ pr.judul_bab }}</strong>{% if pr.catatan %}<div style="font-size:0.88rem; color:#713f12;">Catatan: "{{ pr.catatan }}"</div>{% endif %}</div>
            {% if kode in sudah_selesai %}
              <span style="background:#22c55e; color:#fff; padding:4px 12px; border-radius:999px; font-size:0.85rem; font-weight:800;">✅ Selesai</span>
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
          <span style="font-size:2.1rem;">{{ ikon[k][0] }}</span><span>Kelas {{ k }}</span>
          <small style="font-family:'Nunito'; font-size:0.85rem;">{{ ikon[k][1] }}</small>
        </a>
      {% endfor %}
    </div>"""
    return render_halaman(html, ikon=ikon, daftar_pr=daftar_pr, sudah_selesai=sudah_selesai)

@app.route("/kelas/<int:kelas>")
def halaman_kelas(kelas):
    if kelas not in range(1, 7): abort(404)
    materi = [m for m in MATERI if m["kelas"] == kelas]
    user = get_user_aktif()
    with get_db() as db:
        riwayat = {r["kode_bab"]: r["nilai"] for r in db.execute("SELECT kode_bab, nilai FROM nilai_bab WHERE user_id = ?", (user["id"],)).fetchall()} if user else {}
    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    <h1>📘 Matematika Kelas {{ kelas }}</h1>
    {% for m in materi %}
      {% set skor = riwayat.get(kelas ~ '_' ~ m.slug) %}
      <a class="daftar-materi" href="/kelas/{{ kelas }}/{{ m.slug }}">
        <span>{{ m.judul }}</span>
        {% if skor is not none %}<span class="badge-nilai">⭐ {{ skor }}</span>{% else %}<span style="color:#94a3b8; font-size:0.85rem;">Pelajari &rarr;</span>{% endif %}
      </a>
    {% endfor %}
    <h2>⏱️ Tryout Waktu Kelas {{ kelas }} (10 Menit)</h2>
    <a class="tombol-3d tombol-hijau" href="/kelas/{{ kelas }}/latihan">⏱️ Mulai Tryout Waktu Kelas {{ kelas }}</a>"""
    return render_halaman(html, kelas=kelas, materi=materi, riwayat=riwayat)

@app.route("/kelas/<int:kelas>/<slug>")
def halaman_materi(kelas, slug):
    m = next((x for x in MATERI if x["kelas"] == kelas and x["slug"] == slug), None)
    if not m: abort(404)
    html = """
    <p><a href="/kelas/{{ m.kelas }}">&larr; Kembali ke Kelas {{ m.kelas }}</a></p>
    <h1>{{ m.judul }}</h1>
    <div style="background:#f8fafc; padding:20px; border-radius:18px; border:2px solid #cbd5e1;">{{ m.isi|safe }}</div>
    <hr style="margin:22px 0; border:0; border-top:3px dashed #cbd5e1;">
    <h2>🎯 Pilih Tingkat Kesulitan Latihan:</h2>
    <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:12px;">
      <a class="tombol-3d tombol-hijau" href="/kelas/{{ m.kelas }}/{{ m.slug }}/latihan?level=mudah">🟢 Mudah (+10 pts)</a>
      <a class="tombol-3d tombol-kuning" href="/kelas/{{ m.kelas }}/{{ m.slug }}/latihan?level=sedang">🟡 Sedang (+15 pts)</a>
      <a class="tombol-3d tombol-merah" href="/kelas/{{ m.kelas }}/{{ m.slug }}/latihan?level=sulit">🔴 Sulit (+20 pts)</a>
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
    label_lv = {"mudah": "🟢 Level Mudah", "sedang": "🟡 Level Sedang", "sulit": "🔴 Level Sulit"}[level]
    judul = f"⏱️ Tryout Waktu Kelas {kelas}" if is_tryout else f"✏️ Latihan {next(m['judul'] for m in MATERI if m['kelas']==kelas and m['slug']==slug)} ({label_lv})"

    kunci = f"soal_{kelas}_{slug or 'tryout'}_{level}"
    if request.method == "GET" or kunci not in session:
        soal = buat_soal_otomatis(kelas, slug=slug, jumlah=6, level=level)
        session[kunci] = soal
        session[f"kumpul_{kunci}"] = False
        hasil = nilai = pesan = bintang = None
    else:
        soal = session[kunci]
        hasil = [{"dipilih": int(request.form.get(f"soal{i}", "")) if request.form.get(f"soal{i}", "").isdigit() else None,
                  "benar": (int(request.form.get(f"soal{i}", "")) if request.form.get(f"soal{i}", "").isdigit() else None) == s["jawaban"]}
                 for i, s in enumerate(soal)]
        skor = sum(h["benar"] for h in hasil)
        salah = len(soal) - skor
        nilai = round(skor / len(soal) * 100)
        sisa_detik = max(0, min(600, int(request.form.get("sisa_detik", 0) or 0)))
        user = get_user_aktif()

        if user and not session.get(f"kumpul_{kunci}", False):
            session[f"kumpul_{kunci}"] = True
            bonus_streak = perbarui_streak_harian(user["id"])
            poin_lv = 15 if is_tryout else {"mudah": 10, "sedang": 15, "sulit": 20}[level]
            bonus_w = (sisa_detik // 20) if (is_tryout and skor > 0) else 0
            ubah = (skor * poin_lv) - (salah * 2) + bonus_w
            with get_db() as db:
                db.execute("UPDATE users SET poin = MAX(0, poin + ?), soal_benar = soal_benar + ?, soal_salah = soal_salah + ? WHERE id = ?", (ubah, skor, salah, user["id"]))
                db.execute("INSERT INTO nilai_bab (user_id, kode_bab, nilai) VALUES (?, ?, ?) ON CONFLICT(user_id, kode_bab) DO UPDATE SET nilai = MAX(nilai, excluded.nilai)", (user["id"], f"{kelas}_{slug or 'tryout'}", nilai))
        else:
            ubah = bonus_streak = 0

        bintang = "⭐⭐⭐" if nilai == 100 else ("⭐⭐" if nilai >= 70 else "⭐")
        pesan = f"Benar {skor}, Salah {salah} ({'+' if ubah >= 0 else ''}{ubah} Poin)" + (f" + 🔥 Bonus Streak (+{bonus_streak} pts)!" if bonus_streak else "")

    url_ulang = f"/kelas/{kelas}/{slug}/latihan?level={level}" if slug else f"/kelas/{kelas}/latihan"
    url_kembali = f"/kelas/{kelas}/{slug}" if slug else f"/kelas/{kelas}"
    lv_next = "sedang" if level == "mudah" else ("sulit" if level == "sedang" else None)

    html = """
    <p><a href="{{ url_kembali }}">&larr; Kembali</a></p>
    <h1>{{ judul }}</h1>
    {% if not is_tryout %}
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px;">
        <a class="pill-nav" style="background:{{ '#22c55e' if level=='mudah' else '#e2e8f0' }}; color:{{ '#fff' if level=='mudah' else '#1e293b' }};" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level=mudah">🟢 Mudah</a>
        <a class="pill-nav" style="background:{{ '#eab308' if level=='sedang' else '#e2e8f0' }}; color:#1e293b;" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level=sedang">🟡 Sedang</a>
        <a class="pill-nav" style="background:{{ '#ef4444' if level=='sulit' else '#e2e8f0' }}; color:{{ '#fff' if level=='sulit' else '#1e293b' }};" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level=sulit">🔴 Sulit</a>
      </div>
    {% endif %}
    {% if is_tryout and not hasil %}
      <div style="background:#1e293b; color:#fff; padding:12px 18px; border-radius:14px; display:flex; justify-content:space-between; font-weight:800;">
        <span>⏱️ Sisa Waktu Tryout:</span><span id="tampilan-timer" style="color:#facc15; font-size:1.3rem;">10:00</span>
      </div>
    {% endif %}
    {% if hasil %}
      <div class="nilai-box"><div style="font-size:2rem;">{{ bintang }}</div><strong style="font-size:1.4rem;">Nilai: {{ nilai }}</strong><br><span>{{ pesan }}</span></div>
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
              <input type="radio" name="soal{{ i }}" value="{{ loop.index0 }}" {% if not is_tryout %}required{% endif %} {% if hasil %}disabled{% if hasil[i].dipilih == loop.index0 %} checked{% endif %}{% endif %}>
              <span>{{ p }}</span>
            </label>
          {% endfor %}
          {% if hasil %}
            <div class="bahas">
              <strong>{{ '✅ Benar!' if hasil[i].benar else '❌ Jawaban tepat: ' ~ s.pilihan[s.jawaban] ~ '.' }}</strong> {{ s.bahas }}
              {% if not hasil[i].benar %}
                <div style="margin-top:8px;">
                  <button type="button" class="tombol-3d" style="padding:6px 14px; font-size:0.85rem; background:#8b5cf6; box-shadow:0 3px 0 #5b21b6;"
                    data-idx="{{ i }}" data-soal="{{ s.tanya }}" data-murid="{{ s.pilihan[hasil[i].dipilih] if hasil[i].dipilih is not none else 'Kosong' }}"
                    data-benar="{{ s.pilihan[s.jawaban] }}" data-bahas="{{ s.bahas }}" onclick="tanyaTutorAI(this)">
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
          <a class="tombol-3d" href="{{ url_ulang }}">🔄 Soal Baru</a>
          {% if not is_tryout and lv_next and nilai >= 70 %}
            <a class="tombol-3d tombol-merah" href="/kelas/{{ kelas }}/{{ slug }}/latihan?level={{ lv_next }}">🚀 Lanjut Level {{ lv_next|capitalize }} &rarr;</a>
          {% endif %}
          <a class="tombol-3d tombol-hijau" href="/profil">📊 Progress Saya</a>
        </div>
      {% else %}
        <button class="tombol-3d tombol-hijau" type="submit">🚀 Kumpulkan Jawaban</button>
      {% endif %}
    </form>
    <script>
      async function tanyaTutorAI(btn) {
        const box = document.getElementById('ai-box-' + btn.dataset.idx);
        box.style.display = 'block';
        box.innerText = '🤖 Asisten Tutor AI sedang menyiapkan langkah-langkah mudahnya...';
        try {
          const res = await fetch('/tanya-ai', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ soal: btn.dataset.soal, jawaban_murid: btn.dataset.murid, jawaban_benar: btn.dataset.benar, bahas: btn.dataset.bahas })
          });
          const data = await res.json();
          box.innerText = data.jawaban;
        } catch(e) { box.innerText = '⚠️ Gagal menghubungi AI. Coba periksa koneksi internetmu ya!'; }
      }
    </script>
    {% if is_tryout and not hasil %}
    <script>
      let detik = 600;
      const interval = setInterval(() => {
        detik--; document.getElementById('sisa-detik').value = detik;
        document.getElementById('tampilan-timer').innerText = String(Math.floor(detik/60)).padStart(2,'0') + ':' + String(detik%60).padStart(2,'0');
        if (detik <= 0) { clearInterval(interval); document.getElementById('form-kuis').submit(); }
      }, 1000);
    </script>
    {% endif %}"""
    return render_halaman(html, kelas=kelas, slug=slug, level=level, lv_next=lv_next, is_tryout=is_tryout, judul=judul, soal=soal, hasil=hasil, nilai=nilai, pesan=pesan, bintang=bintang, url_ulang=url_ulang, url_kembali=url_kembali)

# ================= MINI-GAME =================
@app.route("/minigame", methods=["GET", "POST"])
def minigame():
    if request.method == "POST":
        b = max(0, min(60, int(request.form.get("benar_game", 0) or 0)))
        s = max(0, min(60, int(request.form.get("salah_game", 0) or 0)))
        user = get_user_aktif()
        if user:
            with get_db() as db:
                db.execute("UPDATE users SET poin = MAX(0, poin + ?), soal_benar = soal_benar + ?, soal_salah = soal_salah + ? WHERE id = ?", (max(0, b*10 - s*2), b, s, user["id"]))
        return redirect(url_for("leaderboard"))
    html = """
    <p><a href="/">&larr; Kembali ke Beranda</a></p>
    <h1>🎮 Math Blitz: Tantangan 60 Detik!</h1>
    <div id="layar-awal" style="text-align:center; padding:24px; background:#f8fafc; border-radius:20px; border:3px dashed #cbd5e1;">
      <button class="tombol-3d tombol-hijau" onclick="mulaiGame('mudah')">🐣 Mudah</button>
      <button class="tombol-3d" onclick="mulaiGame('sedang')">🚀 Sedang</button>
      <button class="tombol-3d tombol-merah" onclick="mulaiGame('sulit')">🔥 Sulit</button>
    </div>
    <div id="layar-main" style="display:none;">
      <div style="display:flex; justify-content:space-between; background:#1e293b; color:#fff; padding:12px 18px; border-radius:14px; margin-bottom:16px; font-weight:800;">
        <div>⏱️ <span id="waktu" style="color:#facc15;">60</span>d</div><div>⭐ Skor: <span id="skor" style="color:#facc15;">0</span></div>
      </div>
      <div style="text-align:center; padding:26px; background:#eff6ff; border:3px solid #3b82f6; border-radius:20px;">
        <div id="teks-soal" style="font-family:'Fredoka',sans-serif; font-size:2.4rem; margin-bottom:18px;"></div>
        <div id="wadah-opsi" style="display:grid; grid-template-columns:repeat(2, 1fr); gap:12px; max-width:400px; margin:0 auto;"></div>
      </div>
    </div>
    <div id="layar-selesai" style="display:none; text-align:center; padding:24px; background:#fef9c3; border:3px solid #eab308; border-radius:20px;">
      <h2>🏆 Waktu Habis! Skor: <span id="skor-akhir">0</span></h2>
      <form method="post">
        <input type="hidden" id="in-b" name="benar_game" value="0"><input type="hidden" id="in-s" name="salah_game" value="0">
        <button class="tombol-3d tombol-hijau" type="submit">💾 Simpan Skor</button>
      </form>
    </div>
    <script>
      let skor=0, bCnt=0, sCnt=0, waktu=60, lv='mudah', jwb=0;
      const acak = (a,b) => Math.floor(Math.random()*(b-a+1))+a;
      function mulaiGame(l) {
        lv=l; skor=0; bCnt=0; sCnt=0; waktu=60;
        document.getElementById('layar-awal').style.display='none'; document.getElementById('layar-main').style.display='block'; soalBaru();
        const t = setInterval(() => {
          waktu--; document.getElementById('waktu').innerText=waktu;
          if (waktu<=0) { clearInterval(t); document.getElementById('layar-main').style.display='none'; document.getElementById('layar-selesai').style.display='block';
            document.getElementById('skor-akhir').innerText=skor; document.getElementById('in-b').value=bCnt; document.getElementById('in-s').value=sCnt; }
        }, 1000);
      }
      function soalBaru() {
        let a = lv==='mudah'?acak(2,15):acak(3,12), b = lv==='mudah'?acak(2,15):acak(3,12);
        jwb = lv==='mudah'?a+b:a*b;
        document.getElementById('teks-soal').innerText = `${a} ${lv==='mudah'?'+':'×'} ${b} = ?`;
        let ops = new Set([jwb]); while(ops.size<4){ let s=jwb+acak(-6,6); if(s>0) ops.add(s); }
        const w = document.getElementById('wadah-opsi'); w.innerHTML='';
        Array.from(ops).sort(()=>Math.random()-0.5).forEach(n => {
          const btn = document.createElement('button'); btn.className='tombol-3d'; btn.innerText=n;
          btn.onclick = () => { if(n===jwb){bCnt++;skor+=10;bunyiEfek('benar');}else{sCnt++;skor=Math.max(0,skor-2);bunyiEfek('salah');} document.getElementById('skor').innerText=skor; soalBaru(); };
          w.appendChild(btn);
        });
      }
    </script>"""
    return render_halaman(html)

# ================= DASHBOARD KHUSUS IBU GURU =================
@app.route("/guru", methods=["GET", "POST"])
def guru():
    pesan_guru = err_guru = None
    if request.method == "POST":
        aksi = request.form.get("aksi")
        if aksi == "login_guru":
            if request.form.get("pin_guru") == PIN_GURU:
                session.permanent = True; session["is_guru"] = True
            else:
                err_guru = "PIN Ibu Guru salah!"
        elif aksi == "logout_guru":
            session.pop("is_guru", None); return redirect(url_for("login"))
        elif session.get("is_guru"):
            uid = request.form.get("user_id")
            with get_db() as db:
                if aksi == "setujui_murid":
                    db.execute("UPDATE users SET status = 'aktif' WHERE id = ?", (uid,)); pesan_guru = "Akun murid disetujui!"
                elif aksi == "tambah_pr":
                    kode = request.form.get("kode_materi", "")
                    if "|" in kode:
                        k_s, sl = kode.split("|", 1)
                        m_obj = next((x for x in MATERI if str(x["kelas"]) == k_s and x["slug"] == sl), None)
                        if m_obj:
                            db.execute("INSERT INTO tugas_pr (kelas, slug, judul_bab, catatan) VALUES (?, ?, ?, ?)", (m_obj["kelas"], m_obj["slug"], m_obj["judul"], request.form.get("catatan", "").strip()))
                            pesan_guru = "PR berhasil dikirim!"
                elif aksi == "hapus_pr":
                    db.execute("DELETE FROM tugas_pr WHERE id = ?", (request.form.get("pr_id"),)); pesan_guru = "PR dihapus."
                elif aksi == "reset_pin":
                    pb = request.form.get("pin_baru", "").strip()
                    if len(pb) == 4 and pb.isdigit():
                        db.execute("UPDATE users SET pin = ? WHERE id = ?", (pb, uid)); pesan_guru = "PIN diperbarui!"
                elif aksi == "hapus_murid":
                    db.execute("DELETE FROM nilai_bab WHERE user_id = ?", (uid,))
                    db.execute("DELETE FROM users WHERE id = ?", (uid,)); pesan_guru = "Akun dihapus."

    if not session.get("is_guru"):
        return render_halaman("""
        <p><a href="/login">&larr; Kembali</a></p>
        <div style="max-width:400px; margin:20px auto; background:#fefce8; padding:24px; border-radius:20px; border:3px solid #eab308;">
          <h1 style="margin-top:0; font-size:1.5rem;">👩‍🏫 Ruang Khusus Ibu Guru</h1>
          {% if err_guru %}<p style="color:#dc2626; font-weight:800;">⚠️ {{ err_guru }}</p>{% endif %}
          <form method="post"><input type="hidden" name="aksi" value="login_guru">
            <input class="input-box" type="password" name="pin_guru" placeholder="PIN Guru" required>
            <button class="tombol-3d" type="submit">Masuk Dashboard</button>
          </form>
        </div>""", err_guru=err_guru)

    with get_db() as db:
        antrean = db.execute("SELECT id, nama, pin, avatar FROM users WHERE status = 'pending' ORDER BY id ASC").fetchall()
        prs = db.execute("SELECT * FROM tugas_pr ORDER BY id DESC").fetchall()
        murids = db.execute("""
            SELECT u.id, u.nama, u.pin, u.avatar, u.poin, u.streak, COUNT(n.kode_bab) AS bab_selesai
            FROM users u LEFT JOIN nilai_bab n ON u.id = n.user_id
            WHERE u.status = 'aktif' GROUP BY u.id, u.nama, u.pin, u.avatar, u.poin, u.streak
            ORDER BY u.poin DESC, u.nama ASC
        """).fetchall()

    html_dash = """
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
      <h1>👩‍🏫 Dashboard Ibu Guru</h1>
      <form method="post"><input type="hidden" name="aksi" value="logout_guru"><button class="tombol-3d" style="background:#64748b; padding:8px 14px; font-size:0.9rem;" type="submit">Keluar</button></form>
    </div>
    {% if pesan_guru %}<div style="background:#dcfce7; color:#166534; padding:12px; border-radius:12px; font-weight:800; margin-bottom:14px;">✅ {{ pesan_guru }}</div>{% endif %}
    {% if antrean %}
      <div style="background:#fef9c3; border:3px solid #eab308; border-radius:16px; padding:16px; margin-bottom:20px;">
        <h2 style="margin-top:0;">🔔 Menunggu Persetujuan ({{ antrean|length }})</h2>
        {% for a in antrean %}
          <div style="display:flex; justify-content:space-between; align-items:center; background:#fff; padding:8px 12px; border-radius:10px; margin-top:6px;">
            <span>{{ a.avatar }} <strong>{{ a.nama }}</strong> (PIN: {{ a.pin }})</span>
            <div>
              <form method="post" style="display:inline;"><input type="hidden" name="aksi" value="setujui_murid"><input type="hidden" name="user_id" value="{{ a.id }}"><button type="submit" style="background:#22c55e; color:#fff; border:none; padding:5px 12px; border-radius:8px; cursor:pointer;">✅ Terima</button></form>
              <form method="post" style="display:inline;"><input type="hidden" name="aksi" value="hapus_murid"><input type="hidden" name="user_id" value="{{ a.id }}"><button type="submit" style="background:#ef4444; color:#fff; border:none; padding:5px 10px; border-radius:8px; cursor:pointer;">❌ Tolak</button></form>
            </div>
          </div>
        {% endfor %}
      </div>
    {% endif %}
    <div style="background:#eff6ff; border:2px solid #93c5fd; border-radius:16px; padding:16px; margin-bottom:20px;">
      <h2 style="margin-top:0;">📋 Beri Tugas / PR</h2>
      <form method="post" style="display:flex; gap:8px; flex-wrap:wrap;">
        <input type="hidden" name="aksi" value="tambah_pr">
        <select name="kode_materi" style="padding:8px; border-radius:8px; flex:1;">
          {% for m in daftar_materi %}<option value="{{ m.kelas }}|{{ m.slug }}">Kelas {{ m.kelas }} — {{ m.judul }}</option>{% endfor %}
        </select>
        <input type="text" name="catatan" placeholder="Catatan PR" style="padding:8px; border-radius:8px; flex:1;">
        <button type="submit" class="tombol-3d" style="padding:8px 16px; font-size:0.9rem;">+ Pasang PR</button>
      </form>
      {% for pr in prs %}
        <div style="display:flex; justify-content:space-between; background:#fff; padding:6px 12px; border-radius:8px; margin-top:6px;">
          <span>Kelas {{ pr.kelas }}: {{ pr.judul_bab }}</span>
          <form method="post" style="margin:0;"><input type="hidden" name="aksi" value="hapus_pr"><input type="hidden" name="pr_id" value="{{ pr.id }}"><button type="submit" style="background:#ef4444; color:#fff; border:none; padding:3px 8px; border-radius:6px;">Hapus</button></form>
        </div>
      {% endfor %}
    </div>
    <h2>📚 Daftar Murid Aktif ({{ murids|length }} anak)</h2>
    <div style="overflow-x:auto;">
      <table class="tabel-lb">
        <thead><tr><th>Murid</th><th>PIN</th><th>Progress</th><th>Poin</th><th>Kelola</th></tr></thead>
        <tbody>
          {% for m in murids %}
            <tr>
              <td>{{ m.avatar }} <strong>{{ m.nama }}</strong></td><td><code>{{ m.pin }}</code></td>
              <td>{{ m.bab_selesai }} / {{ total_bab }} bab</td><td><strong>{{ m.poin }}</strong></td>
              <td>
                <form method="post" style="display:inline;"><input type="hidden" name="aksi" value="reset_pin"><input type="hidden" name="user_id" value="{{ m.id }}">
                  <input type="text" name="pin_baru" maxlength="4" pattern="[0-9]{4}" placeholder="PIN" style="width:58px; padding:3px;" required>
                  <button type="submit" style="background:#eab308; border:none; padding:4px 8px; border-radius:6px;">Ubah</button>
                </form>
                <form method="post" style="display:inline;"><input type="hidden" name="aksi" value="hapus_murid"><input type="hidden" name="user_id" value="{{ m.id }}">
                  <button type="submit" style="background:#ef4444; color:#fff; border:none; padding:4px 8px; border-radius:6px;">Hapus</button>
                </form>
              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>"""
    return render_halaman(html_dash, antrean=antrean, prs=prs, daftar_materi=MATERI, total_bab=len(MATERI), murids=murids, pesan_guru=pesan_guru, err_guru=err_guru)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)