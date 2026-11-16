import os
import pyodbc
import math
import difflib
from dotenv import load_dotenv

def haversine(lat1, lon1, lat2, lon2):
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 999999
    try:
        R = 6371000  # Föld sugara méterben
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))

        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c # Távolság méterben
    except (ValueError, TypeError):
        return 999999

def normalize_text(text):
    if not text:
        return ""
    text = str(text).lower()
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ö': 'o', 'ő': 'o', 'ú': 'u', 'ü': 'u', 'ű': 'u',
        'gyógyszertár': '', 'patika': '', 'és': '', '-': ' ', ',': ' ', '.': ''
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Eltávolítjuk a felesleges szóközöket
    return " ".join(text.split())

def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()

def main():
    load_dotenv()
    server = os.getenv('DB_SERVER')
    database = os.getenv('DB_DATABASE')
    username = os.getenv('DB_USERNAME')
    password = os.getenv('DB_PASSWORD')
    driver = os.getenv('DB_DRIVER', '{ODBC Driver 17 for SQL Server}')
    trusted = str(os.getenv('DB_TRUSTED_CONNECTION')).lower() in ['yes', 'true', '1']

    if trusted:
        conn_str = f"DRIVER={driver};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
    else:
        conn_str = f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password};"

    print("Csatlakozás az adatbázishoz...")
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()

    # 1. Lekérjük a 'Master' adatokat a dbo.patikak táblából
    print("Mester adatok letöltése (dbo.patikak)...")
    cursor.execute("SELECT patika_id, patika_nev, iranyitoszam, varos, utca_hsz, latitude, longitude FROM dbo.patikak")
    master_records = []
    for row in cursor:
        master_records.append({
            'patika_id': row.patika_id,
            'nev': normalize_text(row.patika_nev),
            'iranyitoszam': str(row.iranyitoszam).strip() if row.iranyitoszam else "",
            'varos': normalize_text(row.varos),
            'cim': normalize_text(row.utca_hsz),
            'lat': row.latitude,
            'lon': row.longitude,
            'raw_name': row.patika_nev
        })
    print(f"{len(master_records)} törzsadat betöltve.")

    # 2. Lekérjük az "árva" (PatikaId IS NULL) webes adatokat
    print("Árva lekapart adatok letöltése...")
    cursor.execute("SELECT Id, Name, ZipCode, City, Address, Latitude, Longitude, FranchiseName FROM Franchise.WebScrapedData WHERE PatikaId IS NULL")
    scraped_records = []
    for row in cursor:
        scraped_records.append({
            'id': row.Id,
            'nev': normalize_text(row.Name),
            'iranyitoszam': str(row.ZipCode).strip() if row.ZipCode else "",
            'varos': normalize_text(row.City),
            'cim': normalize_text(row.Address),
            'lat': row.Latitude,
            'lon': row.Longitude,
            'franchise': row.FranchiseName,
            'raw_name': row.Name
        })
    print(f"{len(scraped_records)} párosítatlan webes patika található.")

    matches = []

    # 3. Párosítás
    print("Párosítás folyamatban...")
    for s_rec in scraped_records:
        best_match = None
        best_score = 0
        best_distance = 999999
        
        for m_rec in master_records:
            # Csak akkor foglalkozunk vele, ha legalább a város vagy az irányítószám egyezik / nagyon hasonló
            if s_rec['varos'] and m_rec['varos'] and (s_rec['varos'] in m_rec['varos'] or m_rec['varos'] in s_rec['varos']):
                city_match = True
            elif s_rec['iranyitoszam'] and m_rec['iranyitoszam'] and s_rec['iranyitoszam'] == m_rec['iranyitoszam']:
                city_match = True
            else:
                city_match = False
                
            dist = haversine(s_rec['lat'], s_rec['lon'], m_rec['lat'], m_rec['lon'])
            
            if city_match or dist < 2000: # Max 2km differencia ha elírták a várost
                name_sim = similar(s_rec['nev'], m_rec['nev'])
                addr_sim = similar(s_rec['cim'], m_rec['cim'])
                
                # Súlyozott pontszám: Név hasonlóság + Cím hasonlóság
                score = (name_sim * 0.6) + (addr_sim * 0.4)
                
                # Ha nagyon közel vannak egymáshoz (pl. < 100m) és a város oké, az hatalmas bónusz
                if dist < 100:
                    score += 0.3
                    
                if score > best_score:
                    best_score = score
                    best_match = m_rec
                    best_distance = dist
                    
        # Ha a pontszám elfogadható szintű (pl. 0.6 azaz 60%-os bizonyosság)
        if best_match and best_score >= 0.55:
            matches.append({
                'web_id': s_rec['id'],
                'patika_id': best_match['patika_id'],
                'web_name': s_rec['raw_name'],
                'master_name': best_match['raw_name'],
                'score': best_score,
                'distance_meters': best_distance
            })

    print(f"\n{len(matches)} sikeres találat! Mentés az adatbázisba...")
    
    # 4. Adatbázis frissítése
    for match in matches:
        # A fő tábla frissítése
        cursor.execute("UPDATE Franchise.WebScrapedData SET PatikaId = ? WHERE Id = ?", match['patika_id'], match['web_id'])
        # A History táblában is frissítjük a vonatkozó rekordot, hogy következetes maradjon a reláció
        cursor.execute("UPDATE History.Franchise_WebScrapedData SET PatikaId = ? WHERE Id = ?", match['patika_id'], match['web_id'])

    print("Kész! Az összerendelés befejeződött.")

if __name__ == "__main__":
    main()
