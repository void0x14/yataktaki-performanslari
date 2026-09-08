# Hedef ve ilk port

## Hedef

Nasıl seçilir: `.codex/skills/hunter-soul/SKILL.md`. Bu dosya ruh değil, fizik: burun/diş açık mı, evren taranmıyor mu, pencere bakışı gösteriyor mu.

Av: açık vekil. Operatör koordinat yazmaz.

## Hariç

- Operatörden CIDR/ASN/port isteme.
- Sabit skor, evrensel port sırası, “şu 5 tarihi kararı doldur”.
- Rastgele evren taraması.
- example.com / whatismyip sınıfı gezinme.
- 1.1.1.1 / 8.8.8.8 / AS13335 önyüklemesi.

## Mevcut kırık

Kaynak fazı yalnız `browse_public_source` açık. Sahiplik (`inspect_owner_context`) ve kardeş aralık (`list_owner_ranges`) yazılı, faz kilidiyle kapalı. Intent fazı yalnız `masscan_liveness` ister, kaydeder, `intent_ready` deyip uyur. `expand_live_ip` / `validate_proxy` / `publish_proxy` döngüye hiç giremez.

Bu yüzden model rastgele sayfa açar, geçerli av niyeti üretemez, tarama olmaz.

## Av döngüsü (tek hat)

```
bak → aday+neden+ilk port → küçük canlılık → (canlıysa) dikey genişle → el sıkış+çıkış → etiket → iz → kardeş
```

Atlama yok. İlk port yoksa tarama yok. Canlılık yoksa genişleme yok. Çıkış yoksa satış yok.

### 1. Bak

İlk turda açık araçlar yalnız av kaynakları:

- `inspect_owner_context` (RDAP: kim, hangi aralık)
- `list_owner_ranges` (aynı ASN’in kardeşleri)
- `browse_public_source` yalnız av hostları: `stat.ripe.net`, `rdap.*`, `bgp.he.net`, `myip.ms` (operatörün eski yüzeyi)

Başka URL sözleşme reddi. Cloudflare DNS önyüklemesi yok. İlk bakış: son **isabetin** kardeşi, yoksa av sayfası. Son kaçırılan kapı değil.

### 2. Aday + ilk port (tek karar)

Masscan’den önce ajan şunları aynı kararda yazar:

- baktığı kaynak ref
- seçtiği dilim (en fazla /24)
- **neden bu hedef** (sayfadan gelen org/ASN/koku; uydurma yasak)
- **tek ilk port**
- **neden o port** (bu hedefin kokusuna bağlı)

Eksik alan = tarama yok, tekrar bak.

İlk port evrensel liste değildir. Hedefin kokusu portu seçer. Ucuz hosting / açık vekil kokusu başka port, SOCKS kokusu başka, ev router/tuhaf geçit kokusu başka. Hepsi birden “ilk atış” olamaz.

Operatör konuştukça av defterine düşer (“böyle durunca ben 3128’e bakardım”). Defter her kararda okunur. Dondurulmuş tarih seti değil.

### 3. Küçük canlılık

Yalnız o dilim + o ilk port. Rate düşük. Manifest dışı yok.

### 4. Dikey genişleme

Bir IP canlı çıktıysa `expand_live_ip` o IP’de. Masscan evreni değil. Aralıklar av defteri + bu isabetin kokusu. Komşu adresler ancak bu IP’de bir şey çıktıktan sonra.

### 5. Ne olduğu

Açık uçta el sıkışma + gerçek çıkış. Banner/protokol/çıkış tekrarları squid, socks, rotate, vs. ayırır. Etiket kanıtsız yazılmaz.

### 6. İz

Her tur: baktım, seçtim, neden, ilk port, canlı mı, genişleme, el sıkış, etiket. Sonraki tur bu izi okur. Aynı kapıya iki kez vurulmaz. Damar bitince kardeşe veya yeni bakışa geçilir. Beşinci denemede tekleyen insan hafızasının yerine bu iz geçer.

## Kabul

1. Ajan CIDR sormadan av sayfası/sahiplik/kardeş ile başlar.
2. example.com / 1.1.1.1 ile başlayan koşu fail.
3. İlk portu tek ve gerekçeli olmayan masscan reddedilir.
4. Canlılık sonrası `expand_live_ip` açılır; önce değil.
5. Çıkışsız uç yayınlanmaz.
6. Kokpitte bakılan yer, seçilen neden, ilk port, canlı sonuç aynı bakışta durur.

## Doğrulama

- Sözleşme testleri: av-dışı URL reddi; ilk portsuz intent reddi; faz sırası (bak → canlılık → genişle → doğrula).
- Canlı canary: bir ajan, operatör CIDR vermeden, av kaynağından dilim+ilk port üretir. Tarama yalnız o manifestte. Sonuç 0 olsa bile neden+port+iz görünür.
