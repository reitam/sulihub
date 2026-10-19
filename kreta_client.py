import requests

class KretaSimpleClient:
    def __init__(self, institute_code, username, password):
        self.institute_code = institute_code.lower().strip()
        self.username = username.strip()
        self.password = password
        self.session = requests.Session()
        self.access_token = None

    def login(self):
        token_url = "https://idp.e-kreta.hu/connect/token"
        
        # Gondviselői / szülői fiókhoz használt aktív kliens azonosítók
        payload = {
            'institute_code': self.institute_code,
            'userName': self.username,
            'password': self.password,
            'grant_type': 'password',
            'client_id': 'kreta-parent-mobile-android'
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'hu.ekreta.gondviselo/1.0.0/Android/10/v2',
            'apiKey': 'a22c0199-2a91-4cf5-9988-cb949bcfc70f',
            'X-Device-Id': '00000000-0000-0000-0000-000000000000'
        }
        
        try:
            res = self.session.post(token_url, data=payload, headers=headers)
            
            try:
                data = res.json()
            except Exception:
                return False, f"A szerver nem JSON választ adott (HTTP {res.status_code}):\n{res.text[:300]}"

            if res.status_code == 200:
                self.access_token = data.get('access_token')
                return True, "Sikeres bejelentkezés!"
            else:
                error_type = data.get('error', 'Ismeretlen hiba')
                error_desc = data.get('error_description', res.text)
                return False, f"HTTP Hiba ({res.status_code}): {error_type} - {error_desc}"

        except Exception as e:
            return False, f"Kivétel a hálózati kommunikáció során: {str(e)}"

    def get_evaluations(self):
        if not self.access_token:
            return False, "Nincs érvényes access_token!"
            
        eval_url = f"https://{self.institute_code}.e-kreta.hu/ellenorzo/V3/Sajat/Ertekelesek"
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'User-Agent': 'hu.ekreta.gondviselo/1.0.0/Android/10/v2',
            'apiKey': 'a22c0199-2a91-4cf5-9988-cb949bcfc70f'
        }
        
        res = self.session.get(eval_url, headers=headers)
        
        if res.status_code == 200:
            return True, res.json()
        else:
            return False, f"HTTP Hiba a jegyeknél ({res.status_code}): {res.text[:200]}"