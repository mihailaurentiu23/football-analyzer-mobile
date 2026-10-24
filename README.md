# Football Analyzer Mobile 1.0 — iPhone / PWA

Versiune mobilă separată de **Football Analyzer 4.13 pe Fedora**. Nu este un fișier `.ipa` și nu se instalează ca aplicație nativă iOS: este o **PWA** (aplicație web adăugată pe ecranul principal) care funcționează prin Safari pe iPhone, de oriunde, după publicarea pe un server HTTPS.

## Ce include

- Interfață pentru telefon în română, cu navigare **Meciuri · Caută · Istoric**.
- Programul și rezultatele pentru Premier League, La Liga, Serie A, Bundesliga și Ligue 1.
- Calculul mediilor și al probabilităților sportive prin model Poisson, pe meci, gazde și oaspeți, bazat pe ultimele 10 partide disponibile.
- Statistici ESPN pentru meciuri finalizate și profiluri de jucători din rapoartele descărcate.
- Formații ESPN confirmate și, dacă lipsesc, ultimul XI verificabil. Nu există formații probabile inventate. Pe teren apar doar formațiile cu sloturi ESPN recunoscute; altfel apare o listă ordonată.
- Arhivarea estimărilor **numai înainte de meci** și evaluare după rezultat, când statisticile reale sunt disponibile.
- Actualizare la pornirea serverului, aproximativ din 45 în 45 de minute **cât timp serverul funcționează**, și manual din aplicație.
- Cod de acces `APP_ACCESS_TOKEN`, opțional local și recomandat obligatoriu pentru un server public.
- Offline: doar interfața PWA rămâne în cache; datele sportive necesită internet și server online.

Datele vin dintr-un endpoint JSON ESPN neoficial, care poate deveni indisponibil sau poate limita cererile. Verifică permisiunile/licențierea înainte de distribuire publică. Nu există garanții de acoperire sau precizie.

## 1. Pornește pe Fedora, pentru test

În terminal, în folderul extras din ZIP:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 8000
```

Deschide `http://127.0.0.1:8000`. Pentru server local cu cod de acces, înainte de pornire setează:

```bash
export APP_ACCESS_TOKEN='alege-un-cod-lung-si-privat'
```

În prima sesiune, sincronizarea ESPN începe automat. Poate dura puțin până când apar meciurile. În cazul erorilor de rețea, aplicația nu generează meciuri fictive.

Baza locală se află în `data/football_analyzer.db`. Nu include în Git/ZIP baza ta cu date personale; folderul `data/` este ignorat de Docker și Git.

## 2. Folosește-o pe iPhone de oriunde

Pentru acces independent de laptop, publică aplicația pe un server HTTPS **care rămâne online**. Proiectul include Dockerfile și două variante Render:

**A. Test / gratuit (`render.yaml`):**

1. În Fedora, creează un repository privat nou pe GitHub și încarcă *doar fișierele proiectului*, nu folderul `data`.
2. Pe [Render](https://render.com), conectează repository-ul și creează un **Blueprint** cu `render.yaml` sau un **Web Service** Docker.
3. Render construiește containerul și îți oferă un URL HTTPS `https://...onrender.com`.
4. În setările serverului, găsește valoarea generată pentru `APP_ACCESS_TOKEN`; vei introduce acest cod numai pe propriile dispozitive.
5. Accesează URL-ul în Safari pe iPhone → **Share → Add to Home Screen → Open as Web App → Add**.

**Limitarea importantă a versiunii gratuite:** pe Render Free, aplicația poate adormi după inactivitate, poate avea întârzieri la reluare, iar **SQLite local este temporar**: arhiva estimărilor și datele salvate se pot pierde la repornire sau redistribuire. Nu îl folosi drept arhivă durabilă.

**B. Pentru utilizare durabilă (`render-persistent.yaml`, plan plătit):**

Folosește un server cu stocare persistentă montată la `/app/data`, de exemplu serviciul configurat în `render-persistent.yaml` (plan `starter` + disk, cu tarif). Verifică prețul exact înainte de activare. Astfel datele SQLite supraviețuiesc repornirilor; se recomandă și backup periodic. Alternativ, configurează un VPS cu volum persistent și HTTPS.

**Important:** Nu am făcut deploy în contul tău și nu am creat un URL public. Acești pași necesită acțiunea ta în contul de găzduire; înainte de ei aplicația va funcționa doar local.

## 3. Despre datele de pe Fedora

Aplicația mobilă are baza ei SQLite, pe server. **Nu sincronizează automat în ambele sensuri** cu versiunea JavaFX instalată pe Fedora. Poți importa manual o copie a unei baze desktop compatibile, după oprirea serverului, utilizând `scripts/import_desktop_db.py`; această operație *înlocuiește baza mobilă* și nu trebuie folosită fără backup.

Acest pachet nu schimbă instalarea Football Analyzer 4.13 existentă. Nu conține API de case de pariuri, cote sau posibilitate de plasare a pariurilor.

## 4. Teste

```bash
pip install pytest
python -m pytest -q tests/
node --check static/app.js
```

Testele verifică parsarea scorurilor, lipsa valorilor inventate, identitatea portarului, calculul probabilităților și păstrarea estimărilor realizate înainte de start. Ele folosesc exemple sintetice, **nu verifică direct ESPN live**. Rularea completă pe un iPhone trebuie confirmată după găzduire.

## Notă de securitate și operare

- Nu publica tokenul `APP_ACCESS_TOKEN` în repository sau în capturi de ecran.
- Serverul oferă date ESPN și calcule statistice; modelele nu sunt certitudini.
- Utilizarea unui endpoint ESPN neoficial poate fi blocată, schimbată sau restricționată; nu face scraping intensiv.
- Pentru date private sau accesul altor persoane ar fi necesar un sistem de conturi și autorizare mai robust.
