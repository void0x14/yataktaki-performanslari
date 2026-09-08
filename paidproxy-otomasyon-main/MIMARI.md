# Mimari — senin eski isi bu meret nereye koyuyor

Kisa. Ingilizce kelime yok. Yalan yok.

## Sen eskiden ne yapiyordun

1. myip.ms / BGP / ASN / prefix / port bakardin.
2. Sezgiyle yuksek degerli hedef secerdin.
3. Masscan ile o CIDR'i tarardin.
4. Acik porta CONNECT / SOCKS denerdin.
5. Ise yarayanlari tutardin.

Bu dort adim sistemde dort kutu. Karistirma.

```
  [Asama 1 — kesfet]          senin tasakli hedef secimin
         |
         |  ajan CIDR + port + ne kadar tara diye karar verir
         v
  [Asama 2 — tara]            masscan. L4. port acik mi.
         |
         v
  [Asama 3 — L7]              CONNECT / SOCKS el sikismasi. Ajan yok.
         |
         v
  [Asama 4 — panel]           SQLite, kuyruk, ekran. Tarama yapmaz.
```

Ajan **sadece Asama 1**. Masscan'e dokunmaz. El sikismasina dokunmaz.
Ajan yoksa Asama 1 durur. Uydurma skor formulu yok. Bu kasitli.

## Komutlar = kutular

| senin eski is | komut | ne yapar |
| --- | --- | --- |
| ASN/prefix/port sec, ne kadar tara | `./pipeline kesfet as64500 --kanit '{...}'` | ajan karar verir, manifest yazar |
| masscan calistir | `./pipeline tara 1.2.3.0/24 -p 3128,8080` | L4. ajan yok |
| panel bak | `./pipeline panel` | web. tarama yok |
| db kur | `./pipeline kur` | bir kere |

`kesfet --tara` = Asama 1 + hemen masscan. Ajan hedef vermezse masscan calismaz.

PYTHONPATH / `python3 -m` yazmak zorunda degilsin. `./pipeline` yeter.

## Ajan nereye takilir

Tek kanca. Uc yol. Ilk dolu olan kullanilir.

1. **Dosya** — `src/proxy_pipeline/agents/tak.py`

   ```
   class BenimAjan:
       version = "1"
       def decide(self, context):
           # context.snapshot = ASN, prefix, kanit, gecmis
           return {action, targets, resource_plan, stop_condition, items}
   ajan = BenimAjan()
   ```

2. **Ortam** — `PIPELINE_AJAN=modul:Sinif`
   Ornek ajan (test / kopyala): `PIPELINE_AJAN=proxy_pipeline.agents.ornek:OrnekAjan`

3. **HTTP beyin** — `OPENAI_API_KEY=...` (istege `OPENAI_BASE_URL`, `PIPELINE_MODEL`)
   Bearer basligi LLM hesabi icindir. Tarama kapisi degil.

`decide` sozlesmesi: `src/proxy_pipeline/decision/contracts.py`
Yukleyici: `src/proxy_pipeline/agents/loader.py`
Cagrildigi yer: `DecisionService.decide` → `ControlPlane.request_decision` → `./pipeline kesfet`

Mod grafikleri (tek ajan, yonetici+alt, router, juri, tartisma, insan) `agents/modes.py` icinde.
Canli beyin onlar degil. Canli beyin `load_routes()`. Grafigi doldurmak senin isin: ajanini moda ver, modu `PIPELINE_AJAN` ile tak.

## Veri akisi (tek satir)

kanıt JSON → ajan.decide → DecisionOutput → ExecutionManifest → masscan argv → açık port dosyası → L7 (ayrı) → SQLite

## Hedef yoksa ne demek

AI kararında hedef yoksa tarama başlatılmaz. Hedef ve portlar karar manifestinde görünür.

## Su an calismayan (yalan yok)

- `tak.py` icinde `ajan = None`. Sen takmadikca `kesfet` "AJAN YOK" der, cikar 2.
- Kaynak baglayicilari (myip.ms vs) katalogda kapali. Kaniti `--kanit` ile sen verirsin.
- `tara` L7 dogrulamaz. Sadece port acik mi.
- Masscan binary git'te yok. `apt install masscan`.
