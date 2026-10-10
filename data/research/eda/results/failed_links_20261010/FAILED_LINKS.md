# Link lỗi / không vào được

- Phạm vi: **quét đủ mọi bản ghi**; đã đọc 351,261 bản ghi, lỗi **9,946** (2.8%).
- Danh sách đầy đủ từng link: `failed_links.csv` (mở bằng Excel; lọc theo `category`, `domain`).

## Theo nguyên nhân

| Nhóm | Số link | Ý nghĩa |
|---|---:|---|
| `robots_4xx` | 9,786 | robots.txt trả 4xx (thường 403) nên crawler coi như cấm; theo RFC 9309, 4xx nghĩa là không có robots.txt, có thể crawl lại |
| `not_article` | 107 | tải được nhưng không phải bài: ảnh/PDF lạ, quá lớn, chuyển về trang chủ, rỗng |
| `dead` | 41 | link chết: 404/410, DNS lỗi, URL hỏng |
| `temporary` | 4 | lỗi tạm thời: timeout, 5xx, mất kết nối, SSL; thử lại sau |
| `quality_rejected` | 3 | tải được nhưng QC loại (trang lỗi, template, chữ quá ít) |
| `blocked` | 2 | site chặn: 401/403/429/451 hoặc trang challenge chống bot |
| `other` | 2 | trạng thái khác, cần xem `error` |
| `robots_disallow` | 1 | robots.txt cấm rõ ràng URL này; không crawl |

## Theo run

| Run | Đã đọc | Lỗi | Chi tiết |
|---|---:|---:|---|
| `nguyen\output\runs\batch01_nguyen` | 140,137 | 9,905 | robots_4xx: 9786, not_article: 102, dead: 12, blocked: 2, other: 2, robots_disallow: 1 |
| `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843` | 96,439 | 0 |  |
| `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843` | 114,685 | 41 | dead: 29, not_article: 5, temporary: 4, quality_rejected: 3 |

## Domain lỗi nhiều nhất

| Domain | Lỗi | Chi tiết |
|---|---:|---|
| `vov.vn` | 9,784 | robots_4xx: 9784 |
| `thaythuocvietnam.vn` | 102 | not_article: 102 |
| `www.cnkang.com` | 36 | dead: 29, not_article: 5, quality_rejected: 2 |
| `www.wujue.com` | 5 | temporary: 4, quality_rejected: 1 |
| `tiemchunglongchau.com.vn` | 4 | dead: 4 |
| `www.pharmacity.vn` | 4 | dead: 4 |
| `tamanhhospital.vn` | 3 | dead: 2, blocked: 1 |
| `vietnamnet.vn` | 3 | other: 2, dead: 1 |
| `ask.familydoctor.com.cn` | 2 | robots_4xx: 2 |
| `youmed.vn` | 1 | blocked: 1 |
| `suckhoeviet.org.vn` | 1 | dead: 1 |
| `baby.39.net` | 1 | robots_disallow: 1 |
