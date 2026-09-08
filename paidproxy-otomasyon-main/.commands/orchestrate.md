---
description: "Kapsamlı veya belirsiz çalışmalar için proje orkestrasyon politikasını (Araştırma, Sentez, Şartname, Uygulama, İnceleme) çalıştırır."
---

# Proje Orkestrasyonu

Kapsamlı veya belirsiz kodlama çalışmaları için proje orkestrasyon politikasını devreye sok.

Bu yeteneğin tam kuralları: `.codex/skills/project-orchestration/SKILL.md`

## Yürütme Akışı

1. **Araştırma:** Eksik bağlam ve gerçekleri topla, gerekiyorsa `reports/` altına kaydet.
2. **Sentez:** Gerçekler ile varsayımları ayır, çelişkileri çöz.
3. **Teknik Şartname (Spec):** Uygulamaya başlamadan önce `specs/<gorev>.md` oluştur/güncelle.
4. **Uygulama:** Şartnameye birebir sadık kalarak kodu uygula.
5. **Bağımsız İnceleme:** Doğrulama testlerini çalıştır (`pytest tests -q`), şartnameye uygunluğu ve regresyon riskini bağımsız incele (`GEÇTİ` / `KALDI`).

## Görev / Girdi
$ARGUMENTS
