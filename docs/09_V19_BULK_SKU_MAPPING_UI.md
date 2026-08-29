# V1.9 — Bulk SKU Mapping UI

## Tujuan
Mempercepat penyelesaian SKU Toko yang belum terhubung tanpa mengubah nama SKU di Shopee/BigSeller.

## Prinsip keamanan
- Saran otomatis bersifat read-only.
- Tidak ada mapping yang dibuat tanpa pilihan/konfirmasi pengguna.
- Mapping manual mengalahkan exact-code matching.
- Satu batch mapping memicu satu kali rebuild HPP dan Profit Engine.

## UI
Menu **SKU Mapping** menyediakan:
1. Ringkasan Belum Terhubung, Mapping Manual, Exact Match, Coverage Qty HPP.
2. Search/filter SKU.
3. Mapping massal berbantuan saran untuk SKU prioritas berdasarkan qty/sales.
4. Checkbox `Terapkan` sebelum konfirmasi batch.
5. Mapping satu-per-satu dengan 5 kandidat teratas dan filter SKU Gudang.
6. Download daftar belum terhubung dan backup mapping manual.

## Resolusi HPP
`Manual Mapping > Exact SKU Code > Unmapped`.

Perbedaan nama SKU tidak menggagalkan HPP selama relasi mapping benar.
