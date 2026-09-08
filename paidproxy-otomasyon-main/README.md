# Proxy Pipeline

Otonom proxy kesif hatti.

Nasil calistirirsin: **[CALISTIR.md](CALISTIR.md)**
Mimari (eski isin nereye dustugu, ajan nereye takilir): **[MIMARI.md](MIMARI.md)**

PYTHONPATH / `python3 -m` yazmak zorunda degilsin.

```bash
./pipeline kur
./pipeline kesfet as64500 --kanit '{"asn":64500,"cidr":"1.2.3.0/24"}'
./pipeline tara 1.1.1.0/24 --dry-run
./pipeline panel
```

- Asama 1 = senin eski hedef avin. Ajan yoksa durur.
- Ajan kancasi: `src/proxy_pipeline/agents/tak.py` veya `PIPELINE_AJAN` veya `OPENAI_API_KEY`
- Masscan bu repoda yok. Makineye kur, `tara` onu cagirir.
- Bos hedef listesi = tum adres evreni.
