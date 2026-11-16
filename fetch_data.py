import json
import urllib.request
import urllib.parse
import urllib.error
import re
import concurrent.futures

def fetch_and_save_data():
    # 1. Beolvassuk az urls.json fájlt
    try:
        with open('urls.json', 'r', encoding='utf-8-sig') as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Hiba: Az urls.json fájl nem található.")
        return
    except json.JSONDecodeError:
        print("Hiba: Az urls.json fájl formátuma érvénytelen.")
        return

    franchises = config.get('franchise', [])
    
    if not franchises:
        print("Nem található franchise adat az urls.json fájlban.")
        return

    # 2. Végigmegyünk a végpontokon és letöltjük az adatokat
    for item in franchises:
        name = item.get('name', 'Ismeretlen')
        url = item.get('url')
        
        if not url:
            print(f"Figyelmeztetés: Nincs URL megadva a következőhöz: {name}")
            continue
            
        print(f"Adatok lekérése: {name}...")
        
        try:
            # Ha BENU, akkor nem kell a sima HTTP kérés, mert GraphQL-t használunk
            if "benu.hu" in url:
                print(f"Adatok letöltése a(z) {name} forrásból (Shopify GraphQL API)...")
                
                # BENU Shopify Storefront API adatok
                graphql_url = 'https://benu-hu-prod.myshopify.com/api/2025-10/graphql.json'
                headers = {
                    'User-Agent': 'Mozilla/5.0',
                    'Content-Type': 'application/json',
                    'X-Shopify-Storefront-Access-Token': 'aceebc583e463763f5c7eaff7a053898'
                }
                
                query = '''
                query fetchPharmacies($cursor: String) {
                  metaobjects(type: "pharmacies", first: 250, after: $cursor) {
                    edges {
                      node {
                        id
                        handle
                        fields {
                          key
                          value
                        }
                      }
                    }
                    pageInfo {
                      hasNextPage
                      endCursor
                    }
                  }
                }
                '''
                
                all_pharmacies = []
                cursor = None
                has_next_page = True
                
                while has_next_page:
                    graphql_data = json.dumps({'query': query, 'variables': {'cursor': cursor}}).encode('utf-8')
                    graphql_req = urllib.request.Request(graphql_url, data=graphql_data, headers=headers)
                    
                    try:
                        with urllib.request.urlopen(graphql_req) as graphql_response:
                            result = json.loads(graphql_response.read().decode('utf-8'))
                            
                            metaobjects = result.get('data', {}).get('metaobjects', {})
                            edges = metaobjects.get('edges', [])
                            
                            for edge in edges:
                                node = edge.get('node', {})
                                fields = node.get('fields', [])
                                
                                # Alakítsuk át a fields tömböt egy objektummá
                                pharmacy_data = {'id': node.get('id'), 'handle': node.get('handle')}
                                for field in fields:
                                    pharmacy_data[field.get('key')] = field.get('value')
                                    
                                # Csak az aktív BENU patikákat tartjuk meg
                                if pharmacy_data.get('is_active') == 'true' and pharmacy_data.get('is_benu') == 'true':
                                    # Nyitvatartás JSON stringként jön, próbáljuk meg parse-olni
                                    if 'opening_hours' in pharmacy_data and pharmacy_data['opening_hours']:
                                        try:
                                            pharmacy_data['opening_hours_parsed'] = json.loads(pharmacy_data['opening_hours'])
                                        except json.JSONDecodeError:
                                            pass
                                            
                                    all_pharmacies.append(pharmacy_data)
                                    
                            page_info = metaobjects.get('pageInfo', {})
                            has_next_page = page_info.get('hasNextPage', False)
                            cursor = page_info.get('endCursor')
                            
                    except Exception as e:
                        print(f"Hiba a(z) {name} GraphQL lekérdezése során: {e}")
                        break
                        
                if all_pharmacies:
                    data = all_pharmacies
                else:
                    print(f"Hiba: Nem találtam patika adatokat a(z) {name} forrásban.")
                    continue
            elif "kulcspatikak.hu" in url:
                print(f"Adatok letöltése a(z) {name} forrásból (egyedi API hívások)...")
                
                kulcs_url = "https://kulcspatikak.hu/gykeres_feed.php"
                kulcs_headers = {'User-Agent': 'Mozilla/5.0'}
                
                def fetch_kulcs_patika(pid):
                    post_data = urllib.parse.urlencode({'patikaid': str(pid)}).encode('utf-8')
                    kreq = urllib.request.Request(kulcs_url, data=post_data, headers=kulcs_headers)
                    try:
                        resp = json.loads(urllib.request.urlopen(kreq, timeout=10).read().decode('utf-8'))
                        if resp.get('patikaIdList', []):
                            patika_data = resp['patikaIdList'][0]
                            html_string = resp.get('htmlString', '')
                            
                            # Részletes nyitvatartás kinyerése a HTML-ből (A további részletek adatai)
                            hours_match = re.search(r'<strong class="lang hu">Nyitvatartás:</strong>.*?<br/>(.*?)</p>', html_string, re.IGNORECASE)
                            if hours_match:
                                hours_raw = hours_match.group(1)
                                # Angol feliratok (pl. <span class="lang en">Monday</span>) kiszedése
                                hours = re.sub(r'<span class="lang en">.*?</span>', '', hours_raw)
                                hours = re.sub(r'<br\s*/?>', ' | ', hours)
                                hours = re.sub(r'<[^>]+>', '', hours).strip()
                                hours = re.sub(r'\s+', ' ', hours)
                                hours = hours.replace(' | ', '|').replace('|', ' | ')
                                hours = re.sub(r'^(\s*\|\s*)+', '', hours)
                                hours = re.sub(r'(\s*\|\s*)+$', '', hours)
                                patika_data['opening_hours_detailed'] = hours
                                
                            # Részletes telefonszám, ha esetleg jobb, mint a sima POI-ban
                            phone_match = re.search(r'<strong class="lang en">Phone:</strong>([^<]+)', html_string)
                            if phone_match and not patika_data.get('phone_detailed'):
                                patika_data['phone_detailed'] = phone_match.group(1).strip()
                                
                            # Facebook e-mail vagy link kinyerése a teljes leírás részéből
                            fb_match = re.search(r'href=[\'"](https?://(?:www\.)?facebook\.com/[^\'"]+)[\'"]', html_string, re.IGNORECASE)
                            if fb_match:
                                fb_link = fb_match.group(1)
                                if 'kulcspatika' not in fb_link.lower() and 'sharer' not in fb_link.lower():
                                    patika_data['facebook'] = fb_link
                                    
                            email_match = re.search(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', html_string)
                            if email_match:
                                patika_data['email'] = email_match.group(1)
                                
                            return patika_data
                    except Exception:
                        pass
                    return None

                all_pharmacies = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    # Legmagasabb aktív ID kb. ~310. Kiderítettük, hogy 1-400 bőven lefedi a teljes listát
                    results = executor.map(fetch_kulcs_patika, range(1, 401))
                    for r in results:
                        if r:
                            all_pharmacies.append(r)
                            
                if all_pharmacies:
                    data = all_pharmacies
                else:
                    print(f"Hiba: Nem találtam patika adatokat a(z) {name} forrásban.")
                    continue
            else:
                # Kérés küldése (User-Agent beállítása, hogy ne blokkoljanak)
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    # Válasz beolvasása
                    raw_content = response.read().decode('utf-8')
                    
                    # Ha a Csillag Patikák weboldaláról van szó, akkor HTML-ből nyerjük ki a JSON-t
                    if "csillagpatikak.hu" in url:
                        # Keresünk egy window.Yco.pharmacies = [...] mintát a HTML-ben
                        match = re.search(r'window\.Yco\.pharmacies\s*=\s*(\[.*?\]);', raw_content, re.DOTALL)
                        if match:
                            json_string = match.group(1)
                            data = json.loads(json_string)
                            
                            # Kinyerjük a HTML-ből a telefonszámokat és nyitvatartásokat is
                            cards = re.findall(r'<h3 class="card-title">(.*?)</h3>(.*?)(?=<h3 class="card-title">|<div class="footer)', raw_content, re.DOTALL)
                            
                            # Készítünk egy szótárat a gyors kereséshez
                            extra_info = {}
                            for card_name, card_content in cards:
                                card_name = card_name.strip()
                                
                                phone_match = re.search(r'<strong>Telefon:\s*</strong>(.*?)</p>', card_content, re.DOTALL)
                                phone = phone_match.group(1).strip() if phone_match else ''
                                
                                hours_match = re.search(r'<strong>\s*Nyitvatartás:</strong>(.*?)</p>', card_content, re.DOTALL)
                                if hours_match:
                                    hours_raw = hours_match.group(1)
                                    # A HTML tageket (pl. <br>) egy speciális elválasztóra cseréljük (pl. | vagy \n)
                                    # Itt most a " | " karaktert használjuk, amit később könnyű lesz újra sortöréssé alakítani
                                    hours = re.sub(r'<br\s*/?>', ' | ', hours_raw)
                                    hours = re.sub(r'<[^>]+>', '', hours).strip()
                                    hours = re.sub(r'\s+', ' ', hours)
                                    # Kicsit megtisztítjuk a felesleges szóközöket a szeparátor körül
                                    hours = hours.replace(' | ', '|').replace('|', ' | ')
                                    # Eltávolítjuk a felesleges üres elválasztókat a végéről és az elejéről
                                    hours = re.sub(r'^(\s*\|\s*)+', '', hours)
                                    hours = re.sub(r'(\s*\|\s*)+$', '', hours)
                                    # Több egymás utáni elválasztót egyre cserélünk
                                    hours = re.sub(r'(\s*\|\s*)+', ' | ', hours)
                                else:
                                    hours = ''
                                    
                                extra_info[card_name] = {
                                    'phone': phone,
                                    'opening_hours': hours
                                }
                                
                            # Hozzáadjuk a JSON adatokhoz a kinyert extra infókat
                            for item in data:
                                name_key = item.get('name', '').replace('\\u00e1', 'á').replace('\\u00ed', 'í').replace('\\u00f3', 'ó').replace('\\u00e9', 'é')
                                # A json.loads már dekódolja a unicode karaktereket, így a name_key már jó
                                name_key = item.get('name', '').strip()
                                
                                if name_key in extra_info:
                                    item['phone'] = extra_info[name_key]['phone']
                                    item['opening_hours'] = extra_info[name_key]['opening_hours']
                                else:
                                    item['phone'] = ''
                                    item['opening_hours'] = ''
                        else:
                            print(f"Hiba: Nem találtam patika adatokat a(z) {name} HTML forrásában.")
                            continue
                    elif "pingvinpatika.hu" in url:
                        # Pingvin Patikák - beágyazott JSON (var pharmacies)
                        match = re.search(r'var pharmacies\s*=\s*(\[.*?\]);', raw_content, re.DOTALL)
                        if match:
                            json_string = match.group(1)
                            data = json.loads(json_string)
                            
                            # Kinyerjük az extra mezőket a HTML tartalomból
                            for item in data:
                                content_html = item.get('content', '')
                                
                                # Város kinyerése a h4 tagből
                                city_match = re.search(r'<h4[^>]*>(.*?)</h4>', content_html)
                                if city_match:
                                    item['city'] = re.sub(r'<[^>]+>', '', city_match.group(1)).strip()
                                
                                # Nyitvatartás kinyerése a span után
                                hours_match = re.search(r'Nyitvatartás:.*?</span>(.*?)</p>', content_html, re.IGNORECASE)
                                if hours_match:
                                    item['opening_hours_detailed'] = hours_match.group(1).strip()
                                    
                        else:
                            print(f"Hiba: Nem találtam patika adatokat a(z) {name} HTML forrásában.")
                            continue
                    elif "patikaplus.hu" in url:
                        # PatikaPlus - beágyazott array of arrays JS formátumban: var patika = ["Név", lat, lon, "Cím", "Tel", "Nyitvatartás HTML"];
                        patikak_matches = re.findall(r'var patika\s*=\s*(\[[^\]]+\]);', raw_content)
                        if patikak_matches:
                            data = []
                            for p_match in patikak_matches:
                                # Ez érvénytelen JSON lehet a single quote-ok vagy speciális karakterek miatt,
                                # így biztonságosabb kisiklani a Python ast moduljával vagy JSON-osítani
                                # Bár Python és JS szintaktikailag hasonló egy sima lista esetén,
                                # kicsit átalakítjuk a JS tömböt JSON stringgé hogy a loads megegye.
                                # (a " -ra végződő stringeket és számokat kell kiszednünk)
                                try:
                                    # Egyszerűbb regex-szel szétszedni a 6 elemet a vesszők mentén
                                    # Szabvány : 'név', lat, lon, 'cím', 'tel', 'html'
                                    import ast
                                    parsed_array = ast.literal_eval(p_match.replace('<div class=', "'<div class=").replace('</div></div></div>',"</div></div></div>'"))
                                except SyntaxError:
                                    # Ha fallback kell, megpróbáljuk regex-szel darabolni
                                    # De mivel a JS tömb sztringeket tartalmazhat, amit Python ast modul is megért:
                                    pass
                                
                                try:
                                    # Biztonságosabb felbontás Regex segítségével, ha az ast elhasalna
                                    # [ "Név", 47.114, 17.549, "Cím", "Tel", '<div...']
                                    parts = re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)(?=(?:[^\']*\'[^\']*\')*[^\']*$)', p_match[1:-1])
                                    if len(parts) >= 6:
                                        p_name = parts[0].strip('\'" ')
                                        p_lat = parts[1].strip()
                                        p_lon = parts[2].strip()
                                        p_address = parts[3].strip('\'" ')
                                        p_tel = parts[4].strip('\'" ')
                                        p_hours_html = parts[5].strip('\'" ')
                                        
                                        # Kiparszoljuk a nyitvatartást a HTML div-ekből
                                        hours_clean = re.sub(r'<div class="row">.*?<div class="col-6">(.*?)</div>.*?<div class="col-6">(.*?)</div>.*?</div>', r'\1: \2 | ', p_hours_html)
                                        hours_clean = re.sub(r'<[^>]+>', '', hours_clean).strip(' |')
                                        hours_clean = hours_clean.replace('\n', '').replace('\u00a0', ' ')
                                        
                                        data.append({
                                            'name': p_name,
                                            'lat': p_lat,
                                            'lon': p_lon,
                                            'address': p_address,
                                            'phone': p_tel,
                                            'opening_hours_detailed': hours_clean
                                        })
                                except Exception as e:
                                    pass
                        else:
                            print(f"Hiba: Nem találtam patika adatokat a(z) {name} HTML forrásában.")
                            continue
                    elif "szirompatikak.hu" in url:
                        # Szirom Patikák API lekérdezése (WP Ajax API Agile Store Locator pluginnal)
                        # Az URL-ben lévő wp-admin/admin-ajax... végpontot hívjuk meg a HTML helyett
                        ajax_url = "https://szirompatikak.hu/wp-admin/admin-ajax.php?action=asl_load_stores&load_all=1&layout=1"
                        ajax_req = urllib.request.Request(ajax_url, headers={'User-Agent': 'Mozilla/5.0'})
                        
                        ajax_response = urllib.request.urlopen(ajax_req, timeout=15)
                        ajax_raw = ajax_response.read().decode('utf-8')
                        data = json.loads(ajax_raw)
                        
                        # Tisztítjuk és átalakítjuk a nyitvatartást, ha van
                        for item in data:
                            hours_raw = item.get('open_hours', '')
                            if hours_raw and hours_raw.startswith('{'):
                                try:
                                    hours_obj = json.loads(hours_raw)
                                    hours_str = []
                                    days_map = {'mon': 'Hétfő', 'tue': 'Kedd', 'wed': 'Szerda', 'thu': 'Csütörtök', 'fri': 'Péntek', 'sat': 'Szombat', 'sun': 'Vasárnap'}
                                    
                                    for eng, hun in days_map.items():
                                        day_val = hours_obj.get(eng)
                                        if isinstance(day_val, list) and day_val and day_val[0] != "0":
                                            hours_str.append(f"{hun}: {day_val[0]}")
                                        elif day_val == "1":
                                            hours_str.append(f"{hun}: Nyitva")
                                        elif day_val == "0":
                                            hours_str.append(f"{hun}: Zárva")
                                            
                                    item['opening_hours_detailed'] = " | ".join(hours_str)
                                except json.JSONDecodeError:
                                    pass
                    else:
                        # Egyébként sima JSON-ként kezeljük
                        data = json.loads(raw_content)
            
            # Fájlnév generálása a franchise nevéből (speciális karakterek cseréje)
            safe_name = "".join([c if c.isalnum() else "_" for c in name]).strip("_")
            output_filename = f"{safe_name}_raw.json"
            
            # 3. Eredmény mentése egy új JSON fájlba
            with open(output_filename, 'w', encoding='utf-8') as out_file:
                json.dump(data, out_file, ensure_ascii=False, indent=4)
                
            print(f"Sikeres mentés: {output_filename}")
            
        except urllib.error.URLError as e:
            print(f"Hálózati hiba történt a(z) {name} lekérésekor: {e}")
        except json.JSONDecodeError:
            print(f"Hiba: A(z) {name} végpont nem érvényes JSON-t adott vissza.")
        except Exception as e:
            print(f"Váratlan hiba történt a(z) {name} feldolgozásakor: {e}")

if __name__ == "__main__":
    fetch_and_save_data()
