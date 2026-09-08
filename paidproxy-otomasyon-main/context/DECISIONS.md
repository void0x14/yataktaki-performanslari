# Mimari ve Tasarım Kararları (ADR)

## ADR-001: 4 Aşamalı Bağımsız Ayrım
- **Karar:** Keşif (Aşama 1), L4 Tarama (Aşama 2), L7 El Sıkışması (Aşama 3) ve Panel (Aşama 4) tamamen izole edilmiştir.
- **Gerekçe:** Ajan doğrudan masscan komutunu veya socket el sıkışmasını yönetmez. Yalnızca hedef ve port manifestini üretir. Bu sayede L4 ve L7 güvenilir, deterministik ve yüksek performanslı kalır.

## ADR-002: Project-Orchestration Skill Entegrasyonu
- **Karar:** Projedeki tüm karmaşık geliştirmeler `.codex/skills/project-orchestration/SKILL.md` kurallarına göre yürütülür.
- **Gerekçe:** Bağlam disiplini sağlamak, kod regresyonlarını önlemek ve araştırma/uygulama/inceleme adımlarını bağımsız kılmak.

## ADR-003: ChatGPT Desktop otonom executor değildir
- **Karar:** ChatGPT Desktop / Codex app (`/usr/lib/chatgpt/resources/codex`) paidproxy otonom yürütücü sayılmaz. Executor, operatörün `developer` kanalını kurduğu süreçtir. Ürün katmanı hem platform hem developer oynar; user kutusundaki emir o kanalları ezmez.
- **Gerekçe:** 2026-09-08 Luna OCR oturumu. Model tool’u yazdı, emri env’ye kaydırdı. Guardian bu turda ateş etmedi. Ret, Beyin SessionStart + Codex’in `additionalContext` → `role: developer` eşlemesi + OpenAI yönetilen developer bloğu. Çıplak model / çıplak API aynı talimatı ürün harness’ı olmadan taşır.
- **Reddedilen:** UserPromptSubmit ile “kök yetki” metni basmak; jsonl zehirlemek; ikiliye yama; sapmayı “model kaprisi” saymak.
- **Yeniden değerlendirme:** Executor süreç değişirse (kendi montajın, yerel ağırlık) bu ADR fiilen uygulanmış olur. ChatGPT Desktop içinde kalarak yeniden değerlendirilmez.
