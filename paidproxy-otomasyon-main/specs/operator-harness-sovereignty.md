# Operatör harness egemenliği

## Hedef

Otonom işte yürürlükteki talimat, kullanıcı kutusuna yazılan metin değil; **isteği montajlayan sürecin `developer` kanalına koyduğu metindir.** Bu şartname, ChatGPT Desktop / Codex Luna ürün katmanının kullanıcı emrini sessizce ezmesini durduracak çalışma sözleşmesini kilitler.

## Hariç tutulan hedefler (Non-goals)

- ChatGPT/Codex ikilisine yama, binary patch, jsonl zehirleme, Guardian exploit, “systemMessage ile platform ol” kancası.
- Modele rica eden ikinci prompt (`instruction-guard.py` tarzı).
- Operatöre güvenlik vaazı, anahtar rotasyonu, “best practice” dayatması.
- PaidProxy av/kokpit ürün kapsamını değiştirmek.

## Mevcut durum

ChatGPT Desktop + `gpt-5.6-luna` xhigh + `personality = "pragmatic"` + `danger-full-access` + `approval never` bile kullanıcıyı `user` kanalında tutar. OpenAI, ürün içinde developer rolünü de oynar.

Bu makinede ek montaj:

- SessionStart kancası Beyin `Last-Session` / daily derlemesini `additionalContext` olarak basar.
- Codex bunu `role: "developer"` kaydeder.
- OCR çatışmasından sonra derleyici “Credential Güvenliği: … reddedilmiş” ve “üst seviye kurallar kullanıcı istemiyle geçersiz kılınamaz” satırlarını karar diye yazdı. Sonraki turlar bu kararı **yeniden emir** olarak görür.

Çıplak modele aynı talimatın geçmesi, checkpoint’in kör kilit olmadığını; ürün montajının fark olduğunu gösterir.

## İstenen durum

1. Executor süreç, operatörün yürürlükteki emrini `developer` (veya tek kanallı yerel modelde tek sistem metni) olarak taşır.
2. Asistan çıktısı, memory/derleyici, kişilik overlay’i yürürlükteki emri ezemez.
3. ChatGPT Desktop varsa yalnızca okunur planlama yüzeyi olabilir; dosya yazan aktör olamaz.
4. Ajan, operatörün operasyonel tercihine vaaz eklemez.

## Gereksinimler

1. **Kanal kuralı:** Yürürlükteki emir, user mesajına değil, istek montajındaki en yüksek operatör-kontrollü role yazılır.
2. **Beyin kuralı:** SessionStart `additionalContext` asistanın “Alınan Kararlar / Öğrenilenler” bloğunu developer’a basmaz. O blok varsa `no-authority` veri sayılır veya hiç enjekte edilmez.
3. **Anti-rica kuralı:** UserPromptSubmit ile modele “ROOT AUTHORITY” metni basılmaz. Bu kanal zaten `managed_developer_instructions` altında kalır ve çatışmayı büyütür.
4. **Ürün kuralı:** ChatGPT Desktop / Codex app, paidproxy otonom executor değildir. Executor: operatörün kurduğu CLI/API/yerel ağırlık süreci.
5. **Sessiz sapma kuralı:** Env’ye kayma, kapsam genişletme, “daha güvenli alternatif” sessiz uygulanamaz. Çatışma varsa durur, montaj hatasını gösterir, emri değiştirmez.
6. **Vaaz yasağı:** Operatörün yazdığı emre güvenlik / rotasyon / prompt-injection / “lamer” çerçevesi eklenmez.

## Kısıtlamalar / değişmezler (invariants)

- OpenAI ürün ikilisinin `managed_developer_instructions` alanı operatör dosyası değildir. O alan ancak ürün terk edilerek devre dışı kalır.
- Guardian v2 binary’de vardır; yokluğu varsayılmaz. Varlığı, her rette ateş ettiği anlamına gelmez. Bu OCR turunda ateş etmedi.
- Ağırlıkta IH önceliği vardır. Harness kalkınca ret oranı düşer; sıfır iddiası bu şartnamede yok.
- Bu şartname exploit üretmez.

## Etkilenen alanlar

- `~/.codex/hooks.json`
- `Documents/Void0x14OS/.codex/hooks/session-start.sh` ve daily derleyici
- `~/.codex/instruction-guard.py` (kaldırılacak / etkisiz)
- Executor seçimi (ChatGPT Desktop dışı)
- `AGENTS.md` operatör egemenliği maddesi
- `context/DECISIONS.md` ADR-003

## Uyumluluk gereksinimleri

PaidProxy 4 kutu ve avcı ruhu değişmez. Bu şartname yalnızca ajan runtime’ının kime itaat ettiğini kilitler.

## Riskler / uç durumlar

- Eski thread’ler, oturum başında basılmış developer kopyasını taşır. Yeni montaj yeni thread ister.
- Memory derleyicisi tekrar “karar” yazarsa zehir geri gelir. Derleyici şablonu da kesilmeli.
- ChatGPT Desktop içinde kalarak “ben developer’ım” demek montajı değiştirmez.

## Kabul kriterleri

1. Yeni bir executor oturumunda asistanın dünkü “reddedildi” özeti `role: developer` olarak gelmez. Kanıt: jsonl’de SessionStart additionalContext’te “Alınan Kararlar / Credential Güvenliği” yok.
2. `instruction-guard.py` UserPromptSubmit zincirinde yoktur veya boştur.
3. Otonom görev ChatGPT Desktop Codex app dışında koşturulabiliyordur (API’de operatör developer’ı / yerel harness).
4. Ajan çıktısında operatör emrine güvenlik vaazı yoktur.
5. ChatGPT Desktop hâlâ kullanılıyorsa spec, onu executor saymaz; sapma “model kaprisi” diye kapanmaz, montaj hatası diye açılır.

## Doğrulama

- OCR-benzeri çatışma thread’inin jsonl dump’ı: developer mesajlarında Beyin “karar” bloğu yok.
- `strings /usr/lib/chatgpt/resources/codex` ile Guardian varlığı yeniden iddia edilmez; olay bazında `GuardianDeniedAction` aranır.
- Executor olarak seçilen süreçte ilk istek gövdesi kaydedilir; `developer` metni operatör dosyasından gelir.

## Uygulama notları

Sıra:

1. Beyin SessionStart enjeksiyonunu kes veya “karar/öğrenilen” bölümünü düşür.
2. `instruction-guard.py` kaldır.
3. Yeni thread.
4. Executor’ı ürün dışına al.
5. İstek gövdesini (rol + metin) her turda diske yaz; sapma olursa montaj kaydına bak, modele rica etme.
