# Franchise Gyógyszertár Scraper és Adatbázis Integráció

Ez a projekt 9 különböző magyarországi gyógyszertár franchise (pl. Alma, Benu, Pingvin, Kulcs, PatikaPlus stb.) adatait tölti le, normalizálja egy egységes formátumra, és szinkronizálja egy MS-SQL adatbázissal. A rendszer beépített verziókövetéssel (history) és okos (fuzzy text + geolokációs) patika azonosítással rendelkezik.

## A futtatás menete (Workflow)

A teljes rendszer szinkronizálásához az alábbi három szkriptet kell lefuttatni, a megadott sorrendben. Az ideális használat érdekében ezeket akár egy `.bat` fájlba is össze lehet fűzni automatizáláshoz.

### 1. Adatok letöltése
```bash
python .\fetch_data.py
```
**Mit csinál?** 
Végigmegy az előre integrált 9 franchise webes forrásán (REST API-k, GraphQL, és kapart HTML/JS adatok). Letölti a napi legfrissebb adatokat, és a nyers választ elmenti egy helyi `urls.json` fájlba.

### 2. Adatok normalizálása és elmentése
```bash
python .\normalize_and_save.py
```
**Mit csinál?** 
- Beolvassa a `urls.json` nyers formátumait és egy egységes, lapos adatstruktúrára hozza őket.
- Kiszámol egy SHA-256 hasht az adatok alapján, így észleli, ha egy patika adatai (pl. nyitvatartás, telefonszám) megváltoztak a legutóbbi futtatás óta.
- Elmenti az eredményeket az MS-SQL szerveren lévő `[Franchise].[WebScrapedData]` táblába.
- Ha az adatok módosultak (vagy egy patika inaktívvá vált), az előző állapotot archiválja a `[History].[Franchise_WebScrapedData]` táblába.
- **Manuális adatok megőrzése:** Ha az adatbázisban a `Note` mezőbe kézzel megjegyzést írtunk (pl. "Ez a patika végleg bezárt"), a szkript felismeri és átmenti az új rekordba, így az sosem vész el!

### 3. Központi Patika ID összerendelés (Fuzzy Matching)
```bash
python .\match_patika_id.py
```
**Mit csinál?** 
- Összeszedi a `[Franchise].[WebScrapedData]` táblából azokat a sorokat, amelyeknél még nincs kitöltve a `PatikaId`.
- Beolvassa a központi, teljes adatbázist a `[dbo].[patikak]` táblából.
- Földrajzi távolság (Haversine-algoritmus) és név/cím hasonlóság kód (difflib ngram matching) alapján megpróbálja társítani az online levadászott patikát a hivatalos nyilvántartással.
- A magas megbízhatóságú találatokat automatikusan frissíti a `[Franchise].[WebScrapedData]` táblában.

---

## Konfiguráció
A rendszer az adatbázis hozzáféréshez környezeti változókat használ. A futtatáshoz szükséges egy `.env` fájl a gyökérben a következő tartalommal:

```env
DB_CONNECTION_STRING="Driver={ODBC Driver 17 for SQL Server};Server=<SZERVER_CIME>;Database=<ADATBAZIS>;UID=<FEHASZNALO>;PWD=<JELSZO>;"
```

## Manuális adminisztráció (Tipikus feladatok)
- **Sikertelen összerendelések:** Ha a 3. lépés (match) után maradnak `PatikaId` nélküli sorok, azok jellemzően már megszűnt gyógyszertárak, vagy extrém módon eltér a címük a központi regiszterben.
- **A `Note` mező használata:** A `[Franchise].[WebScrapedData]` tábla megjegyzés oszlopába biztonságosan írhatunk kézzel (pl. SQL Server Management Studio-ban), a Python scraper felismeri és megőrzi ezeket a sorok következő frissítésekor.