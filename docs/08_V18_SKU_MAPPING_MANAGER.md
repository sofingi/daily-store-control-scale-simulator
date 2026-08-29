# V1.8 — SKU Mapping Manager

## Tujuan
Menghilangkan ketergantungan pada kesamaan nama/kode antara SKU Toko dan SKU Gudang. HPP tetap berasal dari BigSeller Master HPP, tetapi hubungan SKU disimpan oleh aplikasi.

## Prioritas resolusi HPP
1. **Mapping Manual** (`SKU Toko → SKU Gudang`) — prioritas tertinggi.
2. **Exact Code Match** — jika kode SKU Toko sama persis dengan Nomor SKU Gudang.
3. **Unmapped** — HPP tidak ditebak dan profit tetap berstatus belum final/partial.

## Menu SKU Mapping
- Daftar SKU belum terhubung, diurutkan berdasarkan qty transaksi.
- Daftar SKU yang sudah dipetakan manual.
- Exact-code match otomatis.
- Saran 5 pasangan SKU Gudang berdasarkan kode, nama, ukuran dan atribut varian seperti packing kayu.
- Pengguna tetap harus menekan **Hubungkan**; aplikasi tidak menyimpan saran otomatis.
- Mapping dapat dihapus/diubah kapan saja.

## Efek ke Profit Engine
Saat mapping disimpan, aplikasi langsung:
1. mengambil HPP dari SKU Gudang target,
2. memperbarui seluruh order lama dengan SKU Toko tersebut,
3. menghitung ulang daily profit,
4. menghitung ulang data-quality/finality.

Perubahan nama SKU Toko atau nama SKU Gudang tidak memutus mapping selama kode `store_sku` dan `warehouse_sku` yang tersimpan masih valid.

## Smoke test data riil 1 Jul–28 Agu 2026
Dengan master SKU Gudang update 29 Agustus 2026:
- 594 SKU Toko unik terdeteksi,
- 531 exact-code match,
- 63 belum terhubung,
- qty HPP coverage sebelum mapping manual ≈ 96.08%.

Contoh suggestion:
`PE-FOAM-1-MM` → `PE-FOAM-1MM-METERAN` sebagai kandidat tertinggi.
