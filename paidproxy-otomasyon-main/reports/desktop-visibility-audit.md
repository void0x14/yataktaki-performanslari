# PaidProxy masaüstü görünürlük audit'i

Oluşturulma: 2026-09-05
İncelenen alan: mevcut native desktop uygulamasının hedefteki görünürlük ve operasyon merkezi gereksinimine karşı canlı kaynak incelemesi.
Kaynak: mevcut paidproxy çalışma ağacı ve gerçek X11 ekran görüntüsü reports/iteration-7-desktop.png.

## Sonuç

KALDI — mevcut masaüstü uygulaması hedeflenen operasyon merkezi değildir.

## Doğrulanmış gerçekler

- desktop/app/main.py tek bir QMainWindow içinde üç grup kuruyor: süreç listesi, metin tabanlı canlı alan ve düğme ağırlıklı “Çalıştır + İzle” alanı.
- Canlı alan gerçek VDS ekranını gömmüyor. on_live_view yalnız display_select çağırıyor, ardından işletim sisteminin QDesktopServices.openUrl() davranışıyla vnc:// adresini harici görüntüleyiciye bırakıyor.
- Ekrandaki “Göz” bileşeni yalnız QListWidget ile event/tool/target/note metni gösteriyor; gerçek baktığı sayfa veya VDS surface yok.
- FilmSeridi yalnız QPixmap ile en fazla 12 PNG karesi listeliyor; video oynatma, scrubber, senkron zaman çizgisi veya replay yüzeyi yok.
- main.py artifact indirmeyi event geldikçe arka thread'lerde deniyor; kalıcı artifact durumunu kullanıcıya ayrı bir güvenilirlik/indirme kuyruğu olarak göstermiyor.
- remote_worker.py her request için ayrı thread açıyor; lifecycle komutları için görünür bir serialized command state veya tek ajan kontrol kilidi yok.
- ProcessStore.sync_remote() uzak son sequence değerini saklamıyor; desktop tarafındaki görünür durum modelinin reconnect/replay bütünlüğü eksik.
- desktop/app/vds.py artifact remote path'i {remote_dir}/agents/... olarak kuruyor; gerçek VDS path'i {remote_dir}/var/agentd/agents/... olduğundan gerçek cache indirme kırılıyor.
- Gerçek ekran görüntüsünde merkezde ajanın ekranı değil event metni; sağda boş film şeridi/sonuç alanı ve hata logu; canlı VDS yüzeyi masaüstü içinde görünmüyor.
- Pet görünür olsa da operasyonel bağlamla bütünleşmiş bir pet/ajan çalışma yüzeyi yok; yalnızca tek bir çizim ve isim/enerji sunuluyor.

## Kullanıcı kabul ölçütlerine göre eksik

1. Herhangi bir ajanı tek bakışta canlı ekran + ne yaptığı + baktığı + düşündüğü + kanıtı ile izleme: yok.
2. Gerçek video ve ekran replay'i: yalnız kare şeridi ve harici VNC açma var; yok.
3. A-Z süreç yönetimi: düğmeler var, fakat komut durumu, yarış önleme ve sonuç görünürlüğü güvenilir değil.
4. Her işlemin görünür ve etkileşimli olması: artifact/cache ve VNC yolu uygulama içi değil.
5. Masaüstü operasyon merkezi: mevcut ekran yoğun butonlu kontrol paneli; ajan çalışma yüzeyi ve kanıt zaman çizgisi yok.

## Değiştirilmemesi gereken sınır

Yerel uygulama yalnızca native gözlem, kullanıcı komutu, artifact cache ve VDS'den teslim alma katmanıdır. Agent/AI/tarama yerelde çalıştırılmayacaktır.

## Sonraki doğru iş

Önce desktop/app/main.py ve ilişkili desktop bileşenlerini görünürlük-first çalışma yüzeyi olarak yeniden kurmak; gerçek VDS frame/video/artifact kaynaklarını aynı native pencerede canlı göstermek; sonra kontrol/reconnect ve tarama hattına dönmek.
