# 🧠 Basic Camera - Proje Hafızası (v1.0.0)

Bu döküman, Basic Camera projesinin mimari kararlarını, mevcut çalışma durumunu ve teknik kısıtlamalarını içerir.

## 📌 Mevcut Durum (Current State)
* **PTP Entegrasyonu:** `gphoto2` CLI aracı kullanılarak Nikon DSC Coolpix S2900 (`04b0:035e`) kamerasıyla asenkron subprocess tabanlı iletişim kuruldu.
* **FastAPI Backend:** `/api/status`, `/api/files`, `/api/files/{index}/stream`, `/api/backup` ve `/api/files/delete` endpoint'lerini barındıran asenkron python sunucusu hazırlandı.
* **Hotplug Kontrolü (Udev):** USB takıldığında `docker start camera-app`, çıkarıldığında `docker stop camera-app` çalıştıran `99-nikon-camera.rules` dosyası yazıldı.
* **Hata Önleme (Poka-Yoke):**
  * Fiziksel kablo kopması durumunda sunucunun çökmesini önlemek için her işlem asenkron hata yakalayıcılarla korundu ve `{ "status": "camera_disconnected" }` JSON çıktısı sağlandı.
  * Eşzamanlı PTP isteklerini ve tampon şişmelerini engellemek için `asyncio.Lock` mekanizması kuruldu.
  * Silme işlemlerinde indeks kayması (PTP indexing shift) sorununu engellemek amacıyla indeksler büyükten küçüğe sıralanarak (descending) işleme alındı.

## 🛠️ Teknik Altyapı ve Kararlar
* **Subprocess vs Python-gphoto2:** Python-gphoto2 kütüphanesi C tabanlıdır ve USB kopmalarında Python yorumlayıcısını doğrudan segmentasyon hatasıyla (segfault) çökertmektedir. Bu durum sunucu kararlılığını bozduğu için, hata yakalama kabiliyeti yüksek olan asenkron `gphoto2` CLI subprocess çağrıları tercih edilmiştir.
* **StreamingResponse:** Büyük boyutlu video ve fotoğrafların RAM tüketimini sıfırlamak için gphoto stdout çıktısı 64KB'lık parçalar (chunks) halinde FastAPI `StreamingResponse` ile istemciye aktarılır.
* **Geri Alma ve Silme Güvenliği:** Yanlışlıkla tüm galeriyi silmeyi engellemek amacıyla `/api/files/delete` endpoint'i `confirm=True` ve `SECURE_DELETE_TOKEN` ortam değişkeni ile çift aşamalı kontrole bağlanmıştır. Token kaynak kodda veya dokümantasyonda paylaşılmaz.

## 🎯 Sonraki Adımlar (Next Steps)
1. Udev kuralının host üzerinde aktif edilerek çalışırlığının doğrulanması.
2. Web arayüzü (frontend) tasarımının (High-Tech Workstation tasarım sistemine uygun) geliştirilmesi ve entegrasyonu.
