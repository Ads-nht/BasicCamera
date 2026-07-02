# 🗺️ Basic Camera - Yol Haritası (Roadmap)

## 📌 Faz 1: Core Backend & Poka-Yoke Entegrasyonu (Tamamlandı)
* [x] Udev hotplug docker tetikleme yapısının kurulması (`99-nikon-camera.rules`).
* [x] Docker-compose ve multi-stage Dockerfile konfigürasyonu.
* [x] FastAPI asenkron PTP kontrolcüsü ve sub-process wrapper'ı.
* [x] Lock tabanlı race-condition engellemesi.
* [x] Indeks kaymasını önleyen geriye doğru silme (descending delete) mantığı.
* [x] Token korumalı silme doğrulama mekanizması.

## 📌 Faz 2: Frontend & High-Tech Workstation Arayüzü
* [ ] "High-Tech Workstation" tasarım kılavuzuna uygun minimalist karanlık mod web arayüzünün yazılması.
* [ ] Kamera durum göstergesi (Connected / Disconnected / Backing up).
* [ ] Resim galerisi ve video oynatma desteği (FastAPI stream endpoint'i kullanarak).
* [ ] Çoklu seçim (multiple select) ile toplu yedekleme (backup) ve toplu silme paneli.
* [ ] Canlı yedekleme ilerleme çubuğu (progress bar) ve detaylı log ekranı.

## 📌 Faz 3: Otomatik Senkronizasyon & Arşivleme
* [ ] USB takıldığında kullanıcı onayı aramaksızın doğrudan "otomatik yedekle ve kamerayı temizle" tetikleyici modu (Opsiyonel konfigürasyon).
* [ ] Yedeklenen resimlerin tarih damgalı klasörlere otomatik kategorize edilmesi (`YYYY-MM-DD`).
* [ ] Düşük disk alanı uyarı sistemi.
