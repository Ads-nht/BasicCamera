# BasicCamera — PTP Kamera Yöneticisi ve Web Paneli

[English](README.md) | [Türkçe](README.tr.md)

BasicCamera, Nikon DSC Coolpix S2900 (`04b0:035e`) dijital fotoğraf makinesini USB/PTP protokolü üzerinden yöneten Dockerize bir FastAPI backend'idir. Fotoğraf ve videoları web paneli üzerinden listeler, stream eder, yedekler ve siler — udev hotplug kontrolü ile boşta sıfır kaynak tüketir.

---

## Öne Çıkan Özellikler

- **Sıfır boşta kaynak** — udev kuralları USB takılınca Docker konteynerini başlatır, çıkarılınca durdurur
- **Asenkron FastAPI backend** — Kalıcı gphoto2 oturumu; USB hatalarında otomatik kurtarma
- **Bellek dostu streaming** — Büyük medya dosyaları 64 KB parçalar halinde RAM'e yüklenmeden aktarılır
- **Web paneli** — `/` adresinde galeri, önizleme, yedekleme ve silme için dahili HTML arayüz
- **Küçük resim önbelleği** — Oluşturulan önizlemeler diskte önbelleğe alınır
- **Poka-yoke güvenceleri:**
  - USB kopması sunucuyu çökertmez; `{ "status": "camera_disconnected" }` döner
  - `asyncio.Lock` ile PTP istekleri sıraya konur; tampon taşması engellenir
  - Silme işlemleri indeks kaymasını önlemek için büyükten küçüğe sıralanır
  - Silme için `confirm=True` ve `SECURE_DELETE_TOKEN` ortam değişkeni zorunlu

---

## Mimari

| Bileşen | Açıklama |
|---------|----------|
| `app.py` | FastAPI sunucusu, gphoto2 sarmalayıcı, API uç noktaları |
| `index.html` | Web panel arayüzü |
| `Dockerfile` | gphoto2 CLI + python-gphoto2 içeren çok aşamalı build |
| `docker-compose.yml` | USB cihaz eşlemesi (`/dev/bus/usb`) |
| `99-nikon-camera.rules` | udev hotplug tetikleyici |

**Dil:** Python 3.11 · **Bağımlılıklar:** FastAPI, Uvicorn, gphoto2, Pillow

### API Uç Noktaları

| Metot | Yol | Açıklama |
|-------|-----|----------|
| GET | `/api/status` | Kamera bağlantı durumu |
| GET | `/api/files` | Kameradaki dosyaları listele |
| GET | `/api/files/{index}/preview` | Düşük çözünürlüklü önizleme |
| GET | `/api/files/{index}/stream` | Tam çözünürlüklü stream |
| GET | `/api/files/{index}/thumbnail` | Önbellekli küçük resim |
| POST | `/api/backup` | Tüm dosyaları depolamaya yedekle |
| GET | `/api/backup/status` | Yedekleme ilerlemesi |
| POST | `/api/files/delete` | Dosya sil (onay gerekli) |
| GET | `/api/backups` | Yedeklenmiş dosyaları listele |
| GET | `/api/system/status` | Sistem ve depolama bilgisi |

---

## Kurulum

### 1. udev kuralını yükle (host)

```bash
sudo cp 99-nikon-camera.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 2. Konteyneri oluştur (ilk kurulum)

```bash
docker compose build
docker compose up --no-start
```

Konteyner `restart: "no"` kullanır — yaşam döngüsü tamamen udev tarafından yönetilir.

### 3. Kamerayı bağla

Nikon Coolpix S2900'ü USB ile takın. udev konteyneri otomatik başlatır. [http://localhost:8000](http://localhost:8000) adresini açın.

---

## Ortam Değişkenleri

| Değişken | Varsayılan | Açıklama |
|----------|------------|----------|
| `SECURE_DELETE_TOKEN` | `CONFIRM_DELETE_COOLPIX` | Silme işlemleri için zorunlu token |
| `REMOTE_CAMERA_HOST` | — | Opsiyonel: uzak host'tan SSH ile dosya çekme |

---

## Sorun Giderme

Masaüstü ortamı kamerayı kilitlerse (`Could not claim the USB device`):

```bash
killall gvfsd-gphoto2
```

---

## Lisans

MIT Lisansı
