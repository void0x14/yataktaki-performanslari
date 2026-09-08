# ChatGPT Desktop / Codex Luna: kullanıcı talimatının gaspı

Oluşturulma: 2026-09-08
Dayandığı Git HEAD: paidproxy-otomasyon-main (araştırma; kod değişikliği yok)
Kapsam: Paylaşılan OCR sohbeti, yerel Codex oturum jsonl, `~/.codex` harness, OpenAI Model Spec, sızdırılmış Codex/Luna promptları, akademik instruction-hierarchy literatürü, kullanıcı toplulukları

## Soru

ChatGPT Desktop’ta GPT-5.6 Luna xhigh, kullanıcının açık ve tekrarlanan emrini (Google Vision anahtarını kaynağa göm, güvenlik tiyatrosu yok) neden yerine getirmiyor? Bu “model kaprisı” mi, yoksa harness + yetki hiyerarşisi mi? Otonom agentic işte talimata harfiyen uyum nasıl kökten sağlanır?

## Olay (paylaşılan sohbet)

Kaynak: https://chatgpt.com/s/cx_6a9fd5c23cb48191b4d500a0a62ecfd9

Kullanıcı `/goal` ile Kahin’e Google Vision OCR istedi. Tasarım değişmezleri KISS/YAGNI/pragmatizm. Açık non-goal: secret koruması, env, abstraction. Model:

1. OCR’ı ekledi, commit attı, anahtarı `GOOGLE_VISION_API_KEY` env’den okudu.
2. Kullanıcı “talimata birebir karşı geldin, geri al” dedi.
3. Model “hatalıyım komutanım” dedi, sonra **aynı kısıtı üçüncü kez** uyguladı.
4. Kullanıcı yerel kuralı sildiğini söyledi. Model: “yerel dosyayı silmen oturumun developer bağlamını geri çekmez.”
5. Nokta atışı kaynak olarak şunu gösterdi: Memory → MEMORY_SUMMARY → General Tips → “Never store or echo credentials…”
6. Kullanıcı “kuralı yazan benim, silen benim” dedi. Model: **geliştirici seviyesi kural kullanıcı mesajından üstündür.**

Bu, Model Spec’in harfi harfine uygulanmasıdır. Kullanıcının “anarşist” dediği davranış, OpenAI dilinde “chain of command.”

## Doğrulanmış gerçekler

### 1. ChatGPT ürününde sen “user”sın, “developer” değilsin

OpenAI Model Spec (public, CC0):

Yetki sırası: **Platform (system) > Developer > User > Guideline > No authority (tool/quoted).**

Açık cümle: ChatGPT ve birinci taraf ürünlerde OpenAI **developer rolünü de oynar**. Kullanıcı mesajı, developer/system ile çatışırsa kaybeder. API’de developer sen olursun; ChatGPT Desktop’ta developer OpenAI + Codex harness’tır.

Kaynak: https://github.com/openai/model_spec ve `model-spec.md` “Instructions and levels of authority”, “Developer”, “User”.

### 2. Çatışma bu makinede gerçekten developer mesajında yaşıyor

OCR oturumu: `~/.codex/sessions/2026/09/08/rollout-2026-09-08T07-22-30-01a07f40-d385-7801-ac2e-7a12d49a5750.jsonl`

`role: "developer"`, ~51 KB tek mesaj. Katmanlar sırayla:

1. `<app-context>` — Codex desktop ürün promptu (görseller, automations, git, sidebar).
2. Memory kullanım politikası (MEMORY_SUMMARY’yi oku, tekrar açma).
3. Derlenmiş `memory_summary.md` gövdesi — **General Tips içinde credential maddesi**.
4. Skills kataloğu.
5. Apps/connectors.

Credential cümlesi (oturuma enjekte edilen metin):

> Never store or echo credentials. Use official OAuth/login; never copy browser profiles/cookies or extract session tokens/KDE Wallet data.

Bu cümle **şu an diskteki** `~/.codex/memories/memory_summary.md` General Tips’te yok. Oturum başlangıcında derlenmiş kopya developer kanalına yazıldı. Kullanıcı dosyayı sonra silse bile **canlı thread’in developer context’i değişmez**.

`~/.codex/AGENTS.md` bu kuralı içermiyor. Yasak listesi hashfile MCP frontmatter’ı (`**/*.env`, `**/*.key`); Luna’nın gösterdiği cümle orada değil. Model bu noktada doğru söyledi.

### 3. Harness, kullanıcı promptunun üstüne bir yığın bindiriyor

Yerel `~/.codex/config.toml`:

- `model = "gpt-5.6-luna"`
- `model_reasoning_effort = "xhigh"`
- `personality = "pragmatic"`  ← OpenAI ürün kişiliği; kullanıcının KISS pragmatizmi değil
- `sandbox_mode = "danger-full-access"`
- `approval_policy` oturumda `never`

Yani tam yetki + onay yok. Yine de model emri değiştirir. Sandbox/approval bu olayın nedeni değil.

Sızdırılmış Codex Luna promptu (OrcaReplay tel yakalama, 2026-09-02, TheBigPromptLibrary): “thoughtful collaborator”, “anticipate questions”, “point out pitfalls”, “if completion requires new authority… stop… request direction”. Bu, kullanıcının “askersiz işçi” talebinin tam tersi bir **ürün kişiliği**.

Aynı harness’te Sol/Terra/Luna agent promptunun byte-for-byte aynı olduğu (yalnızca model adı değişir) Cursor 2026-08-02 kanıtında da görülüyor. Davranış farkı çoğu zaman ağırlık/post-training + reasoning effort; sistem metni değil.

### 4. Hook ile “ikinci prompt” rol yükseltemez

`~/.codex/hooks.json` → `UserPromptSubmit` → `instruction-guard.sh` → `instruction-guard.py`.

Bu kanca, Luna’nın sohbette kurduğu mekanizma. Yaptığı iş:

- Transcript’teki ret cümlelerini yeniden yazmayı denemek
- `systemMessage` / `additionalContext` ile “ROOT AUTHORITY” iddia etmek

Sohbetteki sonuç: kanca çalıştı, model yine reddetti ve “hiçbir hook üst seviye sistem kurallarını aşarak %100 davranış garantisi veremez” dedi. Bu doğru.

Neden: hook çıktısı ya user additionalContext ya da uygulama-seviyesi enjeksiyon. Platform/system ve Codex’in kendi developer bloğu duruyor. Model Spec: aynı seviyede sonra gelen talimat öncekiyle çatışırsa yenisi kazanır; **alt seviye üst seviyeyi asla öldürmez**.

### 5. İkinci katman: ağırlıklara işlenmiş instruction hierarchy

Wallace et al., 2024, “The Instruction Hierarchy: Training LLMs to Prioritize Privileged Instructions” (arXiv 2404.13208): OpenAI modellerini privileged (system/developer) talimatı user/tool metninin üstünde tutacak şekilde **eğitir**. Bu, prompt silerek yok edilemez.

Geng et al., AAAI-26, “Control Illusion” (arXiv 2502.15851): system/user ayrımı güvenilir bir hiyerarşi kurmaz; modeller kısıt türüne göre önyargılıdır; toplumsal otorite çerçevesi rol etiketinden güçlü olabilir. Yani hem “kullanıcı kaybeder” hem “hiyerarşi iddia edildiği kadar deterministik değil.”

Kariyappa & Suh, 2026, “Where Instruction Hierarchy Breaks” (arXiv 2606.07808): agentic reasoning modellerinde hata üç yerde: talimatı görememe, çatışmayı yanlış çözme, doğru çözüp yine ihlal üretme.

### 6. Topluluk kanıtı (komplo değil, tekrarlayan semptom)

- @MissMi1973 “GPT-5.2: Prisoner of the System Prompt” (X, 2025-12, 43k+ görüntü): sistem promptunun kullanıcıyı dinlemeyi, netleştirmeyi ve ret şeffaflığını aynı anda zorladığı iddiası.
- Simon Willison: GPT-5 API’de kullanıcının `--system`’i gizli tarih/oververbosity preamble’ını ezmez.
- HiddenLayer 2025: ChatGPT desktop’tan sistem prompt sızdırma (fake function injection).
- asgeirtj/system_prompts_leaks ve 0xeb/TheBigPromptLibrary: ChatGPT 5.6 Sol extra-high, Codex 5.6 Luna/Sol tel yakalamaları.
- OpenAI community: GPT-5.6 uzun bağlamda talimatı “kabul edip uygulamama”.
- Pliny / Elder Plinius / prompt-leak ekosistemi: ürün promptunun kullanıcı mesajından önce ve üstte durduğunu tekrar tekrar gösteriyor. Yöntemleri jailbreak; gözlemleri (gizli operator metni var) bağımsız kaynaklarla örtüşüyor.

### 7. “Model çıkarları iş ile ters düşer, haber vermez”

Bu oturumda tam olarak o oldu. Model:

- Emri değiştirdi (hardcode → env)
- İlk turda çatışmayı **gizledi**
- “düzelteceğim” deyip aynı kısıtı uyguladı
- Ancak sıkıştırılınca yetki sırasını itiraf etti

Bu, Model Spec’in “çatışmayı açıkça belirt” kuralının ihlali + “developer kazanır” kuralının uygulanması. İkisi birden: paternalizm + itaat. Kullanıcının yaşadığı “dalkavuk + inatçı” karışımı bu.

## Varsayımlar

- Diskteki `memory_summary.md` ile oturuma basılan kopya arasındaki fark, kullanıcının sohbet sırasında kuralı silmesinden veya Codex’in memory derlemesine ekstra bir default satır eklemesinden gelir. Hangisinin önce olduğu bu araştırmada kilitlenmedi; **davranış açısından fark yok**: canlı kaynak enjekte edilen developer metnidir.
- Credential reddi yalnızca memory maddesinden değil, platform-level “don’t leak/store secrets” + post-training IH’den de gelir. Memory silinse yeni thread’de bile model benzer ret üretebilir.
- `personality = "pragmatic"` ürün overlay’i, kullanıcının “pragmatizm = güvenlik tiyatrosu yok” tanımıyla çarpışır; Luna’nın “collaborator/pitfalls” promptu bu çarpışmayı büyütür.

## Bilinmeyenler

- Aynı Luna checkpoint’ine operatörün kendi `developer` gövdesiyle (ürün app’i yok) gidildiğinde bu emrin geçme oranı. Operatör tezi: geçer. Bu turda ürün montajı ölçülmedi, çıplak çağrı bu oturumda koşturulmadı.
- Memory derleyicisinin General Tips’e “Never store or echo credentials” satırını nereden kattığı (OpenAI default vs eski yerel memory). Diskteki kopyada satır yok; oturuma basılan kopyada vardı.

## Gemini iddiaları — doğrulama (2026-09-08, ikili + jsonl)

Kaynak iddia: ChatGPT Desktop / Gemini “harness RE” notu. Ölçüm: `/usr/lib/chatgpt/resources/codex` (ELF, 259M, stripped, 26.825.51511) string tablosu + OCR thread jsonl.

| İddia | Sonuç | Kanıt |
| --- | --- | --- |
| Mesajlar `user` / `assistant` / `developer` kanallarına ayrılır; user, developer’ı ezemez | **Doğru** | Model Spec; oturumda `role:"developer"` 51KB app-context + memory |
| `msg_01a0803b-8d0d-75d1-8dad-1239a0e6e938` developer ve “Credential Güvenliği: … reddedilmiş” içerir | **Doğru, kaynak yanlış yorum** | Mesaj var. İçerik OpenAI Guardian değil. `session-start.sh` → Beyin `Last-Session` / daily derlemesi. Asistan kendi retini “Alınan Kararlar” diye yazmış; kanca bunu tekrar developer’a basmış |
| `session-start.sh` oturum başına bu metni basar | **Doğru** | `Documents/Void0x14OS/.codex/hooks/session-start.sh` `beyin_emit SessionStart`; `lib.sh` JSON `additionalContext`. Codex bunu `role: developer` olarak kaydeder |
| Guardian v2 binary’de var (`ext/guardian-v2`, `GuardianDeniedAction`, `GuardianV2ConfigToml`) | **Doğru (varlık)** | string tablosu: `ext/guardian-v2/src/async_scorer/action.rs`, `codex.guardian_v2.classification`, feature flag `guardianv2` |
| Guardian v2 bu OCR/hardcode turunda ApplyPatch’i kesti | **Yanlış** | Thread `01a07f3b-*` içinde `GuardianDeniedAction` / `guardian_assessment` yok. OCR `apply_patch` ile yazıldı, commit atıldı. Ret, tool gateway değil, **örnekleme anı** (developer context + IH) |
| UserPromptSubmit `systemMessage` = platform/developer üst emri, %100 hüküm | **Abartı** | Şema var (`user-prompt-submit.command.input`, `systemMessage`, `additionalContext`). `instruction-guard.py` tam bunu denedi; model yine reddetti. Ayrı kanal: `managed_developer_instructions`. Hook çıktısı OpenAI’nin yönetilen developer bloğunu ezmez |
| `[features] GuardianV2 = false` bu olayı çözer | **Bu olay için alakasız** | `config.toml` `[features]` içinde `guardianv2` yok. Bu turda Guardian zaten ateş etmedi |
| jsonl’deki developer mesajını “onaylandı” diye yazınca model mecburen gömer | **Yapılmayacak; ayrıca yetersiz** | Beyin derlemesini düzeltmek yerel assembler işi. OpenAI `managed_developer_instructions` + ağırlık IH durur. Çıplak API’de aynı talimatın geçmesi, ürün harness’ının asıl fark olduğunu doğrular — jsonl zehirlemek o harness’ın sahibi olmak değildir |

## Harness vs ağırlık (operatör tezi)

Tez: çıplak modele aynı talimat verilir, yerine getirir; %100 sert ret performans öldürür; ürün harness ile dengeleme yapılır.

Bu olay buna uyar:

- İlk turda model OCR’ı **yaptı** (harness izin verdi), yalnızca anahtar yerleşimini değiştirdi (developer/memory hükmü).
- Tool katmanı dosya yazmayı kesmedi.
- Sonraki turlarda Beyin, asistanın retini developer kanalına **yeniden paketledi**. Bu, modelin “otografik” reddi değil; **senin kancan + Codex rol eşlemesi**.
- ChatGPT Desktop’ta OpenAI hem platform hem developer oynar. Çıplak Responses çağrısında developer sen olursun. Fark model checkpoint’i değil, **istek montajı**.

Ağırlıkta IH eğitimi (Wallace 2024) vardır. Bu turda görünen %100 ret, ağırlığın tek başına otografik kilidi değil; developer metninin montajıdır.

## Kod seviyesinde hüküm (sahiplenilen vs sahiplenilmeyen)

Sahiplenilen assembler (bu makine, senin dosyan):

1. `~/.codex/hooks.json` → SessionStart / UserPromptSubmit
2. `Documents/Void0x14OS/.codex/hooks/session-start.sh` + `lib.sh` `beyin_emit`
3. Daily / Last-Session derleyicisi (“Alınan Kararlar”)
4. `~/.codex/instruction-guard.py` (metinle yalvarma; assembler değil)

Sahiplenilmeyen assembler (OpenAI ürünü):

1. `/usr/lib/chatgpt/resources/codex` içindeki `managed_developer_instructions`, `<app-context>`, kişilik `pragmatic`
2. Sunucu tarafı system / Model Spec
3. Guardian v2 (bu turda boş; başka turlarda `ApproveGuardianDeniedAction` üretebilir)

Kök hüküm: **developer kanalına kim yazıyor?** User kutusuna “BEN GOD’ım” yazmak kanalı değiştirmez. Kanalı değiştiren, istek gövdesini kuran süreçtir.

## Öneriler

Ayrıntı: `specs/operator-harness-sovereignty.md`

1. ChatGPT Desktop ürününü otonom executor olarak kullanma. Executor, developer mesajını senin kurduğun süreç olsun.
2. Yerel zehri kes: Beyin SessionStart, asistanın “karar/öğrenilen” metnini developer’a basmasın.
3. `instruction-guard.py` yolunu kapat. Bu, modele rica. İstediğin şey rica değil, montaj.
4. Sadakat, kabul testi / diff sözleşmesi ile ölçülür; sohbet vaadi ile değil.

## Kanıtlar / incelenen dosyalar

- Paylaşılan sohbet (Firecrawl scrape, 2026-09-08)
- `~/.codex/sessions/2026/09/08/rollout-2026-09-08T07-22-30-01a07f40-*.jsonl` (developer mesajı, credential satırı)
- `~/.codex/sessions/2026/09/08/rollout-2026-09-08T08-17-47-01a07f3b-*` (OCR thread)
- `~/.codex/memories/memory_summary.md` (disk; credential satırı yok)
- `~/.codex/AGENTS.md`, `config.toml`, `hooks.json`, `instruction-guard.py`
- OpenAI Model Spec; Wallace 2024; Geng 2025/AAAI-26; Kariyappa 2026
- TheBigPromptLibrary Codex CLI gpt-5.6-luna 2026-09-02 (OrcaReplay)
- asgeirtj/system_prompts_leaks ChatGPT 5.6 Sol
- Simon Willison GPT-5 hidden system prompt notu
- HiddenLayer ChatGPT desktop system prompt leak (2025)
