# Calistir

PYTHONPATH yok. `python3 -m` yok. `./pipeline` yaz.

## 1. Bir kere

```bash
cd /path/to/paidproxy-otomasyon
python3 -m pip install -e ".[dev]"
sudo apt install masscan    # veya: sudo dnf install masscan
which masscan
chmod +x pipeline
./pipeline kur
```

`which masscan` bos donerse `tara` patlar. `--masscan-bin /tam/yol/masscan` ver.

## 2. Dort komut

```bash
./pipeline kur
./pipeline kesfet as64500 --kanit '{"asn":64500,"cidr":"1.2.3.0/24"}'
./pipeline tara 1.2.3.0/24 -p 3128,8080,1080
./pipeline panel
```

`./pipeline` argsuz = yardim.

## 3. Asama 1 — senin eski hedef avin

Ajan yoksa durur. Uydurma skor yok.

```bash
./pipeline kesfet as64500
# AJAN YOK. Tak: src/proxy_pipeline/agents/tak.py  veya  OPENAI_API_KEY / PIPELINE_AJAN
```

Ornek ajanla dene (uretim beyni degil):

```bash
PIPELINE_AJAN=proxy_pipeline.agents.ornek:OrnekAjan \
  ./pipeline kesfet as64500 --kanit '{"asn":64500,"cidr":"1.2.3.0/24","ports":[3128,8080]}'
```

Kendi beynin:

1. `src/proxy_pipeline/agents/tak.py` ac
2. `decide(self, context)` yaz — CIDR, port, ne kadar tara
3. alta `ajan = BenimAjan()`
4. `./pipeline kesfet as64500 --kanit '{...}'`

veya:

```bash
export OPENAI_API_KEY=...
# istege: export OPENAI_BASE_URL=...
# istege: export PIPELINE_MODEL=gpt-5
./pipeline kesfet as64500 --kanit '{"asn":64500}'
```

Karar CIDR verirse hemen tara:

```bash
PIPELINE_AJAN=proxy_pipeline.agents.ornek:OrnekAjan \
  ./pipeline kesfet as64500 --kanit '{"cidr":"1.2.3.0/24"}' --tara
```

## 4. Asama 2 — masscan

Once komutu gor, calistirma:

```bash
./pipeline tara 1.1.1.0/24 --ports 3128,8080,1080 --dry-run
```

Ekrana `masscan 1.1.1.0/24 -p 3128,8080,1080 ...` duser.

Gercek tarama (masscan cogu Linux'ta root ister):

```bash
sudo ./pipeline tara 1.1.1.0/24 -p 3128,8080,1080,80,8888 --rate 1000 --cikti var/spool/l4-open.txt
```

Cikti: `var/spool/l4-open.txt` — satir: `IP PORT OPEN`

Tum IPv4:

```bash
sudo ./pipeline tara 0.0.0.0/0 -p 3128,8080,1080 --rate 10000
```

Kendi makinende, kendi riskin. Bos hedef listesi = her CIDR.

## 5. Panel

```bash
./pipeline panel
```

Tarayici: `http://127.0.0.1:8080`
Bu ekran durum gosterir. Masscan baslatmaz.

## 6. Klasorler

| yol | ne |
| --- | --- |
| `./pipeline` | kisa giris. PYTHONPATH gerekmez |
| `src/proxy_pipeline/agents/tak.py` | ajan kancasi. senin beyin |
| `src/proxy_pipeline/agents/ornek.py` | calisan ornek. kopyala |
| `src/proxy_pipeline/agents/loader.py` | PIPELINE_AJAN / tak / OPENAI_API_KEY |
| `src/proxy_pipeline/scanners/runner.py` | masscan'i calistirir |
| `var/db/` | sqlite |
| `var/spool/l4-open.txt` | acik port listesi |
| `MIMARI.md` | kutular, ajan, eski isin nereye dustugu |

## 7. Test

```bash
./pipeline --help
python3 -m pytest tests -q
```

pytest PYTHONPATH istemez; `pyproject.toml` icinde ayarli.
