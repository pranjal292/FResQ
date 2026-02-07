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
from datetime import datetime, timedelta

# Import the updated Multi-Vehicle Solver
from solver import VRPSolver 

print("\n" + "="*50)
print("✅ LOADING: FRESQ LOGISTICS ENGINE v3.0 (FLEET EDITION)")
print("⚠️  NOTE: If DB schema errors occur, delete 'fresq.db' to reset.")
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
# --- DATABASE SETUP (Clean - No Dummy Driver) ---
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # 1. Create Orders Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, quantity INTEGER, details TEXT,
                pickup_lat REAL, pickup_lon REAL,
                delivery_lat REAL, delivery_lon REAL,
                ngo_name TEXT, status TEXT,
                created_at TIMESTAMP, expiry_hours INTEGER,
                assigned_driver TEXT
            )
        ''')
        
        # 2. Create Users Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                phone TEXT PRIMARY KEY,
                username TEXT,
                password TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 0,
                last_lat REAL DEFAULT 0.0,
                last_lon REAL DEFAULT 0.0
            )
        ''')
        
        # 3. Migration Check (Safe to keep)
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 0")
            cursor.execute("ALTER TABLE users ADD COLUMN last_lat REAL DEFAULT 0.0")
            cursor.execute("ALTER TABLE users ADD COLUMN last_lon REAL DEFAULT 0.0")
        except: pass 
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN assigned_driver TEXT")
        except: pass
        
        conn.commit()
init_db()

# --- NGO DATA ---
NGO_DATABASE = [
    {"name": "Dadabari Relief Center", "city": "Kota", "lat": 25.1580, "lon": 75.8280},
    {"name": "Nayapura Food Bank", "city": "Kota", "lat": 25.1910, "lon": 75.8450},
    {"name": "Talwandi Shelter", "city": "Kota", "lat": 25.1436, "lon": 75.8540},
    {"name": "Kota Station Aid", "city": "Kota", "lat": 25.2215, "lon": 75.8810},
]

# --- Pydantic MODELS ---
class SignupRequest(BaseModel):
    phone: str; username: str; password: str
class LoginRequest(BaseModel):
    phone: str; password: str
class StatusToggle(BaseModel):
    is_active: bool; lat: float; lon: float
class Heartbeat(BaseModel):
    lat: float; lon: float

# Internal Logic Models
class Location(BaseModel):
    lat: float; lon: float
class TimeWindow(BaseModel):
    start: int; end: int
class Vehicle(BaseModel):
    id: str; capacity: int; start_location: Location
class Order(BaseModel):
    id: str; quantity: int; pickup_location: Location; pickup_window: TimeWindow
    delivery_location: Location; delivery_window: TimeWindow; service_time: int
class CustomerOrderRequest(BaseModel):
    pickup_lat: float; pickup_lon: float; quantity: int; details: str; expiry_hours: int
class StatusUpdate(BaseModel):
    order_id: str; status: str

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

# --- DRIVER STATUS API ---
@app.post("/api/driver/toggle")
def toggle_status(req: StatusToggle, request: Request):
    user_phone = request.cookies.get("fresq_user")
    if not user_phone: raise HTTPException(401, "Not logged in")
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute(
            "UPDATE users SET is_active = ?, last_lat = ?, last_lon = ? WHERE phone = ?", 
            (req.is_active, req.lat, req.lon, user_phone)
        )
        conn.commit()
    return {"status": "updated", "mode": "ON DUTY" if req.is_active else "OFF DUTY"}

@app.post("/api/driver/heartbeat")
def heartbeat(req: Heartbeat, request: Request):
    user_phone = request.cookies.get("fresq_user")
    if not user_phone: return {"status": "ignored"}
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute(
            "UPDATE users SET last_lat = ?, last_lon = ? WHERE phone = ?", 
            (req.lat, req.lon, user_phone)
        )
        conn.commit()
    return {"status": "ok"}

# --- ORDER API ---
@app.get("/api/orders")
def get_orders(request: Request):
    """
    Returns ALL pending orders so drivers can see demand heatmaps.
    The frontend distinguishes between 'assigned to me' vs 'others'.
    """
    orders = []
    now = datetime.now()
    user_phone = request.cookies.get("fresq_user")
    
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE status = 'pending'")
        rows = cursor.fetchall()
        
        for row in rows:
            # Schema: 0:id, 1:qty, 2:details, 3:p_lat, 4:p_lon, 5:d_lat, 6:d_lon, 
            # 7:ngo, 8:status, 9:created, 10:expiry, 11:assigned_driver
            
            try: created_at = datetime.fromisoformat(row[9])
            except: created_at = now
            
            expiry_hours = row[10] if row[10] else 24
            
            expiry_time = created_at + timedelta(hours=expiry_hours)
            minutes_remaining = int((expiry_time - now).total_seconds() / 60)
            
            if minutes_remaining < 0: minutes_remaining = 0 

            priority_level = "NORMAL"
            if minutes_remaining <= 120: priority_level = "CRITICAL"
            elif minutes_remaining <= 300: priority_level = "HIGH"

            assigned_to = row[11]
            is_mine = (assigned_to == user_phone) if user_phone else False

            orders.append({
                "id": row[0], 
                "quantity": row[1], 
                "details": row[2],
                "pickup_location": {"lat": row[3], "lon": row[4]},
                "pickup_window": {"start": 0, "end": minutes_remaining},
                "delivery_location": {"lat": row[5], "lon": row[6]},
                "ngo_name": row[7], 
                "status": row[8],
                "priority_level": priority_level,
                "assigned_driver": assigned_to,
                "is_mine": is_mine
            })
            
    return orders

@app.post("/api/create_order")
def create_order(req: CustomerOrderRequest):
    new_id = str(uuid.uuid4())[:8]
    ngo = min(NGO_DATABASE, key=lambda n: abs(n['lat'] - req.pickup_lat) + abs(n['lon'] - req.pickup_lon))
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute('''
            INSERT INTO orders (id, quantity, details, pickup_lat, pickup_lon, delivery_lat, delivery_lon, ngo_name, status, created_at, expiry_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (new_id, req.quantity, req.details, req.pickup_lat, req.pickup_lon, ngo['lat'], ngo['lon'], ngo['name'], 'pending', datetime.now().isoformat(), req.expiry_hours))
        conn.commit()
    return {"status": "success", "order_id": new_id, "assigned_ngo": ngo['name']}

@app.post("/api/update_status")
def update_status(upd: StatusUpdate):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("UPDATE orders SET status = ? WHERE id = ?", (upd.status, upd.order_id))
        conn.commit()
    return {"status": "success"}

# --- FLEET DISPATCH LOGIC ---
@app.post("/api/dispatch")
def dispatch_orders(request: Request):
    """
    Core logic: Takes ALL active drivers and ALL pending orders,
    optimizes the fleet routes, assigns them in DB, 
    and returns the specific route for the requesting driver.
    """
    user_phone = request.cookies.get("fresq_user")
    
    with sqlite3.connect(DB_NAME) as conn:
        # Get Active Drivers (The Fleet)
        drivers_db = conn.cursor().execute("SELECT phone, last_lat, last_lon FROM users WHERE is_active = 1").fetchall()
        # Get Pending Orders (The Demand)
        orders_db = conn.cursor().execute("SELECT * FROM orders WHERE status = 'pending'").fetchall()

    if not drivers_db:
        return {"error": "No drivers are currently On Duty."}
    if not orders_db:
        return {"route": [], "info": "No pending orders."}

    # 1. Convert DB Drivers to Vehicle Objects
    vehicles = []
    for d in drivers_db:
        # Ensure lat/lon are valid (default 0.0 means GPS not synced yet)
        if d[1] == 0.0 and d[2] == 0.0: continue 
        
        v = Vehicle(
            id=d[0], # Phone number is ID
            capacity=100, 
            start_location=Location(lat=d[1], lon=d[2])
        )
        vehicles.append(v)
    
    if not vehicles:
        return {"error": "Drivers are on duty but have no GPS signal."}

    # 2. Convert DB Orders to Order Objects
    orders = []
    now = datetime.now()
    for row in orders_db:
        try: created = datetime.fromisoformat(row[9])
        except: created = now
        expiry = row[10] if row[10] else 24
        mins_left = int((created + timedelta(hours=expiry) - now).total_seconds()/60)
        
        o = Order(
            id=row[0], quantity=row[1],
            pickup_location=Location(lat=row[3], lon=row[4]),
            pickup_window=TimeWindow(start=0, end=mins_left),
            delivery_location=Location(lat=row[5], lon=row[6]),
            delivery_window=TimeWindow(start=0, end=mins_left),
            service_time=10
        )
        orders.append(o)

    # 3. RUN GLOBAL OPTIMIZATION
    try:
        routes_map, total_dist = solver.solve_route(vehicles, orders)
    except Exception as e:
        print(f"Solver Error: {e}")
        return {"error": "Optimization engine failed."}
    
    # 4. UPDATE ASSIGNMENTS IN DB
    with sqlite3.connect(DB_NAME) as conn:
        # Clear old pending assignments first? No, just overwrite.
        for vid, route in routes_map.items():
            for step in route:
                # Steps location_id look like "ORDERID_pickup"
                if "pickup" in step["location_id"] or "delivery" in step["location_id"]:
                    oid = step["location_id"].split("_")[0]
                    conn.cursor().execute("UPDATE orders SET assigned_driver = ? WHERE id = ?", (vid, oid))
        conn.commit()

    # 5. Return route ONLY for the requesting user
    my_route = routes_map.get(user_phone, [])
    
    return {
        "route": my_route, 
        "total_fleet_distance": total_dist,
        "active_drivers": len(vehicles),
        "total_orders": len(orders)
    }

# --- HTML FRONTEND ---

@app.get("/", response_class=HTMLResponse)
def landing_page():
    return """
    <!DOCTYPE html><html><head><title>FresQ</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>:root{--bg:#f4f4f9;--text:#222;} body.dark{--bg:#111;--text:#fff;} body{background:var(--bg);color:var(--text);font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}
    .card{text-align:center;padding:40px;border:1px solid #ccc;border-radius:20px;} a{display:block;margin:10px;padding:15px;background:#ff6b00;color:white;text-decoration:none;border-radius:10px;font-weight:bold;}</style>
    </head><body><div class="card"><h1>FresQ Logistics</h1><p>Food Rescue Fleet</p>
    <a href="/customer">I am a Donor</a><a href="/driver" style="background:#333;">I am a Driver</a>
    </div></body></html>
    """

# --- 2. LOGIN PAGE (Updated with Sign Up) ---
@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FresQ Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
        </style>
    </head>
    <body>
        <div class="theme-toggle" onclick="toggleTheme()"><i class="fas fa-moon" id="theme-icon"></i></div>
        
        <div class="box">
            <h2 id="title">Login</h2>
            
            <div id="signup-fields" class="hidden">
                <input type="text" id="username" placeholder="Full Name">
            </div>
            
            <input type="tel" id="phone" placeholder="Phone Number">
            <input type="password" id="pass" placeholder="Password">
            
            <button onclick="handleAuth()" id="btn">Login</button>
            
            <div class="toggle" onclick="toggleMode()" id="mode">Need an account? Sign Up</div>
        </div>

        <script>
            let isLogin = true;

            function toggleTheme() {
                document.body.classList.toggle('dark-mode');
                const isDark = document.body.classList.contains('dark-mode');
                document.getElementById('theme-icon').className = isDark ? 'fas fa-sun' : 'fas fa-moon';
            }

            function toggleMode() {
                isLogin = !isLogin;
                // Update UI text
                document.getElementById('title').innerText = isLogin ? "Login" : "Create Account";
                document.getElementById('btn').innerText = isLogin ? "Login" : "Sign Up";
                document.getElementById('mode').innerText = isLogin ? "Need an account? Sign Up" : "Already have an account? Login";
                // Show/Hide Username field
                document.getElementById('signup-fields').classList.toggle('hidden');
            }

            async function handleAuth() {
                const phone = document.getElementById('phone').value;
                const password = document.getElementById('pass').value;
                const target = new URLSearchParams(window.location.search).get('target') || '/customer'; // Default redirect

                if (!phone || !password) return alert("Please fill in all fields.");

                if (isLogin) {
                    // LOGIN LOGIC
                    const res = await fetch('/api/auth/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({phone, password})
                    });
                    
                    if (res.ok) {
                        window.location.href = target;
                    } else {
                        alert("Invalid Credentials");
                    }
                } else {
                    // SIGNUP LOGIC
                    const username = document.getElementById('username').value;
                    if (!username) return alert("Name is required for signup.");

                    const res = await fetch('/api/auth/signup', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({phone, username, password})
                    });
                    
                    if (res.ok) {
                        alert("Account Created! Please Login.");
                        toggleMode(); // Switch back to login view
                    } else {
                        const data = await res.json();
                        alert("Signup Failed: " + (data.detail || "Phone number already exists."));
                    }
                }
            }
        </script>
    </body>
    </html>
    """
@app.get("/customer", response_class=HTMLResponse)
def customer_app(request: Request):
    if not request.cookies.get("fresq_user"): return RedirectResponse(url="/login?target=/customer")
    
    # Pass NGO data to frontend for visual reference
    ngos_json = json.dumps(NGO_DATABASE)
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>FresQ Donor</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
        <style>
            :root {{ --bg:#f4f4f9; --glass:rgba(255,255,255,0.95); --accent:#ff6b00; --text:#222; --border:#ddd; }}
            body.dark-mode {{ --bg:#000; --glass:rgba(10,10,10,0.95); --text:#fff; --border:#333; }}
            
            body {{ margin:0; font-family:'Segoe UI', sans-serif; height: 100vh; overflow:hidden; background: var(--bg); color: var(--text); }}
            
            #map {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; }}
            
            /* FLOATING PANEL */
            .panel {{ 
                position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
                width: 90%; max-width: 500px; background: var(--glass); 
                backdrop-filter: blur(10px); padding: 25px; border-radius: 20px; 
                box-shadow: 0 10px 40px rgba(0,0,0,0.2); z-index: 1000; border: 1px solid var(--border);
                transition: 0.3s;
            }}
            
            h2 {{ margin: 0 0 15px 0; color: var(--accent); font-size: 1.5rem; display:flex; justify-content:space-between; align-items:center; }}
            
            .input-group {{ margin-bottom: 12px; }}
            label {{ display: block; font-size: 0.8rem; opacity: 0.7; margin-bottom: 5px; }}
            input, select {{ width: 100%; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: rgba(0,0,0,0.05); color: var(--text); font-size: 1rem; box-sizing: border-box; }}
            
            button {{ width: 100%; padding: 15px; background: var(--accent); color: white; border: none; border-radius: 10px; font-weight: bold; font-size: 1.1rem; cursor: pointer; margin-top: 10px; }}
            button:active {{ transform: scale(0.98); }}
            
            .location-hint {{ font-size: 0.85rem; color: #7f8c8d; text-align: center; margin-bottom: 15px; padding: 10px; background: rgba(0,0,0,0.03); border-radius: 8px; border: 1px dashed var(--border); }}
            
            /* HEADER BUTTONS */
            .top-btns {{ position: absolute; top: 20px; right: 20px; z-index: 1000; display: flex; gap: 10px; }}
            .icon-btn {{ width: 40px; height: 40px; background: var(--glass); border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; border: 1px solid var(--border); font-size: 1.1rem; color: var(--text); }}
            .home-btn {{ position: absolute; top: 20px; left: 20px; z-index: 1000; text-decoration: none; }}
            
            /* Loading Overlay */
            .overlay {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 2000; display: none; justify-content: center; align-items: center; color: white; flex-direction: column; }}
            .spinner {{ width: 40px; height: 40px; border: 4px solid #fff; border-top: 4px solid var(--accent); border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 15px; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <a href="/" class="icon-btn home-btn"><i class="fas fa-home"></i></a>
        <div class="top-btns">
            <div class="icon-btn" onclick="toggleTheme()"><i class="fas fa-moon" id="theme-icon"></i></div>
            <div class="icon-btn" onclick="logout()"><i class="fas fa-sign-out-alt"></i></div>
        </div>

        <div id="map"></div>

        <div class="panel">
            <h2>Donate Food <i class="fas fa-hand-holding-heart"></i></h2>
            
            <div class="location-hint" id="loc-status">
                <i class="fas fa-map-marker-alt" style="color:#e74c3c"></i> Tap map to select pickup location
            </div>

            <div class="input-group">
                <label>Food Details</label>
                <input type="text" id="details" placeholder="e.g. 50 Meals, Rice & Curry">
            </div>
            
            <div style="display:flex; gap:10px;">
                <div class="input-group" style="flex:1">
                    <label>Quantity (kg)</label>
                    <input type="number" id="qty" value="10">
                </div>
                <div class="input-group" style="flex:1">
                    <label>Expires In (Hours)</label>
                    <input type="number" id="expiry" value="24">
                </div>
            </div>

            <button onclick="submitOrder()">FIND A DRIVER</button>
        </div>

        <div class="overlay" id="loader">
            <div class="spinner"></div>
            <div>Broadcasting to Fleet...</div>
        </div>

        <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
        <script>
            // --- MAP INIT ---
            const map = L.map('map', {{zoomControl:false}}).setView([25.1825, 75.8236], 13);
            const lightTiles = 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            const darkTiles = 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            let tileLayer = L.tileLayer(lightTiles).addTo(map);

            // NGO Markers (Reference)
            const ngos = {ngos_json};
            ngos.forEach(ngo => {{
                L.circleMarker([ngo.lat, ngo.lon], {{
                    color: '#666', radius: 4, fillColor: '#fff', fillOpacity: 1
                }}).addTo(map).bindPopup("NGO: " + ngo.name);
            }});

            // Pickup Pin Logic
            let pickupMarker;
            let pickupLoc = null;

            map.on('click', function(e) {{
                if(pickupMarker) map.removeLayer(pickupMarker);
                
                pickupLoc = e.latlng;
                
                const icon = L.divIcon({{
                    className: 'p',
                    html: '<div style="width:30px;height:30px;background:#2ecc71;border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:3px solid white;box-shadow:0 3px 10px rgba(0,0,0,0.3);"></div>',
                    iconSize: [30, 42],
                    iconAnchor: [15, 42]
                }});
                
                pickupMarker = L.marker(e.latlng, {{icon: icon}}).addTo(map);
                
                document.getElementById('loc-status').innerHTML = 
                    `<span style="color:#2ecc71"><b>Location Set:</b> ${{e.latlng.lat.toFixed(4)}}, ${{e.latlng.lng.toFixed(4)}}</span>`;
            }});

            // --- FUNCTIONS ---
            async function submitOrder() {{
                if(!pickupLoc) return alert("Please tap the map to select a pickup location!");
                
                const details = document.getElementById('details').value;
                if(!details) return alert("Please describe the food.");

                document.getElementById('loader').style.display = 'flex';

                const payload = {{
                    pickup_lat: pickupLoc.lat,
                    pickup_lon: pickupLoc.lng,
                    quantity: parseInt(document.getElementById('qty').value),
                    details: details,
                    expiry_hours: parseInt(document.getElementById('expiry').value)
                }};

                try {{
                    const res = await fetch('/api/create_order', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify(payload)
                    }});
                    
                    const data = await res.json();
                    
                    document.getElementById('loader').style.display = 'none';
                    if(data.status === 'success') {{
                        alert("✅ Request Sent! Assigned to NGO: " + data.assigned_ngo);
                        location.reload();
                    }} else {{
                        alert("Error: " + JSON.stringify(data));
                    }}
                }} catch(e) {{
                    document.getElementById('loader').style.display = 'none';
                    alert("Network Error");
                }}
            }}

            function toggleTheme() {{
                document.body.classList.toggle('dark-mode');
                const isDark = document.body.classList.contains('dark-mode');
                document.getElementById('theme-icon').className = isDark ? 'fas fa-sun' : 'fas fa-moon';
                map.removeLayer(tileLayer);
                tileLayer = L.tileLayer(isDark ? darkTiles : lightTiles).addTo(map);
            }}

            async function logout() {{
                await fetch('/api/auth/logout', {{method:'POST'}});
                window.location.href = "/";
            }}
        </script>
    </body>
    </html>
    """
# --- 3. DRIVER APP (Final Version: GPS + Permissions + Safety) ---
@app.get("/driver", response_class=HTMLResponse)
def driver_app(request: Request):
    user_phone = request.cookies.get("fresq_user")
    
    # 1. Check if cookie exists
    if not user_phone: 
        return RedirectResponse(url="/login?target=/driver")
    
    # 2. Check if User actually exists in DB (Safety check)
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.cursor().execute("SELECT is_active FROM users WHERE phone = ?", (user_phone,)).fetchone()
    
    if not row:
        # User deleted from DB? Force Logout.
        response = RedirectResponse(url="/login?target=/driver")
        response.delete_cookie("fresq_user")
        return response
    
    # 3. Get DB State
    db_is_active = "true" if row[0] else "false"
    
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
            body.dark-mode {{ --bg:#000; --glass:rgba(10,10,10,0.95); --text:#fff; --border:#333; }}
            
            body {{ margin:0; font-family:'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: row; overflow:hidden; background: var(--bg); color: var(--text); }}
            #map {{ flex: 1; height: 100%; position: relative; z-index: 1; }}
            
            /* SIDEBAR */
            .sidebar {{ width: 360px; height: 100%; background: var(--glass); border-right: 1px solid var(--border); display: flex; flex-direction: column; z-index: 1001; }}
            .header {{ padding: 20px; border-bottom: 1px solid var(--border); }}
            .brand {{ font-size: 1.4rem; font-weight: 900; display:flex; justify-content:space-between; align-items:center; }}

            /* BLURRED DRIVER PIN ANIMATION */
            .driver-pin {{
                width: 20px; height: 20px;
                background: #3b82f6;
                border: 3px solid white;
                border-radius: 50%;
                box-shadow: 0 0 15px 5px rgba(59, 130, 246, 0.6);
                animation: pulse-blur 2s infinite;
            }}
            @keyframes pulse-blur {{
                0% {{ box-shadow: 0 0 5px 2px rgba(59, 130, 246, 0.4); }}
                50% {{ box-shadow: 0 0 20px 10px rgba(59, 130, 246, 0.7); }}
                100% {{ box-shadow: 0 0 5px 2px rgba(59, 130, 246, 0.4); }}
            }}

            /* DUTY TOGGLE */
            .duty-switch {{ display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.05); padding: 10px 15px; border-radius: 10px; margin-top: 10px; }}
            .switch {{ position: relative; display: inline-block; width: 50px; height: 26px; }}
            .switch input {{ opacity: 0; width: 0; height: 0; }}
            .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }}
            .slider:before {{ position: absolute; content: ""; height: 20px; width: 20px; left: 3px; bottom: 3px; background-color: white; transition: .4s; border-radius: 50%; }}
            input:checked + .slider {{ background-color: #2ecc71; }}
            input:checked + .slider:before {{ transform: translateX(24px); }}
            
            .content {{ flex: 1; overflow-y: auto; padding: 20px; }}
            .task-card {{ background: rgba(0,0,0,0.03); border: 1px solid var(--border); padding: 15px; border-radius: 12px; margin-bottom: 15px; border-left: 5px solid #555; }}
            .btn-opt {{ width: 100%; padding: 20px; background: var(--accent); color: white; border: none; font-weight: bold; cursor: pointer; }}
            
            /* RECENTER BTN */
            .recenter-btn {{
                position: absolute; bottom: 20px; right: 20px; z-index: 1000;
                width: 50px; height: 50px; border-radius: 50%;
                background: var(--accent); color: white;
                display: flex; align-items: center; justify-content: center;
                font-size: 1.5rem; cursor: pointer;
                box-shadow: 0 4px 10px rgba(0,0,0,0.3);
            }}
            
            /* PINS */
            .pin-wrap {{ width:30px; height:30px; border-radius:50% 50% 50% 0; transform:rotate(-45deg); display:flex; justify-content:center; align-items:center; border:2px solid white; box-shadow:0 3px 5px rgba(0,0,0,0.3); }}
            .pin-num {{ transform:rotate(45deg); font-size:12px; font-weight:bold; color:white; }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="header">
                <div class="brand">
                    <span>Fres<span style="color:var(--accent)">Q</span></span>
                    <div>
                         <i class="fas fa-moon" onclick="toggleTheme()" id="theme-icon" style="cursor:pointer; margin-right:15px;"></i>
                         <a href="/"><i class="fas fa-home" style="color:var(--text)"></i></a>
                    </div>
                </div>
                <div class="duty-switch">
                    <span id="status-label" style="font-weight:bold; color:#7f8c8d">OFF DUTY</span>
                    <label class="switch">
                        <input type="checkbox" id="dutyToggle" onchange="requestAndToggleDuty()">
                        <span class="slider"></span>
                    </label>
                </div>
            </div>
            
            <div class="content" id="list">
                <div style="text-align:center; padding:50px 20px; opacity:0.6;" id="prompt-text">
                    Go On Duty to track location.
                </div>
            </div>
            <button class="btn-opt" onclick="dispatch()" id="optBtn" disabled style="opacity:0.5">SYNC FLEET</button>
        </div>

        <div id="map">
            <div class="recenter-btn" onclick="recenterMap()"><i class="fas fa-crosshairs"></i></div>
        </div>
        
        <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
        
        <script>
            // --- STATE ---
            let isOnDuty = {db_is_active}; 
            let driverLoc = null;
            let driverMarker = null;
            let watchId = null;
            
            // --- MAP INIT ---
            const map = L.map('map', {{zoomControl:false}}).setView([25.1825, 75.8236], 13);
            const lightTiles = 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            const darkTiles = 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            let tileLayer = L.tileLayer(lightTiles).addTo(map);
            const routeLayer = L.layerGroup().addTo(map);

            // --- ON LOAD ---
            window.onload = function() {{
                const toggle = document.getElementById('dutyToggle');
                toggle.checked = isOnDuty;
                updateUI(isOnDuty);
                
                if (isOnDuty) {{
                    // Attempt to restore tracking if page refreshed while on duty
                    requestAndToggleDuty(true); 
                }}
            }};

            // --- GPS & PERMISSIONS ---
            function requestAndToggleDuty(isRestoring = false) {{
                const toggle = document.getElementById('dutyToggle');
                const desiredState = toggle.checked;

                if (desiredState) {{
                    if (!navigator.geolocation) {{
                        alert("Geolocation not supported.");
                        toggle.checked = false; return;
                    }}
                    
                    // Request GPS
                    navigator.geolocation.getCurrentPosition(
                        (pos) => {{
                            // Success
                            isOnDuty = true;
                            startTracking();
                            handleToggleAPI(true);
                        }},
                        (err) => {{
                            // Denied
                            if (!isRestoring) alert("Location access required for Duty mode.");
                            toggle.checked = false;
                            isOnDuty = false;
                            updateUI(false);
                        }},
                        {{ enableHighAccuracy: true }}
                    );
                }} else {{
                    isOnDuty = false;
                    stopTracking();
                    handleToggleAPI(false);
                }}
            }}

            function startTracking() {{
                if (watchId) return;
                watchId = navigator.geolocation.watchPosition(
                    (p) => {{
                        driverLoc = {{lat: p.coords.latitude, lon: p.coords.longitude}};
                        updateDriverMarker();
                        // Optional: Send heartbeat on every move? Or rely on interval?
                        // Better to rely on interval to save bandwidth, 
                        // but update local marker immediately.
                    }},
                    (e) => console.error(e),
                    {{ enableHighAccuracy: true }}
                );
                updateUI(true);
            }}

            function stopTracking() {{
                if (watchId) navigator.geolocation.clearWatch(watchId);
                watchId = null;
                if (driverMarker) map.removeLayer(driverMarker);
                updateUI(false);
            }}

            function updateDriverMarker() {{
                if (!driverLoc) return;
                if (driverMarker) map.removeLayer(driverMarker);
                
                // Custom Blurred Pin
                const icon = L.divIcon({{
                    className: 'custom-div-icon',
                    html: '<div class="driver-pin"></div>',
                    iconSize: [20, 20],
                    iconAnchor: [10, 10]
                }});
                
                driverMarker = L.marker([driverLoc.lat, driverLoc.lon], {{icon: icon}}).addTo(map);
            }}
            
            function recenterMap() {{
                if(driverLoc) map.setView([driverLoc.lat, driverLoc.lon], 15);
            }}

            // --- API INTERACTIONS ---
            async function handleToggleAPI(status) {{
                // Fallback 0,0 if loc not ready yet
                const lat = driverLoc ? driverLoc.lat : 0;
                const lon = driverLoc ? driverLoc.lon : 0;
                
                await fetch('/api/driver/toggle', {{
                    method: 'POST', headers: {{'Content-Type':'application/json'}},
                    body: JSON.stringify({{is_active: status, lat: lat, lon: lon}})
                }});
                
                if (status) dispatch(); 
            }}
            
            async function sendHeartbeat() {{
                if(!isOnDuty || !driverLoc) return;
                await fetch('/api/driver/heartbeat', {{
                    method: 'POST', headers: {{'Content-Type':'application/json'}},
                    body: JSON.stringify({{lat: driverLoc.lat, lon: driverLoc.lon}})
                }});
            }}

            async function dispatch() {{
                if(!isOnDuty) return;
                const btn = document.getElementById('optBtn');
                btn.innerText = "OPTIMIZING...";
                
                try {{
                    // 1. Get Route
                    const res = await fetch('/api/dispatch', {{method:'POST'}});
                    const data = await res.json();
                    
                    if(data.error) {{
                        console.warn(data.error);
                        // If "No drivers", try sending heartbeat to re-register
                        if(data.error.includes("No drivers")) sendHeartbeat();
                        btn.innerText = "SYNC FLEET";
                        return;
                    }}
                    
                    // 2. Get Details
                    const ordersRes = await fetch('/api/orders');
                    const allOrders = await ordersRes.json();
                    
                    drawRoute(data.route, allOrders);
                    renderList(data.route, allOrders);
                    
                }} catch(e) {{ console.error(e); }}
                btn.innerText = "SYNC FLEET";
            }}

            // --- RENDERERS ---
            function renderList(route, orders) {{
                const list = document.getElementById('list');
                if(!route || route.length === 0) {{
                     list.innerHTML = "<div style='text-align:center; padding:30px; opacity:0.6;'>No orders assigned yet.<br>Wait for dispatch.</div>";
                     return;
                }}
                
                let html = "";
                let stepNum = 1;
                route.forEach(step => {{
                    if(step.type === 'start') return;
                    const id = step.location_id.split('_')[0];
                    const order = orders.find(o => o.id == id);
                    if(!order) return;
                    
                    const isPickup = step.type === 'pickup';
                    const color = isPickup ? '#2ecc71' : '#e74c3c';
                    
                    html += `
                    <div class="task-card" style="border-left-color:${{color}}">
                        <div style="display:flex;justify-content:space-between;font-size:0.8rem;font-weight:bold;">
                            <span>STEP ${{stepNum++}} • ${{step.type.toUpperCase()}}</span>
                            <span style="opacity:0.5">#${{id.substring(0,4)}}</span>
                        </div>
                        <div style="margin:5px 0; font-weight:bold;">${{isPickup ? order.details : order.ngo_name}}</div>
                        <div style="font-size:0.8rem; color:${{order.priority_level === 'CRITICAL' ? 'red' : 'green'}}">
                            ${{order.priority_level}} PRIORITY
                        </div>
                    </div>`;
                }});
                list.innerHTML = html;
            }}

            function drawRoute(route, orders) {{
                routeLayer.clearLayers();
                if(!route || route.length === 0) return;
                
                const points = [];
                let stepNum = 1;
                
                if (driverLoc) points.push(driverLoc);

                route.forEach(step => {{
                    if(step.type === 'start') return;
                    const id = step.location_id.split('_')[0];
                    const order = orders.find(o => o.id == id);
                    if(!order) return;
                    
                    const loc = step.type === 'pickup' ? order.pickup_location : order.delivery_location;
                    points.push(loc);
                    
                    const color = step.type === 'pickup' ? '#2ecc71' : '#e74c3c';
                    const iconHtml = `<div class="pin-wrap" style="background:${{color}}"><span class="pin-num">${{stepNum++}}</span></div>`;
                    const icon = L.divIcon({{className:'p', html:iconHtml, iconSize:[30,42], iconAnchor:[15,42]}});
                    
                    L.marker([loc.lat, loc.lon], {{icon}}).addTo(routeLayer);
                }});
                
                if(points.length > 1) {{
                   const latlngs = points.map(p => [p.lat, p.lon]);
                   L.polyline(latlngs, {{color:'#ff6b00', weight:5}}).addTo(routeLayer);
                   // Only fit bounds if we aren't actively driving (avoids jumping map)
                   // map.fitBounds(latlngs, {{padding:[50,50]}});
                }}
            }}

            // --- UTILS ---
            function updateUI(active) {{
                const label = document.getElementById('status-label');
                const btn = document.getElementById('optBtn');
                
                label.innerText = active ? "ON DUTY" : "OFF DUTY";
                label.style.color = active ? "#2ecc71" : "#7f8c8d";
                btn.disabled = !active;
                btn.style.opacity = active ? "1" : "0.5";
                
                if(!active) {{
                    document.getElementById('list').innerHTML = "<div style='text-align:center; padding:50px 20px; opacity:0.6;'>Go On Duty to track location.</div>";
                    routeLayer.clearLayers();
                }}
            }}

            function toggleTheme() {{
                document.body.classList.toggle('dark-mode');
                const isDark = document.body.classList.contains('dark-mode');
                document.getElementById('theme-icon').className = isDark ? 'fas fa-sun' : 'fas fa-moon';
                map.removeLayer(tileLayer);
                tileLayer = L.tileLayer(isDark ? darkTiles : lightTiles).addTo(map);
            }}

            // Loops
            setInterval(() => {{ if(isOnDuty) sendHeartbeat(); }}, 10000); // GPS Sync
            setInterval(() => {{ if(isOnDuty) dispatch(); }}, 30000);      // Route Sync
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)