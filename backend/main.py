import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import sqlite3
import hashlib
import os
import binascii
# Ensure solver.py is in the same directory
from solver import VRPSolver 

print("\n" + "="*50)
print("✅ LOADING: FULL SYSTEM + SECURE AUTH + LOGISTICS")
print("⚠️  REMINDER: Delete 'fresq.db' if you see DB errors.")
print("="*50 + "\n")

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

solver = VRPSolver()
DB_NAME = "fresq.db"

# --- SECURITY UTILS ---
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return binascii.hexlify(salt + pwd_hash).decode()

def verify_password(stored_password: str, provided_password: str) -> bool:
    try:
        stored_data = binascii.unhexlify(stored_password)
        salt, stored_hash = stored_data[:16], stored_data[16:]
        pwd_hash = hashlib.pbkdf2_hmac('sha256', provided_password.encode(), salt, 100000)
        return pwd_hash == stored_hash
    except: return False

# --- DATABASE SETUP ---
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, quantity INTEGER, details TEXT,
                pickup_lat REAL, pickup_lon REAL,
                delivery_lat REAL, delivery_lon REAL,
                ngo_name TEXT, status TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                phone TEXT PRIMARY KEY,
                username TEXT,
                password TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
init_db()

# --- NGO DATA ---
NGO_DATABASE = [
    {"name": "Dadabari Relief Center", "city": "Kota", "lat": 25.1580, "lon": 75.8280},
    {"name": "Nayapura Food Bank", "city": "Kota", "lat": 25.1910, "lon": 75.8450},
    {"name": "Talwandi Shelter", "city": "Kota", "lat": 25.1436, "lon": 75.8540},
    {"name": "Kota Station Aid", "city": "Kota", "lat": 25.2215, "lon": 75.8810},
    {"name": "Akshaya Patra Jaipur", "city": "Jaipur", "lat": 26.8225, "lon": 75.8018},
    {"name": "Rays Asha Ki Kiran", "city": "Jaipur", "lat": 26.8912, "lon": 75.7600},
    {"name": "Sambhali Trust", "city": "Jodhpur", "lat": 26.2890, "lon": 73.0240},
    {"name": "Seva Mandir", "city": "Udaipur", "lat": 24.5940, "lon": 73.6820}
]

# --- MODELS ---
class SignupRequest(BaseModel):
    phone: str
    username: str
    password: str

class LoginRequest(BaseModel):
    phone: str
    password: str

class Location(BaseModel):
    lat: float
    lon: float
class Vehicle(BaseModel):
    id: str
    capacity: int
    start_location: Location
class Order(BaseModel):
    id: str
    quantity: int
    pickup_location: Location
    pickup_window: Dict[str, int]
    delivery_location: Location
    delivery_window: Dict[str, int]
    service_time: int
    ngo_name: str = "Unknown"
    details: str = "Food"
    status: str = "pending"
class OptimizationRequest(BaseModel):
    vehicle: Vehicle
    orders: List[Order]
class CustomerOrderRequest(BaseModel):
    pickup_lat: float
    pickup_lon: float
    quantity: int
    details: str
    expiry_hours: int
class StatusUpdate(BaseModel):
    order_id: str
    status: str

# --- AUTH ENDPOINTS ---
@app.post("/api/auth/signup")
def signup(req: SignupRequest):
    hashed_pwd = hash_password(req.password)
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.cursor().execute("INSERT INTO users (phone, username, password) VALUES (?, ?, ?)", (req.phone, req.username, hashed_pwd))
            conn.commit()
        return {"status": "success"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Phone number already registered")

@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    with sqlite3.connect(DB_NAME) as conn:
        user = conn.cursor().execute("SELECT password, username FROM users WHERE phone = ?", (req.phone,)).fetchone()
    if not user or not verify_password(user[0], req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    res = JSONResponse(content={"status": "success"})
    res.set_cookie(key="fresq_user", value=req.phone, max_age=86400)
    return res

@app.post("/api/auth/logout")
def logout(response: Response):
    res = JSONResponse(content={"status": "logged_out"})
    res.delete_cookie("fresq_user")
    return res

# --- LOGISTICS API ---
@app.get("/api/orders")
def get_orders():
    orders = []
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE status = 'pending'")
        rows = cursor.fetchall()
        for row in rows:
            orders.append({
                "id": row[0], "quantity": row[1], "details": row[2],
                "pickup_location": {"lat": row[3], "lon": row[4]},
                "pickup_window": {"start": 0, "end": 86400},
                "delivery_location": {"lat": row[5], "lon": row[6]},
                "delivery_window": {"start": 0, "end": 86400},
                "service_time": 300, "ngo_name": row[7], "status": row[8]
            })
    return orders

@app.post("/api/create_order")
def create_order(req: CustomerOrderRequest):
    new_id = str(uuid.uuid4())[:8]
    ngo = min(NGO_DATABASE, key=lambda n: abs(n['lat'] - req.pickup_lat) + abs(n['lon'] - req.pickup_lon))
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO orders (id, quantity, details, pickup_lat, pickup_lon, delivery_lat, delivery_lon, ngo_name, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (new_id, req.quantity, req.details, req.pickup_lat, req.pickup_lon, ngo['lat'], ngo['lon'], ngo['name'], 'pending'))
        conn.commit()
    return {"status": "success", "order_id": new_id, "assigned_ngo": ngo['name']}

@app.post("/api/optimize")
def optimize(req: OptimizationRequest):
    try:
        route, dist = solver.solve_route(req)
        return {"route": route, "total_distance": dist}
    except Exception as e:
        print(f"Solver Error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/update_status")
def update_status(upd: StatusUpdate):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (upd.status, upd.order_id))
        conn.commit()
    return {"status": "success"}

# --- 1. LANDING PAGE ---
@app.get("/", response_class=HTMLResponse)
def landing_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Welcome to FresQ</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root { 
                --bg: #f4f4f9; --glass: rgba(255, 255, 255, 0.9); --border: 1px solid rgba(0, 0, 0, 0.1); 
                --accent: #ff6b00; --text: #222222; --shadow: rgba(0, 0, 0, 0.1);
            }
            body.dark-mode {
                --bg: #000000; --glass: rgba(20, 20, 20, 0.8); --border: 1px solid rgba(255, 255, 255, 0.15);
                --text: #ffffff; --shadow: rgba(255, 107, 0, 0.1);
            }
            body { margin: 0; padding: 0; background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; align-items: center; justify-content: center; overflow: hidden; transition: 0.3s; }
            .container { text-align: center; width: 100%; max-width: 420px; padding: 20px; }
            .card { background: var(--glass); backdrop-filter: blur(30px); border: var(--border); border-radius: 30px; padding: 60px 40px; box-shadow: 0 0 50px var(--shadow); display: flex; flex-direction: column; gap: 25px; transition: 0.3s; }
            h1 { font-size: 4rem; margin: 0; letter-spacing: -2px; font-weight: 800; line-height: 1; }
            h1 span { color: var(--accent); }
            p { color: #888; margin-top: 5px; margin-bottom: 40px; font-size: 1.2rem; letter-spacing: 2px; text-transform: uppercase; }
            .btn { display: flex; align-items: center; justify-content: center; gap: 15px; padding: 20px; border-radius: 18px; text-decoration: none; font-size: 1.2rem; font-weight: 700; transition: all 0.2s ease; }
            .btn:active { transform: scale(0.98); }
            .btn-donor { background: linear-gradient(135deg, #ff6b00, #ff9100); color: black; box-shadow: 0 10px 30px rgba(255, 107, 0, 0.25); }
            .btn-driver { background: rgba(0,0,0,0.05); color: inherit; border: var(--border); }
            body.dark-mode .btn-driver { background: rgba(255, 255, 255, 0.05); }
            .theme-toggle { position: absolute; top: 20px; right: 20px; width: 45px; height: 45px; border-radius: 50%; background: var(--glass); border: var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 1.2rem; transition: transform 0.2s; }
            .theme-toggle:hover { transform: scale(1.1); }
        </style>
    </head>
    <body>
        <div class="theme-toggle" onclick="toggleTheme()"><i class="fas fa-moon" id="theme-icon"></i></div>
        <div class="container">
            <div class="card">
                <div><h1>Fres<span>Q</span></h1><p>Food Rescue Network</p></div>
                <a href="/customer" class="btn btn-donor"><i class="fas fa-heart"></i> I am a Donor</a>
                <a href="/driver" class="btn btn-driver"><i class="fas fa-truck-fast"></i> I am a Driver</a>
            </div>
        </div>
        <script>
            function toggleTheme() {
                document.body.classList.toggle('dark-mode');
                const icon = document.getElementById('theme-icon');
                if (document.body.classList.contains('dark-mode')) { icon.classList.remove('fa-moon'); icon.classList.add('fa-sun'); }
                else { icon.classList.remove('fa-sun'); icon.classList.add('fa-moon'); }
            }
        </script>
    </body>
    </html>
    """

# --- 2. LOGIN PAGE ---
@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <!DOCTYPE html><html><head><title>FresQ Login</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg:#f4f4f9; --glass:rgba(255,255,255,0.95); --accent:#ff6b00; --text:#222; --border: 1px solid #ddd; }
        body.dark-mode { --bg:#000; --glass:rgba(20,20,20,0.8); --text:#fff; --border: 1px solid #333; }
        body { margin:0; background:var(--bg); color:var(--text); font-family:sans-serif; height:100vh; display:flex; align-items:center; justify-content:center; transition:0.3s; }
        .box { background:var(--glass); padding:40px; border-radius:24px; border:var(--border); width:350px; text-align:center; box-shadow:0 10px 40px rgba(0,0,0,0.1); }
        input { width:100%; padding:12px; margin:8px 0; background:rgba(0,0,0,0.05); border:1px solid #ddd; border-radius:10px; box-sizing:border-box; color:inherit; outline:none; }
        body.dark-mode input { border-color:#444; background:rgba(255,255,255,0.05); }
        button { width:100%; padding:14px; background:var(--accent); color:white; border:none; border-radius:12px; cursor:pointer; font-weight:bold; margin-top:10px; }
        .toggle { margin-top: 15px; font-size: 0.85rem; color: #666; cursor: pointer; text-decoration: underline; }
        .hidden { display: none; }
        .theme-toggle { position:absolute; top:20px; right:20px; cursor:pointer; font-size:1.2rem; }
    </style></head>
    <body>
        <div class="theme-toggle" onclick="toggleTheme()"><i class="fas fa-moon" id="theme-icon"></i></div>
        <div class="box"><h2 id="title">Login</h2>
        <div id="signup-fields" class="hidden"><input type="text" id="username" placeholder="Full Name"></div>
        <input type="tel" id="phone" placeholder="Phone Number"><input type="password" id="pass" placeholder="Password">
        <button onclick="handleAuth()" id="btn">Login</button><div class="toggle" onclick="toggleMode()" id="mode">Need an account? Sign Up</div></div>
        <script>
        let isLogin = true;
        function toggleTheme() { document.body.classList.toggle('dark-mode'); document.getElementById('theme-icon').className = document.body.classList.contains('dark-mode') ? 'fas fa-sun' : 'fas fa-moon'; }
        function toggleMode() { isLogin = !isLogin; document.getElementById('title').innerText = isLogin ? "Login" : "Create Account"; document.getElementById('btn').innerText = isLogin ? "Login" : "Sign Up"; document.getElementById('mode').innerText = isLogin ? "Need an account? Sign Up" : "Already have an account? Login"; document.getElementById('signup-fields').classList.toggle('hidden'); }
        async function handleAuth() {
            const phone = document.getElementById('phone').value; const password = document.getElementById('pass').value;
            const target = new URLSearchParams(window.location.search).get('target') || '/customer';
            if(isLogin) {
                const res = await fetch('/api/auth/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({phone, password}) });
                if(res.ok) window.location.href = target; else alert("Invalid Credentials");
            } else {
                const username = document.getElementById('username').value;
                const res = await fetch('/api/auth/signup', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({phone, username, password}) });
                if(res.ok) { alert("Account Created! Please Login."); toggleMode(); } else alert("Signup Failed or Phone exists.");
            }
        }
        </script>
    </body></html>
    """

# --- 3. CUSTOMER APP ---
@app.get("/customer", response_class=HTMLResponse)
def customer_app(request: Request):
    if not request.cookies.get("fresq_user"): return RedirectResponse(url="/login?target=/customer")
    return f"""
    <!DOCTYPE html><html><head><title>Donor</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css"/>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
    <style>
        :root{{--accent:#ff6b00;--bg:#f4f4f9;--card:#fff; --success: #10b981; --error: #ef4444;}}
        body{{margin:0;font-family:sans-serif;background:var(--bg);overflow:hidden;}}
        
        #map{{position:absolute;top:0;left:0;width:100%;height:100vh;z-index:0;}}
        
        /* SLIDEABLE BOTTOM SHEET CSS */
        .panel{{
            position:absolute; bottom:0; left:50%; transform:translateX(-50%);
            width:100%; max-width:600px;
            background:var(--card);
            border-radius:25px 25px 0 0;
            padding:10px 25px 30px 25px;
            box-shadow:0 -10px 40px rgba(0,0,0,0.2);
            z-index:1000; box-sizing:border-box;
            transition: transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
            max-height: 80vh; overflow-y: auto;
        }}
        
        .panel.minimized {{ transform: translateX(-50%) translateY(85%); }}
        
        .drag-handle {{ width: 50px; height: 5px; background: #ddd; border-radius: 10px; margin: 10px auto 20px; cursor: grab; }}
        .drag-handle:active {{ cursor: grabbing; }}

        input,textarea,select{{width:100%;padding:14px;margin-bottom:12px;border-radius:12px;border:1px solid #ddd;box-sizing:border-box;font-family:inherit;background:#fff;}}
        input:focus,textarea:focus,select:focus{{border-color:var(--accent);outline:none;}}
        
        button{{width:100%;padding:16px;background:var(--accent);color:#fff;border:none;border-radius:14px;font-weight:bold;cursor:pointer;font-size:1rem;margin-top:10px; transition:0.3s;}}
        button:disabled {{ background: #ccc; cursor: not-allowed; }}
        
        .home-btn{{position:absolute;top:20px;left:20px;z-index:2000;background:#fff;border-radius:50%;box-shadow:0 4px 10px rgba(0,0,0,0.2);cursor:pointer;display:flex;align-items:center;justify-content:center;text-decoration:none;color:inherit;width:45px;height:45px;}}
        .logout{{position:absolute;top:20px;right:20px;z-index:2000;background:#fff;border-radius:50%;box-shadow:0 4px 10px rgba(0,0,0,0.2);cursor:pointer;display:flex;align-items:center;justify-content:center;width:45px;height:45px;}}
        
        .date-group {{ display: flex; gap: 10px; }}
        .date-field {{ flex: 1; }}
        .date-field label {{ font-size: 0.8rem; color: #666; display: block; margin-bottom: 4px; }}
        .expiry-container {{ display: flex; gap: 5px; }}

        /* --- AI UPLOAD STYLES --- */
        .upload-section {{ border: 2px dashed #ddd; border-radius: 15px; padding: 20px; text-align: center; margin-bottom: 15px; cursor: pointer; position: relative; }}
        .upload-section:hover {{ background: #f9f9f9; border-color: var(--accent); }}
        #preview-img {{ max-width: 100%; height: 150px; object-fit: cover; border-radius: 10px; margin: 0 auto; display: block; }}
        .hidden {{ display: none !important; }}
        
        /* Analysis Results */
        .result-box {{ margin-top: 15px; padding: 15px; border-radius: 12px; border: 1px solid #eee; text-align: center; }}
        .result-box.pass {{ background: #ecfdf5; border-color: #a7f3d0; }}
        .result-box.fail {{ background: #fef2f2; border-color: #fecaca; }}
        
        .score-val {{ font-size: 1.5rem; font-weight: 900; display: block; margin-bottom: 5px; }}
        .score-val.pass {{ color: var(--success); }}
        .score-val.fail {{ color: var(--error); }}
        
        .progress-bg {{ background: #e5e7eb; height: 8px; border-radius: 4px; overflow: hidden; margin: 10px 0; }}
        .progress-fill {{ height: 100%; transition: width 0.5s ease; }}
        .progress-fill.pass {{ background: var(--success); }}
        .progress-fill.fail {{ background: var(--error); }}

        #classification-msg {{ font-size: 1.2rem; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; }}
        
    </style></head><body>
    
    <a href="/" class="home-btn"><i class="fas fa-home"></i></a>
    <div class="logout" onclick="logout()"><i class="fas fa-sign-out-alt"></i></div>
    
    <div id="map"></div>
    
    <div class="panel" id="sheet">
        <div class="drag-handle" onclick="toggleSheet()"></div>
        <h2 style="margin-top:0;color:var(--accent)">Request Pickup</h2>
        
        <div class="upload-section" onclick="document.getElementById('food-img').click()">
            <input type="file" id="food-img" accept="image/*" class="hidden" onchange="handleImageUpload(event)">
            <img id="preview-img" class="hidden">
            <div id="upload-placeholder">
                <i class="fas fa-camera" style="font-size:2rem; color:#ccc;"></i>
                <div style="color:#888; margin-top:5px;">Tap to Verify Food Freshness</div>
            </div>
        </div>

        <div id="analysis-result" class="hidden result-box">
            <span id="score-val" class="score-val"></span>
            <div class="progress-bg"><div id="score-bar" class="progress-fill"></div></div>
            <div id="classification-msg"></div>
        </div>

        <textarea id="details" rows="2" placeholder="What are you donating? (e.g. 10 Meals)"></textarea>
        
        <div class="date-group">
            <div class="date-field">
                <label>Manufactured Date</label>
                <input type="date" id="mfg_date">
            </div>
            <div class="date-field">
                <label>Expires In</label>
                <div class="expiry-container">
                    <input type="number" id="exp_val" placeholder="3" style="flex:1">
                    <select id="exp_unit" style="flex:2">
                        <option value="Hours">Hours</option>
                        <option value="Days">Days</option>
                        <option value="Weeks">Weeks</option>
                    </select>
                </div>
            </div>
        </div>

        <input id="addr" placeholder="Address (House/Flat No, Street)">
        <input id="pin" placeholder="Pincode">
        <input id="land" placeholder="Landmark (Optional)">
        <button id="btn-submit" onclick="submit()">Find Rescue Driver</button>
    </div>

    <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
    <script>
    const map=L.map('map',{{zoomControl:false}}).setView([25.1376,75.8456],13);L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png').addTo(map);
    let lat,lon,marker; map.on('click',e=>{{lat=e.latlng.lat;lon=e.latlng.lng;if(marker)map.removeLayer(marker);marker=L.marker([lat,lon]).addTo(map)}});
    
    // Panel Logic
    const sheet = document.getElementById('sheet');
    const handle = document.querySelector('.drag-handle');
    let startY = 0; let isDragging = false;

    handle.addEventListener('click', () => {{ if(!isDragging) sheet.classList.toggle('minimized'); }});
    handle.addEventListener('touchstart', e => {{ startY = e.touches[0].clientY; sheet.style.transition = 'none'; }});
    handle.addEventListener('touchmove', e => {{ const delta = e.touches[0].clientY - startY; if(delta > 0) sheet.style.transform = `translateX(-50%) translateY(${{delta}}px)`; }});
    handle.addEventListener('touchend', e => {{ sheet.style.transition = 'transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1)'; const delta = e.changedTouches[0].clientY - startY; if(delta > 50) sheet.classList.add('minimized'); else sheet.classList.remove('minimized'); sheet.style.transform = ''; }});
    handle.addEventListener('mousedown', e => {{ isDragging = true; startY = e.clientY; sheet.style.transition = 'none'; }});
    document.addEventListener('mousemove', e => {{ if(!isDragging) return; const delta = e.clientY - startY; if(delta > 0) sheet.style.transform = `translateX(-50%) translateY(${{delta}}px)`; }});
    document.addEventListener('mouseup', e => {{ if(!isDragging) return; isDragging = false; sheet.style.transition = 'transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1)'; const delta = e.clientY - startY; if(delta > 50) sheet.classList.add('minimized'); else sheet.classList.remove('minimized'); sheet.style.transform = ''; }});

    // --- AI LOGIC (State & Functions) ---
    const state = {{ trainedBadColors: [{{r:90,g:60,b:40}}, {{r:40,g:30,b:20}}], qualityStatus: 'pending' }}; 

    function handleImageUpload(event) {{
        const file = event.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = function(e) {{
            const img = new Image();
            img.onload = function() {{
                document.getElementById('upload-placeholder').classList.add('hidden');
                const preview = document.getElementById('preview-img');
                preview.src = e.target.result;
                preview.classList.remove('hidden');
                analyzePixels(img);
            }};
            img.src = e.target.result;
        }};
        reader.readAsDataURL(file);
    }}

    function analyzePixels(img) {{
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        canvas.width = 100; canvas.height = 100;
        ctx.drawImage(img, 0, 0, 100, 100);
        const data = ctx.getImageData(0, 0, 100, 100).data;
        
        let vibrant=0, dull=0, synthetic=0, foodColor=0, matchedBad=0, total=0;

        for (let i = 0; i < data.length; i += 4) {{
            const r = data[i], g = data[i+1], b = data[i+2];
            total++;
            const avg = (r+g+b)/3;
            const max = Math.max(r,g,b), min = Math.min(r,g,b);
            const sat = max===0?0:(max-min)/max;

            // Synthetic (Plastic/Blue/Neon)
            if ((b > r+15 && b > g+15 && avg > 40) || (r > g+30 && b > g+30 && avg > 100) || (sat > 0.85 && avg > 150)) synthetic++;
            // Food Colors (Warm or Green)
            if (r > b+10 || g > b+10) foodColor++;
            // Trained Bad (Rot)
            state.trainedBadColors.forEach(bad => {{ if (Math.sqrt(Math.pow(r-bad.r,2) + Math.pow(g-bad.g,2) + Math.pow(b-bad.b,2)) < 30) matchedBad++; }});
            // Freshness Heuristic
            if ((r > b+20 && r > g && sat < 0.6 && avg < 150) || avg < 40) dull++; else if (sat > 0.3 && avg > 60) vibrant++; else dull+=0.2;
        }}

        // Decision Tree
        if (synthetic/total > 0.15) return displayResult(0);
        if (foodColor/total < 0.3) return displayResult(0);
        if (matchedBad > (total*0.1)) return displayResult(20);

        const freshRatio = (vibrant + dull) === 0 ? 0 : vibrant / (vibrant + dull);
        let score = Math.floor(freshRatio * 130);
        if (dull > vibrant) score = Math.min(score, 45);
        displayResult(Math.min(99, score));
    }}

    function displayResult(score) {{
        const box = document.getElementById('analysis-result');
        const val = document.getElementById('score-val');
        const bar = document.getElementById('score-bar');
        const txt = document.getElementById('classification-msg');
        const btn = document.getElementById('btn-submit');

        box.classList.remove('hidden');
        val.innerText = score + "/100";
        bar.style.width = score + "%";

        if (score >= 50) {{
            box.className = "result-box pass"; val.className = "score-val pass"; bar.className = "progress-fill pass";
            txt.innerText = "ACCEPTED"; 
            txt.className = "text-emerald-700";
            btn.disabled = false;
            state.qualityStatus = 'approved';
        }} else {{
            box.className = "result-box fail"; val.className = "score-val fail"; bar.className = "progress-fill fail";
            txt.innerText = "REJECTED"; 
            txt.className = "text-red-700";
            btn.disabled = true;
            state.qualityStatus = 'rejected';
        }}
    }}

    async function submit(){{
        const d=document.getElementById('details').value; const a=document.getElementById('addr').value; 
        const p=document.getElementById('pin').value; const mfg=document.getElementById('mfg_date').value;
        const expVal=document.getElementById('exp_val').value;
        const expUnit=document.getElementById('exp_unit').value;

        // Check AI Status
        if(state.qualityStatus !== 'approved') return alert("Please verify food freshness by uploading a photo first.");

        if(!mfg || !expVal) return alert("Please fill in Manufacture and Expiry dates.");
        if(!lat && (!a || !p)) return alert("Please pin location on map OR enter Address & Pincode.");

        const expiryStr = `${{expVal}} ${{expUnit}}`;

        await fetch('/api/create_order',{{
            method:'POST', headers:{{'Content-Type':'application/json'}},
            body:JSON.stringify({{
                pickup_lat:lat, pickup_lon:lon, quantity:10, details:d,
                address:a, pincode:p, landmark:document.getElementById('land').value,
                manufacture_date:mfg, expiry_date:expiryStr
            }})
        }});
        alert("Request Sent!"); location.reload();
    }}
    async function logout(){{await fetch('/api/auth/logout',{{method:'POST'}}); window.location.href="/"}}
    </script></body></html>
    """

# --- 3. DRIVER APP ---
@app.get("/driver", response_class=HTMLResponse)
def driver_app(request: Request):
    # Protect Route
    if not request.cookies.get("fresq_user"): return RedirectResponse(url="/login?target=/driver")
    
    ngos_json = json.dumps(NGO_DATABASE)
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>FresQ Driver</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
        <style>
            :root {{ --bg:#f4f4f9; --glass:rgba(255,255,255,0.95); --accent:#ff6b00; --text:#222; --border:#ddd; }}
            body.dark-mode {{ --bg:#000; --glass:rgba(10,10,10,0.9); --text:#fff; --border:#333; }}
            
            body {{ margin:0; font-family:'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: row; overflow:hidden; background: var(--bg); color: var(--text); }}
            
            /* MAP & LAYOUT */
            #map {{ flex: 1; height: 100%; position: relative; z-index: 1; }}
            
            /* RESPONSIVE SIDEBAR */
            .sidebar {{ 
                width: 360px; height: 100%; background: var(--glass); border-right: 1px solid var(--border); 
                display: flex; flex-direction: column; transition: transform 0.3s ease; z-index: 1001; 
            }}
            
            /* HEADER */
            .header {{ padding: 25px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }}
            .brand {{ font-size: 1.4rem; font-weight: 900; }}
            .brand span {{ color: var(--accent); }}
            
            /* CONTENT LIST */
            .content {{ flex: 1; overflow-y: auto; padding: 20px; }}
            .task-card {{ background: rgba(0,0,0,0.03); border: 1px solid var(--border); padding: 15px; border-radius: 12px; margin-bottom: 15px; border-left: 5px solid #555; }}
            .task-card.pickup {{ border-left-color: #2ecc71; }}
            .task-card.delivery {{ border-left-color: #e74c3c; }}
            
            /* BUTTONS */
            .btn-opt {{ width: 100%; padding: 20px; background: var(--accent); color: white; border: none; font-weight: bold; cursor: pointer; font-size: 1rem; }}
            .actions {{ display: flex; gap: 10px; margin-top: 10px; }}
            .act-btn {{ flex: 1; padding: 10px; border-radius: 8px; border: 1px solid var(--border); background: rgba(255,255,255,0.5); cursor: pointer; font-weight: bold; text-decoration: none; text-align: center; color: var(--text); }}
            .btn-done {{ background: var(--accent); color: white; border: none; }}

            /* PINS */
            .pin-wrap {{ width:36px; height:36px; border-radius:50% 50% 50% 0; transform:rotate(-45deg); display:flex; justify-content:center; align-items:center; box-shadow:0 3px 10px rgba(0,0,0,0.3); border:2px solid white; }}
            .pin-num {{ transform:rotate(45deg); font-size:14px; font-weight:bold; color:white; }}

            /* MOBILE TOGGLE BUTTON */
            .mobile-toggle {{
                position: absolute; bottom: 25px; right: 20px; width: 60px; height: 60px; 
                background: var(--accent); color: white; border-radius: 50%; display: none; 
                align-items: center; justify-content: center; font-size: 1.5rem; 
                box-shadow: 0 4px 15px rgba(0,0,0,0.3); z-index: 2000; cursor: pointer;
            }}

            /* RESPONSIVE LOGIC */
            @media (max-width: 768px) {{
                body {{ flex-direction: column; }}
                .sidebar {{ 
                    position: absolute; top: 0; left: 0; width: 100%; height: 70%; 
                    transform: translateY(-100%); /* Hidden by default */
                    border-right: none; border-bottom: 2px solid var(--accent);
                    box-shadow: 0 10px 40px rgba(0,0,0,0.5);
                }}
                .sidebar.active {{ transform: translateY(0); }}
                .mobile-toggle {{ display: flex; }}
                #map {{ width: 100vw; height: 100vh; }}
            }}
        </style>
    </head>
    <body>
        <div class="mobile-toggle" onclick="toggleSidebar()"><i class="fas fa-list"></i></div>

        <div class="sidebar" id="sidebar">
            <div class="header">
                <div class="brand">Fres<span>Q</span> LOGISTICS</div>
                <i class="fas fa-sign-out-alt" style="cursor:pointer; font-size:1.2rem;" onclick="logout()" title="Logout"></i>
            </div>
            <div class="content" id="list">
                <div style="text-align:center; padding:50px 20px; opacity:0.6;">Waiting for orders...</div>
            </div>
            <button class="btn-opt" onclick="loadMission()">REFRESH ROADMAP</button>
        </div>

        <div id="map"></div>

        <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
        <script src="https://unpkg.com/leaflet-polylineoffset/leaflet.polylineoffset.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet-polylinedecorator/1.6.0/leaflet.polylineDecorator.js"></script>
        
        <script>
            // --- MAP INIT ---
            const DEFAULT_LAT = 25.1376; const DEFAULT_LON = 75.8456;
            const map = L.map('map', {{zoomControl:false}}).setView([DEFAULT_LAT, DEFAULT_LON], 13);
            
            // Map Tiles (Light/Dark Support handled via CSS variables mostly, but tiles need JS swap)
            const lightTiles = 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            const darkTiles = 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            let tileLayer = L.tileLayer(lightTiles).addTo(map);

            // Layers
            const routeLayer = L.layerGroup().addTo(map);
            const createPin = (color, number) => L.divIcon({{className:'custom-pin', html:`<div class="pin-wrap" style="background:${{color}};"><span class="pin-num">${{number}}</span></div>`, iconSize:[36,48], iconAnchor:[18,48], popupAnchor:[0,-40]}});
            
            // State
            let driverLoc = {{lat: DEFAULT_LAT, lon: DEFAULT_LON}};
            let driverMarker;
            let currentOrders = [];
            let isOptimizing = false;

            // --- GPS & DRIVER MARKER ---
            if(navigator.geolocation) {{ navigator.geolocation.getCurrentPosition(p => {{ driverLoc = {{lat:p.coords.latitude, lon:p.coords.longitude}}; updateDriver(); }}); }}
            
            function updateDriver() {{ 
                if(driverMarker) map.removeLayer(driverMarker); 
                driverMarker = L.marker([driverLoc.lat, driverLoc.lon], {{icon:createPin('#3b82f6', 'YOU')}}).addTo(map); 
                loadMission(); // Auto-load on startup
            }}
            updateDriver();

            // --- RESPONSIVE TOGGLE ---
            function toggleSidebar() {{
                document.getElementById('sidebar').classList.toggle('active');
                const icon = document.querySelector('.mobile-toggle i');
                icon.className = icon.className.includes('fa-list') ? 'fas fa-times' : 'fas fa-list';
            }}

            // --- LOGIC: FETCH & OPTIMIZE ---
            const sleep = ms => new Promise(r => setTimeout(r, ms));

            async function loadMission() {{
                isOptimizing = true;
                const btn = document.querySelector('.btn-opt');
                const originalText = btn.innerText;
                btn.innerText = 'CALCULATING...';
                
                try {{
                    // 1. Get Orders
                    const orders = await (await fetch('/api/orders')).json();
                    currentOrders = orders;
                    
                    if(!orders.length) {{
                        document.getElementById('list').innerHTML = "<div style='text-align:center; padding:50px 20px; opacity:0.6;'>No active orders.</div>";
                        btn.innerText = originalText;
                        routeLayer.clearLayers();
                        isOptimizing = false;
                        return;
                    }}

                    // 2. Optimize Route
                    const res = await fetch('/api/optimize', {{
                        method:'POST', headers:{{'Content-Type':'application/json'}},
                        body: JSON.stringify({{vehicle:{{id:"me", capacity:100, start_location:driverLoc}}, orders:orders}})
                    }});
                    const data = await res.json();
                    
                    // 3. Draw & Render
                    await drawRoute(data.route, orders);
                    renderList(data.route, orders);
                    
                    // 4. Mobile UX: Hide sidebar to show map result
                    if(window.innerWidth < 768) toggleSidebar();
                    
                }} catch(e) {{ console.error(e); }}
                
                btn.innerText = originalText;
                isOptimizing = false;
            }}

            // --- LOGIC: DRAW ROUTE (With Separation & Arrows) ---
            async function drawRoute(route, orders) {{
                routeLayer.clearLayers();
                let stopIndex = 1;
                
                // 1. Build Waypoints List
                const pts = route.map(stop => {{
                    if(stop.location_id === 'DEPOT') return driverLoc;
                    
                    const [id, type] = stop.location_id.split('_');
                    const o = orders.find(x => x.id === id);
                    const loc = type === 'pickup' ? o.pickup_location : o.delivery_location;
                    const color = type === 'pickup' ? '#2ecc71' : '#e74c3c';
                    
                    // Draw Stop Pin
                    L.marker([loc.lat, loc.lon], {{icon:createPin(color, stopIndex++)}}).addTo(routeLayer);
                    return loc;
                }});

                // 2. Fetch Legs Individually (To fix Separation & Rate Limit)
                for (let i = 0; i < pts.length - 1; i++) {{
                    await sleep(300); // Throttling for OSRM
                    const start = pts[i];
                    const end = pts[i+1];
                    const url = `https://router.project-osrm.org/route/v1/driving/${{start.lon}},${{start.lat}};${{end.lon}},${{end.lat}}?overview=full&geometries=geojson`;
                    
                    try {{
                        const res = await fetch(url);
                        if (!res.ok) throw new Error('Rate Limit');
                        const osrm = await res.json();
                        
                        if(osrm.routes && osrm.routes[0]) {{
                            const line = osrm.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
                            
                            // MANUAL OFFSET LOGIC
                            // This ensures overlapping lines (going back/forth) are visible
                            const shift = i * 0.00015; 
                            const offsetCoords = line.map(p => [p[0] + shift, p[1] + shift]);
                            
                            // Alternate Colors for clarity
                            const colors = ['#ff6b00', '#ffaa00', '#ff4500'];
                            const legColor = colors[i % colors.length];

                            const poly = L.polyline(offsetCoords, {{ color: legColor, weight: 6, opacity: 0.9 }}).addTo(routeLayer);
                            
                            // Directional Arrows
                            L.polylineDecorator(poly, {{
                                patterns: [{{
                                    offset: '10%', repeat: '60px', 
                                    symbol: L.Symbol.arrowHead({{pixelSize: 14, polygon: true, pathOptions: {{fillOpacity: 1, color: '#fff', stroke: false}}}}) 
                                }}]
                            }}).addTo(routeLayer);
                        }}
                    }} catch(e) {{
                        // Fallback: Dashed Line
                        L.polyline([[start.lat, start.lon], [end.lat, end.lon]], {{ color: 'red', dashArray: '10, 10', weight: 4 }}).addTo(routeLayer);
                    }}
                }}
                
                // Zoom Fit
                const group = new L.featureGroup(routeLayer.getLayers());
                if(group.getLayers().length > 0) map.fitBounds(group.getBounds(), {{padding:[50,50]}});
            }}

            // --- LOGIC: RENDER LIST ---
            function renderList(route, orders) {{
                let stopIndex = 1;
                document.getElementById('list').innerHTML = route.map(stop => {{
                    if(stop.location_id === 'DEPOT') return '';
                    
                    const [id, type] = stop.location_id.split('_');
                    const o = orders.find(x => x.id === id);
                    const title = type === 'pickup' ? o.details : o.ngo_name;
                    const loc = type === 'pickup' ? o.pickup_location : o.delivery_location;
                    const navUrl = `https://www.google.com/maps/dir/?api=1&destination=${{loc.lat}},${{loc.lon}}&travelmode=driving`;
                    
                    return `
                    <div class="task-card ${{type}}">
                        <div style="display:flex; justify-content:space-between;">
                            <b>STEP ${{stopIndex++}} • ${{type.toUpperCase()}}</b>
                            <small style="color:#888">#${{o.id}}</small>
                        </div>
                        <div style="font-size:1.1rem; font-weight:bold; margin:5px 0;">${{title}}</div>
                        
                        <div class="actions">
                            <a href="${{navUrl}}" target="_blank" class="act-btn"><i class="fas fa-location-arrow"></i> NAVIGATE</a>
                            <button class="act-btn btn-done" onclick="markComplete('${{o.id}}', this)">COMPLETE</button>
                        </div>
                    </div>`;
                }}).join('');
            }}

            // --- UTILS ---
            async function markComplete(orderId, btn) {{
                if(!confirm("Mark this task as done?")) return;
                btn.innerHTML = "...";
                await fetch('/api/update_status', {{
                    method:'POST', headers:{{'Content-Type':'application/json'}}, 
                    body: JSON.stringify({{order_id: orderId, status: 'completed'}})
                }});
                loadMission();
            }}

            async function logout() {{
                await fetch('/api/auth/logout', {{method:'POST'}});
                window.location.href = "/";
            }}

            // Auto-poll for new orders
            setInterval(async () => {{ 
                if(!isOptimizing) {{
                    const o = await (await fetch('/api/orders')).json();
                    if(o.length !== currentOrders.length) loadMission(); 
                }}
            }}, 15000);

        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)