# 📷 Basic Camera Manager

Basic Camera Manager, Nikon DSC Coolpix S2900 (USB ID: `04b0:035e`) dijital fotoğraf makinesinden PTP (Picture Transfer Protocol) protokolünü kullanarak fotoğraf ve videoları otonom olarak yedeklemek, listelemek, silmek ve stream etmek amacıyla tasarlanmış Dockerize bir web uygulaması arka uç (backend) servisidir.

## 🚀 Özellikler
* **0-Idle Resource:** Sunucu kaynaklarını korumak amacıyla udev hotplug tetikleme sistemi. Fotoğraf makinesi bağlandığında Docker konteyneri otomatik başlar (`docker start`), bağlantı koptuğunda ise otomatik durdurulur (`docker stop`).
* **Asenkron FastAPI:** Tamamen asenkron yapıda kurulmuş Python/FastAPI backend'i.
* **Bellek Dostu Medya Akışı (Streaming):** Büyük boyutlu fotoğraf ve videoları sunucu belleğine (RAM) yüklemeden doğrudan kamera üzerinden istemciye stream eder.
* **Poka-Yoke (Hata Önleme) Güvenceleri:**
  * **Bağlantı Dayanıklılığı:** USB kablosu işlem ortasında çekilirse, `gphoto2` CLI/sub-process hataları yakalanır ve sunucu çökmeden `{ "status": "camera_disconnected" }` yanıtı döndürülür.
  * **İşlem Kilidi (Concurrency Lock):** `asyncio.Lock` kullanılarak tüm PTP istekleri sıraya konur; kullanıcının ardışık tıklamalarla kamera tampon belleğini (buffer) şişirmesi engellenir.
  * **Geriye Doğru Silme (PTP Shift Prevention):** Dosya silme isteklerinde indeks kaymalarını önlemek amacıyla indeksler **büyükten küçüğe** (descending) sıralanarak silinir.
  * **Silme Güvenlik Duvarı:** Silme istekleri zorunlu doğrulama token'ı (`CONFIRM_DELETE_COOLPIX`) ve onay bayrağı ile korunur.

## 📁 Proje Klasör Yapısı
* `app.py`: FastAPI backend kodu, asenkron gphoto2 wrapper'ı ve güvenli API endpoint'leri.
* `Dockerfile`: `python:3.11-slim` tabanlı, `gphoto2` CLI paketini içeren iki aşamalı (multi-stage) minimal Docker imaj tanımı.
* `docker-compose.yml`: `/dev/bus/usb` cihaz map'lemesini barındıran docker-compose dosyası.
* `99-nikon-camera.rules`: Fotoğraf makinesi algılandığında docker'ı tetikleyen udev kuralı.

## 🛠️ Kurulum ve Çalıştırma

### 1. Udev Kuralını Tanımlama (Sunucu Üzerinde)
Uzak sunucu terminalinde udev kuralını `/etc/udev/rules.d/` altına kopyalayın ve udev servisini yeniden yükleyin:
```bash
sudo cp 99-nikon-camera.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 2. Docker Konteynerini Oluşturma (İlk Kurulum)
Konteynerin udev tarafından başlatılabilmesi için önce bir kez build edilip oluşturulması gerekir:
```bash
docker-compose build
docker-compose up --no-start
```

*Not: Konteynerin restart politikası `restart: "no"` olarak ayarlanmıştır. Çalışma döngüsü tamamen udev tarafından kontrol edilecektir.*

## ⚠️ GVFS / Cihaz Meşgul Hatası Çözümü
Eğer masaüstü ortamı (KDE, GNOME) kamerayı otomatik bağlayarak kilitleirse (`Could not claim the USB device` hatası alınırsa), aşağıdaki komutla gvfs-gphoto monitorünü durdurabilirsiniz:
```bash
killall gvfsd-gphoto2
```
