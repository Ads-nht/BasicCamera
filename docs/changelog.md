# 📝 Değişiklik Günlüğü (Changelog) - Basic Camera

Tüm önemli değişiklikler bu dosyada kronolojik olarak kayıt altına alınacaktır.

## [1.0.0] - 2026-07-02
### Eklendi
* Proje dizini ve standart klasör yapısı (/src, /tests, /docs) başlatıldı.
* `99-nikon-camera.rules` udev kural şablonu yazıldı.
* `/dev/bus/usb` map'li ve `restart: "no"` parametreli `docker-compose.yml` hazırlandı.
* İki aşamalı minimal `Dockerfile` yazıldı.
* Asenkron FastAPI `app.py` oluşturuldu. `gphoto2` sub-process entegrasyonu, stream kanalı, kilit mekanizması ve güvenli silme yapısı eklendi.
* Proje teknik hafızası, yol haritası ve kullanım kılavuzu dokümante edildi.
