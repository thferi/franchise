import os
import sys
import json
import glob
import pyodbc
import hashlib
from datetime import datetime
from dotenv import load_dotenv

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

try:
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()
except Exception as e:
    print(f"Hiba a DB kapcsolódáskor: {e}")
    sys.exit(1)

def setup_database():
    print("Sémák és táblák ellenőrzése / létrehozása...")
    cursor.execute("""
        IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'Franchise')
        BEGIN
            EXEC('CREATE SCHEMA [Franchise]');
        END
    """)
    cursor.execute("""
        IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'History')
        BEGIN
            EXEC('CREATE SCHEMA [History]');
        END
    """)
    
    # Fő tábla létrehozása
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='WebScrapedData' AND xtype='U' AND uid = SCHEMA_ID('Franchise'))
        BEGIN
            CREATE TABLE Franchise.WebScrapedData (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                PatikaId INT NULL,
                FranchiseName NVARCHAR(100) NOT NULL,
                OriginalId NVARCHAR(255) NOT NULL,
                Name NVARCHAR(255),
                ZipCode NVARCHAR(20),
                City NVARCHAR(100),
                Address NVARCHAR(500),
                Phone NVARCHAR(255),
                Email NVARCHAR(255),
                Facebook NVARCHAR(500),
                Website NVARCHAR(255),
                PharmacyManager NVARCHAR(100),
                Latitude FLOAT,
                Longitude FLOAT,
                OpeningHours NVARCHAR(MAX),
                RawJson NVARCHAR(MAX),
                RecordHash NVARCHAR(255),
                IsActive BIT DEFAULT 1,
                FirstSeenAt DATETIME DEFAULT GETDATE(),
                LastSeenAt DATETIME DEFAULT GETDATE(),
                Note NVARCHAR(MAX)
            )
            -- Egyedi index, amivel könnyű azonosítani a patikát a franchise-on belül
            CREATE UNIQUE INDEX UQ_FranchiseName_OriginalId ON Franchise.WebScrapedData(FranchiseName, OriginalId)
        END
    """)
    
    # History tábla létrehozása (ugyanazok az oszlopok + ValidFrom/To)
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Franchise_WebScrapedData' AND xtype='U' AND uid = SCHEMA_ID('History'))
        BEGIN
            CREATE TABLE History.Franchise_WebScrapedData (
                HistoryId INT IDENTITY(1,1) PRIMARY KEY,
                Id INT NOT NULL,
                PatikaId INT NULL,
                FranchiseName NVARCHAR(100),
                OriginalId NVARCHAR(255),
                Name NVARCHAR(255),
                ZipCode NVARCHAR(20),
                City NVARCHAR(100),
                Address NVARCHAR(500),
                Phone NVARCHAR(255),
                Email NVARCHAR(255),
                Facebook NVARCHAR(500),
                Website NVARCHAR(255),
                PharmacyManager NVARCHAR(100),
                Latitude FLOAT,
                Longitude FLOAT,
                OpeningHours NVARCHAR(MAX),
                RawJson NVARCHAR(MAX),
                RecordHash NVARCHAR(255),
                IsActive BIT,
                FirstSeenAt DATETIME,
                LastSeenAt DATETIME,
                Note NVARCHAR(MAX),
                ValidFrom DATETIME NOT NULL,
                ValidTo DATETIME NULL
            )
        END
    """)

# Regex/segéd a címek szétszedésére
def safe_str(val):
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)

def safe_address(val):
    if not val:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        parts = []
        if val.get('streetName'):
            parts.append(val.get('streetName'))
        if val.get('streetType'):
            parts.append(val.get('streetType'))
        if val.get('streetNo'):
            parts.append(val.get('streetNo'))
        return " ".join(parts).strip()
    return str(val)

def safe_opening(val):
    if not val:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        hours = []
        days_map = {'monday':'Hétfő', 'tuesday':'Kedd', 'wednesday':'Szerda', 'thursday':'Csütörtök', 'friday':'Péntek', 'saturday':'Szombat', 'sunday':'Vasárnap'}
        for eng, hun in days_map.items():
            day_data = val.get(eng, {})
            if isinstance(day_data, dict):
                f = day_data.get('from', '00:00')
                t = day_data.get('to', '00:00')
                if f != '00:00' or t != '00:00':
                    hours.append(f"{hun}: {f} - {t}")
                else:
                    hours.append(f"{hun}: Zárva")
            elif isinstance(day_data, str):
                hours.append(f"{hun}: {day_data}")
        return " | ".join(hours)
    
    return json.dumps(val, ensure_ascii=False)

def get_hash(data_dict):
    keys = ["Name", "ZipCode", "City", "Address", "Phone", "Email", "Facebook", "Website", "PharmacyManager", "Latitude", "Longitude", "OpeningHours"]
    concat = "|".join([safe_str(data_dict.get(k, "")) for k in keys])
    # A RawJson-t is belevesszük a hashbe, hogy ha ott észrevétlen változás van, azt is historyzza
    concat += "|" + safe_str(data_dict.get("RawJson", ""))
    return hashlib.sha256(concat.encode('utf-8')).hexdigest()

def normalize_data():
    all_normalized = []
    
    for file in glob.glob("*_raw.json"):
        with open(file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            
        franchise = file.replace("_raw.json", "").replace("_API", "").replace("_WEB", "").replace("___", " - ").replace("_", " ").strip()
        
        # Determine the array of items based on franchise
        items = []
        if isinstance(raw_data, list):
            items = raw_data
        elif isinstance(raw_data, dict):
            if 'data' in raw_data:
                items = raw_data['data']
            elif 'items' in raw_data:
                items = raw_data['items']
                
        for item in items:
            norm = {
                "FranchiseName": franchise,
                "OriginalId": "",
                "Name": None,
                "ZipCode": None,
                "City": None,
                "Address": None,
                "Phone": None,
                "Email": None,
                "Facebook": None,
                "Website": None,
                "PharmacyManager": None,
                "Latitude": None,
                "Longitude": None,
                "OpeningHours": None,
                "RawJson": json.dumps(item, ensure_ascii=False)
            }
            
            # --- Franchise Specifikus Csomagolás ---
            try:
                if "Alma" in franchise or "Gyongy" in franchise:
                    norm["OriginalId"] = str(item.get('id', item.get('slug')))
                    norm["Name"] = item.get('name')
                    norm["ZipCode"] = str(item.get('zip', ''))
                    norm["City"] = item.get('city')
                    norm["Address"] = item.get('address')
                    norm["Phone"] = item.get('phone')
                    norm["Latitude"] = item.get('latitude')
                    norm["Longitude"] = item.get('longitude')
                    
                elif "BENU" in franchise:
                    norm["OriginalId"] = str(item.get('id'))
                    norm["Name"] = item.get('name')
                    norm["ZipCode"] = item.get('zip_code')
                    norm["City"] = item.get('city')
                    norm["Address"] = item.get('address')
                    norm["Phone"] = item.get('phone_number')
                    norm["Email"] = item.get('email')
                    
                    slug_or_handle = item.get('slug', item.get('handle', ''))
                    if slug_or_handle:
                        norm["Website"] = f"https://benu.hu/{slug_or_handle}"
                    norm["PharmacyManager"] = item.get('pharmacy_ceo')
                    
                    try:
                        norm["Latitude"] = float(item.get('latitude'))
                        norm["Longitude"] = float(item.get('longitude'))
                    except (ValueError, TypeError):
                        pass
                        
                    # BENU complex hours (megpróbáljuk kinyerni textként ha parserhető)
                    if item.get("opening_hours_parsed"):
                        # Ezt most egyszerűsítve csak a dict formát írjuk le, a db-be ok
                        norm["OpeningHours"] = str(item.get("opening_hours_parsed"))
                    else:
                        norm["OpeningHours"] = item.get("opening_hours")
                        
                elif "Kulcs" in franchise:
                    norm["OriginalId"] = str(item.get('patikaid'))
                    if 'poi' in item:
                        norm["Name"] = item['poi'].get('patika')
                        norm["Address"] = item['poi'].get('address')
                        norm["Latitude"] = item['poi'].get('latitude')
                        norm["Longitude"] = item['poi'].get('longitude')
                    
                    norm["Phone"] = item.get('phone_detailed')
                    norm["OpeningHours"] = item.get('opening_hours_detailed')
                    norm["Facebook"] = item.get('facebook')
                    norm["Email"] = item.get('email')
                    
                elif "Szimpatika" in franchise:
                    norm["OriginalId"] = str(item.get('id', ''))
                    norm["Name"] = item.get('name')
                    if 'store' in item:
                        # Ha az address egy object, onnan szedjük az adatokat
                        addr_obj = item['store'].get('address', {})
                        if isinstance(addr_obj, dict):
                            norm["City"] = addr_obj.get('city')
                            norm["ZipCode"] = str(addr_obj.get('ZIPCode', ''))
                            # Használjuk a létező biztonságos címet ami ezt az objectet összefűzi
                            norm["Address"] = addr_obj
                        else:
                            norm["City"] = item['store'].get('city')
                            norm["ZipCode"] = str(item['store'].get('zipCode', ''))
                            norm["Address"] = item['store'].get('address')
                            
                        norm["Latitude"] = item['store'].get('latitude')
                        norm["Longitude"] = item['store'].get('longitude')
                        norm["OpeningHours"] = item['store'].get('openingHours')
                        norm["Phone"] = item['store'].get('phoneNumber')
                        norm["Email"] = item['store'].get('email')
                        
                        urls_arr = item['store'].get('urls', [])
                        if urls_arr and isinstance(urls_arr, list) and 'url' in urls_arr[0]:
                            url_val = urls_arr[0]['url']
                            norm["Website"] = f"https://szimpatika.hu{url_val}/" if not url_val.endswith('/') else f"https://szimpatika.hu{url_val}"
                        
                elif "Csillag" in franchise:
                    norm["OriginalId"] = item.get('name') # Nincs ID-juk
                    norm["Name"] = item.get('name')
                    norm["Address"] = item.get('address')
                    norm["Phone"] = item.get('phone')
                    norm["OpeningHours"] = item.get('opening_hours')
                    norm["Latitude"] = item.get('lat')
                    norm["Longitude"] = item.get('lng')
                    
                elif "Pingvin" in franchise:
                    norm["OriginalId"] = item.get('address') # Cím az egyedi azonosító
                    norm["Name"] = f"Pingvin Patika - {item.get('city', '')}"
                    norm["City"] = item.get('city')
                    norm["Address"] = item.get('address')
                    norm["OpeningHours"] = item.get('opening_hours_detailed')
                    norm["Latitude"] = item.get('lat')
                    norm["Longitude"] = item.get('lon')
                    
                elif "PatikaPlus" in franchise:
                    norm["OriginalId"] = item.get('name') + " - " + item.get('address')
                    norm["Name"] = item.get('name')
                    norm["Address"] = item.get('address')
                    norm["Phone"] = item.get('phone')
                    norm["OpeningHours"] = item.get('opening_hours_detailed')
                    norm["Latitude"] = item.get('lat')
                    norm["Longitude"] = item.get('lon')
                    
                elif "Szirom" in franchise:
                    norm["OriginalId"] = str(item.get('id', ''))
                    norm["Name"] = item.get('title')
                    norm["ZipCode"] = item.get('postal_code')
                    norm["City"] = item.get('city')
                    norm["Address"] = item.get('street')
                    norm["Phone"] = item.get('phone')
                    norm["Email"] = item.get('email')
                    norm["Latitude"] = item.get('lat')
                    norm["Longitude"] = item.get('lng')
                    norm["OpeningHours"] = item.get('opening_hours_detailed')
                    
            except Exception as e:
                print(f"Hiba a {franchise} - {item} normalizálásakor: {e}")
                
            # Generálunk egy belső hash-t a könnyebb változáskövetéshez
            # Ensure complex objects are handled properly
            norm["Address"] = safe_address(norm['Address'])
            norm["OpeningHours"] = safe_opening(norm['OpeningHours'])
            
            norm["RecordHash"] = get_hash(norm)
            all_normalized.append(norm)
            
    return all_normalized

def sync_to_db(records):
    now = datetime.now()
    if not records:
        print("Nincsenek adatok a szinkronizáláshoz!")
        return

    # Betöltjük a jelenlegi Franchise.WebScrapedData memóriába Cache-be dictként (OriginalId + FranchiseName alapú kulcssal)
    cursor.execute("SELECT Id, FranchiseName, OriginalId, RecordHash, IsActive FROM Franchise.WebScrapedData")
    db_cache = {}
    for r in cursor:
        db_cache[f"{r.FranchiseName}_{r.OriginalId}"] = {
            "Id": r.Id,
            "RecordHash": r.RecordHash,
            "IsActive": r.IsActive
        }

    inserted_count = 0
    updated_count = 0
    unchanged_count = 0
    activated_count = 0
    
    # Hagyjuk meg a látott itemeket, hogy a nem látottakat "IsActive=0"-ra rakhassuk
    seen_keys = set()

    for item in records:
        key = f"{item['FranchiseName']}_{item['OriginalId']}"
        seen_keys.add(key)
        
        # Mely oszlopokat inzertáljuk
        cols = ["FranchiseName", "OriginalId", "Name", "ZipCode", "City", "Address", "Phone", "Email", "Facebook", "Website", "PharmacyManager", "Latitude", "Longitude", "OpeningHours", "RecordHash", "RawJson", "IsActive", "FirstSeenAt", "LastSeenAt", "Note"]
        
        vals = [item["FranchiseName"], item["OriginalId"], item["Name"], item["ZipCode"], item["City"], item["Address"], item["Phone"], item["Email"], item["Facebook"], item["Website"], item["PharmacyManager"], item["Latitude"], item["Longitude"], item["OpeningHours"], item["RecordHash"], item["RawJson"], 1, now, now, None]
            
        if key not in db_cache:
            # 1. Teljesen új patika -> INSERT a Main-be + INSERT a History-ba
            q = f'''
                INSERT INTO Franchise.WebScrapedData ({", ".join(cols)})
                OUTPUT inserted.Id
                VALUES ({", ".join(["?" for _ in cols])})
            '''
            cursor.execute(q, vals)
            new_id = cursor.fetchone()[0]
            
            # History log
            h_cols = cols.copy()
            h_cols.insert(0, "Id")
            h_vals = vals.copy()
            h_vals.insert(0, new_id)
            h_cols.extend(["ValidFrom", "ValidTo"])
            h_vals.extend([now, None])
            
            hq = f'''INSERT INTO History.Franchise_WebScrapedData ({", ".join(h_cols)}) VALUES ({", ".join(["?" for _ in h_cols])})'''
            cursor.execute(hq, h_vals)
            inserted_count += 1
            
        else:
            db_row = db_cache[key]
            record_id = db_row["Id"]
            
            # Van változás? (Adat vagy újra aktiválás)
            if db_row["RecordHash"] != item["RecordHash"] or not db_row["IsActive"]:
                # --- HISTORY UPDATE ---
                # A korábbi history rekord lezárása (ahol ValidTo IS NULL)
                cursor.execute("UPDATE History.Franchise_WebScrapedData SET ValidTo = ? WHERE Id = ? AND ValidTo IS NULL", now, record_id)
                
                # --- MAIN UPDATE ---
                upd_cols = ["Name", "ZipCode", "City", "Address", "Phone", "Email", "Facebook", "Website", "PharmacyManager", "Latitude", "Longitude", "OpeningHours", "RecordHash", "RawJson", "IsActive", "LastSeenAt"]
                upd_vals = [item["Name"], item["ZipCode"], item["City"], item["Address"], item["Phone"], item["Email"], item["Facebook"], item["Website"], item["PharmacyManager"], item["Latitude"], item["Longitude"], item["OpeningHours"], item["RecordHash"], item["RawJson"], 1, now, record_id]
                
                # UPDATE a History log Note oszlopának megőrzésével nem töröljük a Mastert de beolvassuk előtte a NOTE mezőt
                cursor.execute("SELECT Note FROM Franchise.WebScrapedData WHERE Id = ?", record_id)
                existing_note = cursor.fetchone().Note
                
                uq = f'''UPDATE Franchise.WebScrapedData SET {", ".join([c + "=?" for c in upd_cols])} WHERE Id = ?'''
                cursor.execute(uq, upd_vals)
                
                # --- HISTORY INSERT ---
                h_cols = cols.copy()
                h_cols.insert(0, "Id")
                h_vals = vals.copy()
                h_vals.insert(0, record_id) # The existing ID
                # Felülírjuk az üres Note-ot a historikus insertben a meglévővel
                h_vals[h_cols.index("Note")] = existing_note
                h_cols.extend(["ValidFrom", "ValidTo"])
                h_vals.extend([now, None])
                
                hq = f'''INSERT INTO History.Franchise_WebScrapedData ({", ".join(h_cols)}) VALUES ({", ".join(["?" for _ in h_cols])})'''
                cursor.execute(hq, h_vals)
                
                if not db_row["IsActive"]:
                    activated_count += 1
                else:
                    updated_count += 1
            else:
                # Nincs adatváltozás, csak befrissítjük az utolsó látogatást
                cursor.execute("UPDATE Franchise.WebScrapedData SET LastSeenAt = ? WHERE Id = ?", now, record_id)
                unchanged_count += 1

    # 4. Amik benne vannak a DB-ben, de most nem jöttek le a webről (és IsActive=1) -> INAKTIVÁLJUK
    missing_keys = [k for k in db_cache.keys() if k not in seen_keys and db_cache[k]["IsActive"] == True]
    deactivated_count = 0
    for mk in missing_keys:
        record_id = db_cache[mk]["Id"]
        # History tábla régi rekord lezárása
        cursor.execute("UPDATE History.Franchise_WebScrapedData SET ValidTo = ? WHERE Id = ? AND ValidTo IS NULL", now, record_id)
        
        # Main tábla update: IsActive = 0, + a RecordHash-t is meg kéne változtatni, de elég ha az active átbillen
        cursor.execute("UPDATE Franchise.WebScrapedData SET IsActive = 0, LastSeenAt = ? WHERE Id = ?", now, record_id)
        
        # History táblába beírjuk az inaktív rekordot
        # Előbb lekérjük a db-ből a jelenlegi amúgy is adatot hogy újra lementsük inaktívként
        cursor.execute("SELECT FranchiseName, OriginalId, Name, ZipCode, City, Address, Phone, Email, Facebook, Website, PharmacyManager, Latitude, Longitude, OpeningHours, RawJson, RecordHash, Note FROM Franchise.WebScrapedData WHERE Id = ?", record_id)
        r = cursor.fetchone()
        
        h_cols = ["Id", "FranchiseName", "OriginalId", "Name", "ZipCode", "City", "Address", "Phone", "Email", "Facebook", "Website", "PharmacyManager", "Latitude", "Longitude", "OpeningHours", "RecordHash", "RawJson", "IsActive", "FirstSeenAt", "LastSeenAt", "Note", "ValidFrom", "ValidTo"]
        h_vals = [record_id, r.FranchiseName, r.OriginalId, r.Name, r.ZipCode, r.City, r.Address, r.Phone, r.Email, r.Facebook, r.Website, r.PharmacyManager, r.Latitude, r.Longitude, r.OpeningHours, r.RecordHash, r.RawJson, 0, now, now, r.Note, now, None]
        
        hq = f'''INSERT INTO History.Franchise_WebScrapedData ({", ".join(h_cols)}) VALUES ({", ".join(["?" for _ in h_cols])})'''
        cursor.execute(hq, h_vals)
        deactivated_count += 1
        
    print("\n--- Szinkronizáció kész ---")
    print(f"Lefuttatva: {len(records)} patika a JSON forrásokból")
    print(f"Újként beszúrva: {inserted_count}")
    print(f"Módosítva (History is naplózva): {updated_count}")
    print(f"Újra aktiválva: {activated_count}")
    print(f"Változatlan (LastSeenAt frissítve): {unchanged_count}")
    print(f"Inaktiválva (Lezárva/Eltűnt a webről): {deactivated_count}")

if __name__ == "__main__":
    setup_database()
    records = normalize_data()
    sync_to_db(records)
