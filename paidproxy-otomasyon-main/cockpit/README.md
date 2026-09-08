# PaidProxy Operasyon Kokpiti

Bu proje için tek gerçek masaüstü uygulaması Tauri'dir.

## Kullanıcı olarak açma

Kurulumdan sonra terminal kullanmadan:

1. Super tuşuna bas.
2. `PaidProxy Operasyon Kokpiti` yaz.
3. Uygulama adına tıkla.

Uygulama menüsü kaydı `cockpit/install-desktop.sh` ile oluşturulur. Bu script yalnızca uygulama menüsü kaydı kurar; günlük açılış için terminal kullanman gerekmez.

## Kaynak haritası

- `app/`: Tauri arayüzü; fare, klavye, buton ve görünüm davranışları burada.
- `src-tauri/`: Tauri masaüstü köprüsü; VDS bağlantısı ve fiziksel etkileşim komutları burada.
- `bridge/`: Tauri'nin kullandığı Python bağlantı ve RFB yardımcıları. Eski PySide6 uygulaması değildir.
- `install-desktop.sh`: Linux uygulama menüsüne PaidProxy kaydı kurar.

Eski PySide6 uygulaması kaldırılmıştır. Ondan alınan gerekli bağlantı davranışları `bridge/` altında Tauri için bağımsız hale getirilmiştir.
