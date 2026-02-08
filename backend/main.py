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

# --- IMPORT SOLVER ---
# Ensure you have the 'solver.py' file in the same directory.
# If you don't have it, create a dummy one or use the one from previous steps.
try:
    from solver import VRPSolver
except ImportError:
    print("⚠️  WARNING: 'solver.py' not found. using dummy solver.")
    class VRPSolver:
        def solve_route(self, vehicles, orders):
            return {}, 0
            
print("\n" + "="*50)
print("✅ LOADING: FRESQ LOGISTICS ENGINE v3.1 (FINAL)")
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
    pickup_lat: float; pickup_lon: float; quantity: int; details: str; expiry_hours: float
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
    user_phone = request.cookies.get("fresq_user")
    
    with sqlite3.connect(DB_NAME) as conn:
        # 1. GET ALL ACTIVE DRIVERS (The Fleet)
        drivers_db = conn.cursor().execute("SELECT phone, last_lat, last_lon FROM users WHERE is_active = 1").fetchall()
        
        # 2. GET ALL PENDING ORDERS (The Demand)
        orders_db = conn.cursor().execute("SELECT * FROM orders WHERE status = 'pending'").fetchall()

    if not drivers_db:
        return {"error": "No drivers are currently On Duty."}
    
    # If no orders, return empty route
    if not orders_db:
        return {"route": []}

    # Convert DB Drivers to Vehicle Objects
    vehicles = []
    for d in drivers_db:
        # Skip if GPS is 0,0 (invalid)
        if d[1] == 0.0 and d[2] == 0.0: continue
        vehicles.append(Vehicle(
            id=d[0], capacity=100, start_location=Location(lat=d[1], lon=d[2])
        ))

    # Convert DB Orders to Order Objects
    orders = []
    now = datetime.now()
    for row in orders_db:
        # row: 0:id, ..., 9:created_at, 10:expiry
        try: created = datetime.fromisoformat(row[9])
        except: created = now
        expiry = row[10] or 24
        
        mins_left = int((created + timedelta(hours=expiry) - now).total_seconds()/60)
        
        orders.append(Order(
            id=row[0], quantity=row[1],
            pickup_location=Location(lat=row[3], lon=row[4]),
            pickup_window=TimeWindow(start=0, end=mins_left),
            delivery_location=Location(lat=row[5], lon=row[6]),
            delivery_window=TimeWindow(start=0, end=mins_left),
            service_time=10
        ))

    # 3. RUN GLOBAL OPTIMIZATION
    # This solves for EVERYONE at once
    routes_map, total_dist = solver.solve_route(vehicles, orders)

    # 4. SAVE ASSIGNMENTS
    with sqlite3.connect(DB_NAME) as conn:
        for vid, route in routes_map.items():
            for step in route:
                if step["type"] in ['pickup', 'delivery']:
                    oid = step["location_id"].split("_")[0]
                    conn.cursor().execute("UPDATE orders SET assigned_driver = ? WHERE id = ?", (vid, oid))
        conn.commit()

    # 5. RETURN ONLY MY ROUTE
    # The solver optimized for everyone, but I only need to see MY steps.
    my_route = routes_map.get(user_phone, [])
    
    return {"route": my_route, "total_fleet_distance": total_dist}

# --- HTML FRONTEND ---

@app.get("/", response_class=HTMLResponse)
def landing_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FresQ</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            /* --- 1. DEFAULT LIGHT THEME (Base Variables) --- */
            :root { 
                --bg: #f4f4f9; 
                --text: #222; 
                --card-bg: rgba(255,255,255,0.85);
                --btn-primary: #ff6b00;
                --btn-secondary: #222;
                --toggle-bg: rgba(0,0,0,0.05);
                --shadow: rgba(0,0,0,0.1);
            } 
            
            /* --- 2. DARK THEME OVERRIDES (Applied when 'dark' class is present) --- */
            body.dark { 
                --bg: #111; 
                --text: #fff; 
                --card-bg: rgba(20,20,20,0.8);
                --btn-secondary: #333;
                --toggle-bg: rgba(255,255,255,0.15);
                --shadow: rgba(0,0,0,0.5);
            } 
            
            /* --- 3. LAYOUT & ANIMATION --- */
            body { 
                background: var(--bg); 
                color: var(--text); 
                font-family: 'Segoe UI', sans-serif; 
                display: flex; 
                justify-content: center; 
                align-items: center; 
                height: 100vh; 
                margin: 0; 
                padding: 20px; 
                box-sizing: border-box; 
                transition: background 0.3s ease, color 0.3s ease;
            }
            
            .card { 
                text-align: center; 
                padding: 40px; 
                border: 1px solid rgba(255,255,255,0.1); 
                border-radius: 32px; 
                background: var(--card-bg); 
                width: 100%; 
                max-width: 380px; 
                box-shadow: 0 20px 60px var(--shadow); 
                backdrop-filter: blur(20px);
                transition: background 0.3s ease, box-shadow 0.3s ease;
            } 
            
            h1 { margin-bottom: 5px; font-size: 2.2rem; font-weight: 800; letter-spacing: -1px; }
            p { margin-top: 0; opacity: 0.6; font-size: 1.1rem; }
            
            /* --- 4. BUTTONS --- */
            a { 
                display: block; 
                margin: 15px 0; 
                padding: 20px; 
                background: var(--btn-primary); 
                color: white; 
                text-decoration: none; 
                border-radius: 24px; 
                font-weight: bold; 
                font-size: 1.1rem;
                box-shadow: 0 8px 20px rgba(255, 107, 0, 0.25);
                transition: transform 0.2s, box-shadow 0.2s;
            }
            
            a:active { transform: scale(0.97); }
            
            a.driver-btn { 
                background: var(--btn-secondary); 
                box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2); 
            }
            
            /* --- 5. THEME TOGGLE --- */
            .theme-toggle { 
                position: absolute; 
                top: 25px; 
                right: 25px; 
                background: var(--toggle-bg); 
                width: 50px; 
                height: 50px; 
                border-radius: 50%; 
                display: flex; 
                align-items: center; 
                justify-content: center; 
                cursor: pointer; 
                font-size: 1.2rem;
                transition: background 0.3s, transform 0.2s;
            }
            .theme-toggle:hover { transform: scale(1.1); }
            .theme-toggle:active { transform: scale(0.95); }
        </style>
    </head>
    <body>
        <div class="theme-toggle" onclick="toggleTheme()" title="Toggle Dark Mode">
            <i class="fas fa-moon" id="theme-icon"></i>
        </div>
        
        <div class="card">
            <h1>FresQ Logistics</h1>
            <p>Food Rescue Fleet</p>
            
            <div style="margin-top:40px;">
                <a href="/customer">
                    <i class="fas fa-hand-holding-heart" style="margin-right:10px;"></i> I am a Donor
                </a>
                <a href="/driver" class="driver-btn">
                    <i class="fas fa-truck" style="margin-right:10px;"></i> I am a Driver
                </a>
            </div>
        </div>

        <script>
            function toggleTheme() {
                const body = document.body;
                const icon = document.getElementById('theme-icon');
                
                body.classList.toggle('dark');
                
                if (body.classList.contains('dark')) {
                    icon.classList.remove('fa-moon');
                    icon.classList.add('fa-sun');
                } else {
                    icon.classList.remove('fa-sun');
                    icon.classList.add('fa-moon');
                }
            }
        </script>
    </body>
    </html>
    """

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FresQ Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root { 
                --bg: #f4f4f9; 
                --glass: rgba(255,255,255,0.95); 
                --accent: #ff6b00; 
                --text: #222; 
                --border: 1px solid #ddd;
            }
            body.dark-mode { 
                --bg: #000; 
                --glass: rgba(20,20,20,0.9); 
                --text: #fff; 
                --border: 1px solid #333; 
            }
            
            body { 
                margin: 0; 
                background: var(--bg); 
                color: var(--text); 
                font-family: 'Segoe UI', sans-serif; 
                height: 100vh; 
                display: flex; 
                align-items: center; 
                justify-content: center; 
                transition: 0.3s; 
                padding: 20px; 
                box-sizing: border-box; 
            }
            
            /* Responsive Login Box */
            .box { 
                background: var(--glass); 
                padding: 30px; 
                border-radius: 24px; 
                width: 100%; 
                max-width: 360px; /* Limits width on desktop */
                text-align: center; 
                box-shadow: 0 10px 40px rgba(0,0,0,0.1); 
                border: var(--border);
                position: relative;
            }
            
            h2 { margin-top: 0; margin-bottom: 20px; font-size: 1.8rem; }
            
            /* Inputs */
            input { 
                width: 100%; 
                padding: 15px; 
                margin: 8px 0; 
                background: rgba(0,0,0,0.05); 
                border: 1px solid #ddd; 
                border-radius: 12px; 
                box-sizing: border-box; 
                color: inherit; 
                outline: none; 
                font-size: 16px; 
            }
            
            input:focus { border-color: var(--accent); }
            
            /* Button */
            button { 
                width: 100%; 
                padding: 16px; 
                background: var(--accent); 
                color: white; 
                border: none; 
                border-radius: 12px; 
                cursor: pointer; 
                font-weight: bold; 
                margin-top: 15px; 
                font-size: 16px; 
                transition: transform 0.1s;
            }
            
            button:active { transform: scale(0.98); }
            
            /* Toggle Link */
            .toggle { 
                margin-top: 20px; 
                font-size: 0.9rem; 
                color: #888; 
                cursor: pointer; 
                text-decoration: underline; 
                padding: 10px; 
            }
            
            .hidden { display: none; }
            
            /* Theme Toggle Icon */
            .theme-toggle { 
                position: absolute; 
                top: 20px; 
                right: 20px; 
                cursor: pointer; 
                font-size: 1.4rem; 
                padding: 10px; 
                color: var(--text);
            }
        </style>
    </head>
    <body>
        <div class="theme-toggle" onclick="toggleTheme()">
            <i class="fas fa-moon" id="theme-icon"></i>
        </div>
        
        <div class="box">
            <h2 id="title">Login</h2>
            
            <div id="signup-fields" class="hidden">
                <input type="text" id="username" placeholder="Full Name">
            </div>
            
            <input type="tel" id="phone" placeholder="Phone Number" autocomplete="off">
            <input type="password" id="pass" placeholder="Password">
            
            <button onclick="handleAuth()" id="btn">Login</button>
            
            <div class="toggle" onclick="toggleMode()" id="mode">
                Need an account? Sign Up
            </div>
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
                // Update Text
                document.getElementById('title').innerText = isLogin ? "Login" : "Create Account"; 
                document.getElementById('btn').innerText = isLogin ? "Login" : "Sign Up"; 
                document.getElementById('mode').innerText = isLogin ? "Need an account? Sign Up" : "Already have an account? Login"; 
                // Show/Hide Fields
                document.getElementById('signup-fields').classList.toggle('hidden'); 
            }

            async function handleAuth() {
                const phone = document.getElementById('phone').value; 
                const password = document.getElementById('pass').value;
                const btn = document.getElementById('btn');
                
                // Get redirect target
                const target = new URLSearchParams(window.location.search).get('target') || '/customer';

                if (!phone || !password) return alert("Please fill in all fields");

                btn.innerText = "Processing...";
                btn.disabled = true;

                try {
                    if (isLogin) {
                        // --- LOGIN ---
                        const res = await fetch('/api/auth/login', { 
                            method: 'POST', 
                            headers: {'Content-Type': 'application/json'}, 
                            body: JSON.stringify({phone, password}) 
                        });
                        
                        if (res.ok) {
                            window.location.href = target; 
                        } else {
                            alert("Invalid Credentials");
                            btn.innerText = "Login";
                            btn.disabled = false;
                        }
                    } else {
                        // --- SIGN UP ---
                        const username = document.getElementById('username').value;
                        if (!username) {
                            alert("Name is required");
                            btn.innerText = "Sign Up";
                            btn.disabled = false;
                            return;
                        }

                        const res = await fetch('/api/auth/signup', { 
                            method: 'POST', 
                            headers: {'Content-Type': 'application/json'}, 
                            body: JSON.stringify({phone, username, password}) 
                        });
                        
                        if (res.ok) { 
                            alert("Account Created! Please Login."); 
                            toggleMode(); // Switch back to login view
                            btn.innerText = "Login";
                            btn.disabled = false;
                        } else { 
                            const data = await res.json();
                            alert("Error: " + (data.detail || "Phone number already exists."));
                            btn.innerText = "Sign Up";
                            btn.disabled = false;
                        }
                    }
                } catch (e) {
                    console.error(e);
                    alert("Network Error");
                    btn.innerText = isLogin ? "Login" : "Sign Up";
                    btn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """

@app.get("/customer", response_class=HTMLResponse)
def customer_app(request: Request):
    # Security check
    if not request.cookies.get("fresq_user"): 
        return RedirectResponse(url="/login?target=/customer")
    
    # Pass NGO data to frontend
    ngos_json = json.dumps(NGO_DATABASE)
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>FresQ Donor Portal</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
        <style>
            :root {{ 
                --bg: #f4f4f9; 
                --glass: rgba(255,255,255,0.95); 
                --accent: #ff6b00; 
                --text: #222; 
                --border: 1px solid #eee;
            }}
            body.dark-mode {{ 
                --bg: #000; 
                --glass: rgba(20,20,20,0.95); 
                --text: #fff; 
                --border: 1px solid #333;
            }}
            
            body {{ 
                margin: 0; 
                background: var(--bg); 
                color: var(--text); 
                font-family: 'Segoe UI', sans-serif; 
                height: 100vh; 
                overflow: hidden; 
                transition: 0.3s;
            }}
            
            #map {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 0; }}
            
            /* --- CONTROLS --- */
            .icon-btn {{ 
                background: var(--glass); width: 50px; height: 50px; border-radius: 50%; 
                display: flex; justify-content: center; align-items: center; color: var(--text); 
                box-shadow: 0 4px 15px rgba(0,0,0,0.1); cursor: pointer; text-decoration: none; 
                font-size: 1.2rem; transition: 0.2s; 
            }}
            .icon-btn:hover {{ transform: scale(1.05); }}
            
            .home-btn {{ position: absolute; top: 25px; left: 25px; z-index: 1000; }}
            .top-right {{ position: absolute; top: 25px; right: 25px; z-index: 1000; display: flex; gap: 15px; }}
            
            /* --- SLIDING PANEL --- */
            .panel {{ 
                position: absolute; 
                bottom: 0; 
                left: 50%; 
                transform: translateX(-50%); 
                width: 100%; 
                max-width: 450px; 
                background: var(--glass); 
                padding: 20px 25px; 
                border-radius: 32px 32px 0 0; 
                z-index: 1000; 
                border-top: var(--border); 
                backdrop-filter: blur(15px); 
                box-shadow: 0 -5px 40px rgba(0,0,0,0.15); 
                max-height: 85vh; 
                overflow-y: auto; 
                transition: transform 0.4s cubic-bezier(0.25, 1, 0.5, 1);
            }}

            /* Minimized State class (toggled by JS) */
            .panel.minimized {{
                transform: translate(-50%, calc(100% - 70px)); /* Show only top 70px */
                overflow: hidden;
            }}
            
            /* Desktop Override: Float it nicely */
            @media (min-width: 600px) {{
                .panel {{ 
                    bottom: 30px; 
                    width: 90%; 
                    border-radius: 32px;
                    border: var(--border);
                }}
                .panel.minimized {{
                    transform: translate(-50%, calc(100% - 80px));
                }}
            }}
            
            h2 {{ margin-top: 0; margin-bottom: 20px; font-size: 1.6rem; font-weight: 800; letter-spacing: -0.5px; }}
            
            label {{ font-size: 0.85rem; font-weight: bold; margin-bottom: 8px; display: block; opacity: 0.7; text-transform: uppercase; letter-spacing: 0.5px; }}
            
            input:not([type='file']), textarea, select {{ 
                width: 100%; padding: 16px; margin-bottom: 15px; border: var(--border); 
                border-radius: 16px; box-sizing: border-box; font-size: 1rem; 
                background: rgba(0,0,0,0.04); color: inherit; outline: none; 
                font-family: inherit; transition: 0.2s; 
            }}
            input:focus, textarea:focus {{ background: rgba(0,0,0,0.08); border-color: var(--accent); }}
            
            .row {{ display: flex; gap: 10px; }}
            .col {{ flex: 1; }}
            
            .location-hint {{ 
                font-size: 0.95rem; color: #888; margin-bottom: 20px; text-align: center; 
                padding: 15px; border: 2px dashed #ccc; border-radius: 16px; 
                background: rgba(0,0,0,0.02); cursor: pointer; 
            }}
            
            /* Drag Handle */
            .drag-handle {{
                width: 60px; height: 5px; background: rgba(0,0,0,0.2); 
                border-radius: 10px; margin: 0 auto 15px auto; cursor: pointer;
            }}
        </style>
    </head>
    <body>
        <a href="/" class="icon-btn home-btn"><i class="fas fa-home"></i></a>
        <div class="top-right">
            <div class="icon-btn" onclick="toggleTheme()"><i class="fas fa-moon" id="theme-icon"></i></div>
            <div class="icon-btn" onclick="logout()" title="Logout" style="color:#e74c3c;"><i class="fas fa-sign-out-alt"></i></div>
        </div>
        
        <div id="map"></div>
        
        <div class="panel" id="mainPanel">
            <div class="drag-handle" onclick="togglePanel()"></div>
            
            <div class="flex justify-between items-center mb-4">
                <h2 onclick="togglePanel()" class="cursor-pointer">Donate Food</h2>
                <button onclick="document.getElementById('train-section').classList.toggle('hidden')" class="text-xs text-slate-400 underline">Calibrate AI</button>
            </div>

            <div id="train-section" class="hidden mb-6 p-4 bg-slate-100 rounded-xl border border-slate-200">
                <h3 class="font-bold text-sm mb-2 text-slate-700">Teach AI Bad Patterns</h3>
                <input type="file" accept="image/*" onchange="trainModel(event)" class="text-sm w-full mb-2">
                <div id="training-status" class="text-xs text-slate-500">Upload an image of spoiled food to train.</div>
            </div>

            <div class="mb-6">
                <label>Food Quality Scan <span class="text-red-500">*</span></label>
                
                <div class="relative group cursor-pointer">
                    <input type="file" id="food-upload" accept="image/*" onchange="handleImageUpload(event)" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10">
                    
                    <div id="upload-placeholder" class="border-2 border-dashed border-slate-300 rounded-xl p-8 text-center bg-slate-50 group-hover:bg-slate-100 transition-colors">
                        <i class="fa-solid fa-camera text-3xl text-slate-400 mb-2"></i>
                        <p class="text-sm text-slate-500 font-medium">Tap to Scan Food</p>
                    </div>

                    <img id="preview-img" class="hidden w-full h-48 object-cover rounded-xl shadow-md border border-slate-200" />
                </div>

                <div id="analysis-result" class="hidden mt-4 p-4 rounded-xl border">
                    <div class="flex justify-between items-end mb-1">
                        <span class="text-xs font-bold uppercase tracking-wider opacity-60">Quality Score</span>
                        <span id="score-val" class="text-xl font-black">0/100</span>
                    </div>
                    <div class="w-full bg-slate-200 rounded-full h-2.5 mb-3 overflow-hidden">
                        <div id="score-bar" class="h-full transition-all duration-1000 ease-out" style="width: 0%"></div>
                    </div>
                    <div id="score-msg" class="text-sm font-medium"></div>
                    <div id="classification-msg" class="text-xs mt-1 opacity-70"></div>
                    
                    <button id="btn-override" onclick="manualOverride()" class="hidden mt-3 w-full py-2 text-xs font-bold text-slate-500 bg-white border border-slate-300 rounded-lg hover:bg-slate-50">
                        I confirm this is safe (Override)
                    </button>
                </div>
            </div>

            <label>Pickup Address (Optional if Pinned)</label>
            <input type="text" id="address" placeholder="Type address OR just pin on map">

            <label>Food Details</label>
            <textarea id="desc" rows="1" placeholder="e.g. 50 Meals, Rice & Curry"></textarea>
            
            <label>Manufacture Date <span style="color:#e74c3c">*</span></label>
            <input type="datetime-local" id="mfg_date">
            
            <label>Shelf Life <span style="color:#e74c3c">*</span></label>
            <div class="row">
                <input type="number" id="life_val" placeholder="Value (e.g. 4)" class="col">
                <select id="life_unit" class="col">
                    <option value="1">Hours</option>
                    <option value="24">Days</option>
                    <option value="168">Weeks</option>
                </select>
            </div>
            
            <div class="location-hint" id="coords" onclick="focusMap()">
                <i class="fas fa-map-marker-alt" style="color:#e74c3c; margin-right:5px;"></i> 
                Tap map to set precise pickup pin
            </div>
            
            <button id="btn-submit" onclick="submit()" disabled class="w-full bg-slate-300 text-slate-500 font-bold py-3 rounded-xl transition-all cursor-not-allowed shadow-none border-none">
                FIND DRIVER
            </button>
        </div>

        <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
        <script>
            // --- UI TOGGLES ---
            function togglePanel() {{
                const p = document.getElementById('mainPanel');
                p.classList.toggle('minimized');
            }}
            
            // --- AI & STATE LOGIC ---
            const state = {{
                trainedBadColors: [],
                qualityStatus: 'pending' // pending, approved, rejected
            }};

            // 1. AI Training Logic
            function trainModel(event) {{
                const file = event.target.files[0];
                if (!file) return;

                const reader = new FileReader();
                reader.onload = function(e) {{
                    const img = new Image();
                    img.onload = function() {{
                        const canvas = document.createElement('canvas');
                        const ctx = canvas.getContext('2d');
                        canvas.width = 50; canvas.height = 50;
                        ctx.drawImage(img, 0, 0, 50, 50);
                        const data = ctx.getImageData(0, 0, 50, 50).data;
                        
                        let r=0, g=0, b=0, count=0;
                        for(let i=0; i<data.length; i+=4) {{
                            r += data[i]; g += data[i+1]; b += data[i+2];
                            count++;
                        }}
                        
                        state.trainedBadColors.push({{
                            r: Math.floor(r/count),
                            g: Math.floor(g/count),
                            b: Math.floor(b/count)
                        }});

                        document.getElementById('training-status').innerHTML = `<span class="text-emerald-600 font-bold"><i class="fa-solid fa-check"></i> Learned ${{state.trainedBadColors.length}} bad patterns.</span>`;
                        alert("AI Updated: This image pattern is now marked as 'Rotten'.");
                    }};
                    img.src = e.target.result;
                }};
                reader.readAsDataURL(file);
            }}

            // 2. Donor: AI Freshness Logic (Pixel Analysis)
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
                canvas.width = 100; // Downsample for speed
                canvas.height = 100;
                ctx.drawImage(img, 0, 0, 100, 100);
                
                const imageData = ctx.getImageData(0, 0, 100, 100);
                const data = imageData.data;
                
                let vibrantScore = 0;
                let dullScore = 0;
                let matchedTrainedBad = 0;
                
                let syntheticScore = 0; 
                let foodColorScore = 0;
                let totalAnalyzed = 0;

                for (let i = 0; i < data.length; i += 4) {{
                    const r = data[i], g = data[i+1], b = data[i+2];
                    totalAnalyzed++;

                    const avg = (r + g + b) / 3;
                    const max = Math.max(r, g, b);
                    const min = Math.min(r, g, b);
                    const sat = max === 0 ? 0 : (max - min) / max;

                    // Edibility Filter
                    if (b > r + 15 && b > g + 15 && avg > 40) syntheticScore++;
                    if (r > g + 30 && b > g + 30 && avg > 100) syntheticScore++;
                    if (sat > 0.85 && avg > 150) syntheticScore++;
                    if (sat < 0.1 && avg > 80 && b > r) syntheticScore += 0.5;

                    // Food Color Detection
                    if ((r > b + 10) || (g > b + 10)) foodColorScore++;

                    // Trained Bad Patterns
                    state.trainedBadColors.forEach(bad => {{
                        const dist = Math.sqrt(Math.pow(r-bad.r,2) + Math.pow(g-bad.g,2) + Math.pow(b-bad.b,2));
                        if (dist < 30) matchedTrainedBad++; 
                    }});

                    // Freshness Heuristics
                    const isBrownish = (r > b + 20) && (r > g) && (sat < 0.6) && (avg < 150);
                    const isDarkSpot = (avg < 40);
                    
                    if (isBrownish || isDarkSpot) {{
                        dullScore++;
                    }} else if (sat > 0.3 && avg > 60) {{
                        vibrantScore++; 
                    }} else {{
                        dullScore += 0.2; 
                    }}
                }}

                // Decision Logic
                const syntheticRatio = syntheticScore / totalAnalyzed;
                if (syntheticRatio > 0.15) {{ 
                    displayResult(0, "Rejected: Non-edible object detected (Synthetic Colors/Plastic).");
                    document.getElementById('classification-msg').innerText = "Classification: Inedible Object / Packaging";
                    return;
                }}

                const foodRatio = foodColorScore / totalAnalyzed;
                if (foodRatio < 0.3) {{
                    displayResult(0, "Rejected: No identifiable food detected.");
                    document.getElementById('classification-msg').innerText = "Classification: Background / Unknown Object";
                    return;
                }}

                if (matchedTrainedBad > (totalAnalyzed * 0.1)) {{
                    displayResult(15, "Matched user-defined 'Bad' pattern.");
                    document.getElementById('classification-msg').innerText = "Classification: Edible but Spoiled";
                    return;
                }}

                const totalConsidered = vibrantScore + dullScore;
                const freshRatio = totalConsidered === 0 ? 0 : vibrantScore / totalConsidered;
                
                let score = Math.floor(freshRatio * 130); 
                if (dullScore > vibrantScore) score = Math.min(score, 45); 
                
                const finalScore = Math.min(99, score);
                displayResult(finalScore);
                
                document.getElementById('classification-msg').innerText = 
                    finalScore >= 60 ? "Classification: Edible & Fresh" : "Classification: Edible but Low Quality";
            }}

            function displayResult(score, customMsg) {{
                const container = document.getElementById('analysis-result');
                const val = document.getElementById('score-val');
                const bar = document.getElementById('score-bar');
                const msg = document.getElementById('score-msg');
                const btn = document.getElementById('btn-submit');
                const override = document.getElementById('btn-override');

                container.classList.remove('hidden');
                val.innerText = score + "/100";
                bar.style.width = score + "%";

                if (score >= 60) {{
                    container.className = "mt-4 p-4 rounded-xl border border-emerald-200 bg-emerald-50";
                    val.className = "text-xl font-black text-emerald-600";
                    bar.className = "h-full bg-emerald-500";
                    msg.innerHTML = `<i class='fa-solid fa-check-circle text-emerald-600'></i> ${{customMsg || "Approved: Freshness verified."}}`;
                    msg.className = "text-sm font-medium text-emerald-800";
                    
                    btn.disabled = false;
                    btn.className = "w-full bg-emerald-600 text-white font-bold py-3 rounded-xl hover:bg-emerald-700 hover:scale-[1.02] transform transition-all shadow-lg shadow-emerald-200 cursor-pointer border-none";
                    override.classList.add('hidden');
                    state.qualityStatus = 'approved';
                }} else {{
                    container.className = "mt-4 p-4 rounded-xl border border-red-200 bg-red-50";
                    val.className = "text-xl font-black text-red-600";
                    bar.className = "h-full bg-red-500";
                    msg.innerHTML = `<i class='fa-solid fa-ban text-red-600'></i> ${{customMsg || "Rejected: Potential spoilage/rot detected."}}`;
                    msg.className = "text-sm font-medium text-red-800";
                    
                    btn.disabled = true;
                    btn.className = "w-full bg-slate-300 text-slate-500 font-bold py-3 rounded-xl transition-all cursor-not-allowed shadow-none border-none";
                    override.classList.remove('hidden');
                    state.qualityStatus = 'rejected';
                }}
            }}

            function manualOverride() {{
                if (state.qualityStatus === 'rejected') {{
                    if(confirm("Confirm that this item is fresh and safe for consumption?")) {{
                        displayResult(75, "Manually Approved (User Override)"); 
                        document.getElementById('classification-msg').innerText = "Classification: Manual Override";
                    }}
                }}
            }}

            // --- MAP & SUBMIT LOGIC ---
            const map = L.map('map', {{zoomControl:false}}).setView([25.1825, 75.8236], 13);
            const lightTiles = 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            const darkTiles = 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png';
            let tileLayer = L.tileLayer(lightTiles).addTo(map);
            
            const ngos = {ngos_json};
            ngos.forEach(n => {{
                L.circleMarker([n.lat, n.lon], {{
                    color: '#555', radius: 6, fillColor: '#fff', fillOpacity: 1
                }}).addTo(map).bindPopup("<b>NGO:</b> " + n.name);
            }});
            
            let pickupLoc = null; 
            let marker = null;
            
            const now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            document.getElementById('mfg_date').value = now.toISOString().slice(0,16);

            function focusMap() {{ 
                // Auto-minimize panel when map interaction is requested
                document.getElementById('mainPanel').classList.add('minimized');
                alert("Tap anywhere on the map to set the pickup pin.");
            }}

            map.on('click', e => {{
                pickupLoc = e.latlng;
                if(marker) map.removeLayer(marker);
                
                const icon = L.divIcon({{
                    className: 'p',
                    html: '<div style="width:30px;height:30px;background:#2ecc71;border:3px solid white;border-radius:50% 50% 50% 0;transform:rotate(-45deg);box-shadow:0 3px 10px rgba(0,0,0,0.3);"></div>',
                    iconSize: [30, 42],
                    iconAnchor: [15, 42]
                }});
                
                marker = L.marker(e.latlng, {{icon: icon}}).addTo(map);
                const el = document.getElementById('coords');
                el.innerHTML = `<span style="color:#2ecc71; font-weight:bold;"><i class="fas fa-check"></i> Pin Location Set</span>`;
                el.style.borderColor = "#2ecc71";
                el.style.background = "rgba(46, 204, 113, 0.1)";
                
                // Re-open panel after pin set
                document.getElementById('mainPanel').classList.remove('minimized');
            }});

            async function submit() {{
                // 1. Check AI Status
                if (state.qualityStatus !== 'approved') {{
                    return alert("Please scan your food quality first. Ensure score is above 60.");
                }}

                // 2. Gather Inputs
                let address = document.getElementById('address').value;
                const details = document.getElementById('desc').value;
                const mfgDateVal = document.getElementById('mfg_date').value;
                const lifeVal = document.getElementById('life_val').value;
                
                if(!pickupLoc) return alert("Please tap the map to set the exact pin location.");
                if(!address) address = `Pinned Location (${{pickupLoc.lat.toFixed(4)}}, ${{pickupLoc.lng.toFixed(4)}})`;
                if(!mfgDateVal || !lifeVal) return alert("Please enter Manufacture Date and Shelf Life.");

                const mfgDate = new Date(mfgDateVal);
                const unitMult = parseInt(document.getElementById('life_unit').value);
                const totalHours = parseFloat(lifeVal) * (unitMult === 1 ? 1 : (unitMult === 24 ? 24 : 168));
                
                const expiryDate = new Date(mfgDate.getTime() + (totalHours * 60 * 60 * 1000));
                const now = new Date();
                let hoursRemaining = (expiryDate - now) / 36e5;
                if(hoursRemaining < 0) hoursRemaining = 0; 
                
                const btn = document.getElementById('btn-submit');
                btn.innerText = "Processing...";
                btn.disabled = true;
                
                const fullDetails = `[${{address}}] ${{details}}`;

                try {{
                    const res = await fetch('/api/create_order', {{
                        method: 'POST', 
                        headers: {{'Content-Type':'application/json'}},
                        body: JSON.stringify({{
                            pickup_lat: pickupLoc.lat, 
                            pickup_lon: pickupLoc.lng, 
                            quantity: 10, 
                            details: fullDetails, 
                            expiry_hours: hoursRemaining
                        }})
                    }});
                    
                    const data = await res.json();
                    
                    if(data.status === 'success') {{
                        alert("✅ Donation Registered! Finding a driver...");
                        location.reload();
                    }} else {{
                        const errorMsg = typeof data.detail === 'object' ? JSON.stringify(data.detail) : data.detail;
                        alert("Error: " + errorMsg);
                        btn.innerText = "FIND DRIVER";
                        btn.disabled = false;
                    }}
                }} catch(e) {{
                    alert("Network Error");
                    btn.innerText = "FIND DRIVER";
                    btn.disabled = false;
                }}
            }}
            
            function toggleTheme() {{
                document.body.classList.toggle('dark-mode');
                const isDark = document.body.classList.contains('dark-mode');
                document.getElementById('theme-icon').className = isDark ? 'fas fa-sun' : 'fas fa-moon';
                const url = isDark ? darkTiles : lightTiles;
                tileLayer.setUrl(url);
            }}

            async function logout() {{
                await fetch('/api/auth/logout', {{method:'POST'}});
                window.location.href = '/login';
            }}
        </script>
    </body>
    </html>
    """

@app.get("/driver", response_class=HTMLResponse)
def driver_app(request: Request):
    user_phone = request.cookies.get("fresq_user")
    
    # 1. Check if cookie exists
    if not user_phone: 
        return RedirectResponse(url="/login?target=/driver")
    
    # 2. Check if User actually exists in DB
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.cursor().execute("SELECT is_active FROM users WHERE phone = ?", (user_phone,)).fetchone()
    
    if not row:
        response = RedirectResponse(url="/login?target=/driver")
        response.delete_cookie("fresq_user")
        return response
    
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
            :root {{ 
                --bg: #f4f4f9; 
                --glass: rgba(255,255,255,0.95); 
                --accent: #ff6b00; 
                --text: #222; 
                --border: 1px solid #eee;
            }}
            body.dark-mode {{ 
                --bg: #000; 
                --glass: rgba(15,15,15,0.95); 
                --text: #fff; 
                --border: 1px solid #333;
            }}
            
            body {{ 
                margin: 0; 
                font-family: 'Segoe UI', sans-serif; 
                height: 100vh; 
                display: flex; 
                flex-direction: row; 
                overflow: hidden; 
                background: var(--bg); 
                color: var(--text); 
            }}
            
            /* Sidebar Layout (Rounder) */
            .sidebar {{ 
                width: 380px; 
                height: 100%; 
                background: var(--glass); 
                border-right: var(--border); 
                display: flex; 
                flex-direction: column; 
                z-index: 1001; 
                transition: 0.3s;
                box-shadow: 10px 0 30px rgba(0,0,0,0.05);
            }}
            
            #map {{ 
                flex: 1; 
                height: 100%; 
                position: relative; 
                z-index: 1; 
            }}

            /* Mobile Bottom Sheet Mode */
            @media (max-width: 768px) {{
                body {{ flex-direction: column-reverse; }}
                .sidebar {{ 
                    width: 100%; 
                    height: 50vh; 
                    border-right: none; 
                    border-radius: 32px 32px 0 0; 
                    box-shadow: 0 -10px 40px rgba(0,0,0,0.15); 
                }}
                #map {{ height: 50vh; }}
            }}
            
            .header {{ padding: 25px; }}
            .brand {{ font-size: 1.5rem; font-weight: 800; display: flex; justify-content: space-between; align-items: center; letter-spacing: -0.5px; }}
            
            .nav-icons {{ display: flex; align-items: center; gap: 15px; }}
            .nav-icons i {{ cursor: pointer; font-size: 1.2rem; color: var(--text); opacity: 0.7; transition: 0.2s; }}
            .nav-icons i:hover {{ opacity: 1; color: var(--accent); }}
            
            .duty-switch {{ 
                display: flex; align-items: center; justify-content: space-between; 
                background: rgba(0,0,0,0.04); padding: 12px 20px; 
                border-radius: 20px; margin-top: 20px; 
            }}
            
            .switch {{ position: relative; display: inline-block; width: 50px; height: 28px; }}
            .switch input {{ opacity: 0; width: 0; height: 0; }}
            .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }}
            .slider:before {{ position: absolute; content: ""; height: 20px; width: 20px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }}
            input:checked + .slider {{ background-color: #2ecc71; }}
            input:checked + .slider:before {{ transform: translateX(22px); }}
            
            .content {{ flex: 1; overflow-y: auto; padding: 20px; }}
            
            /* Task Card */
            .task-card {{ 
                background: var(--glass); 
                border: var(--border); 
                padding: 20px; 
                border-radius: 20px; 
                margin-bottom: 15px; 
                border-left: 6px solid #555; 
                box-shadow: 0 4px 15px rgba(0,0,0,0.03);
            }}

            .info-row {{ display:flex; align-items:flex-start; margin-bottom:8px; gap:10px; font-size:0.95rem; line-height:1.4; }}
            .info-row i {{ margin-top:3px; opacity:0.6; width:16px; text-align:center; }}

            /* Action Buttons */
            .card-actions {{ display: flex; gap: 10px; margin-top: 15px; }}
            .action-btn {{ 
                flex: 1; padding: 12px; border: none; border-radius: 12px; 
                font-weight: bold; cursor: pointer; display: flex; 
                align-items: center; justify-content: center; gap: 8px; 
                font-size: 0.95rem; transition: 0.2s; 
            }}
            .btn-nav {{ background: rgba(59, 130, 246, 0.1); color: #3b82f6; }}
            .btn-nav:hover {{ background: #3b82f6; color: white; }}
            
            .btn-done {{ background: rgba(46, 204, 113, 0.1); color: #2ecc71; }}
            .btn-done:hover {{ background: #2ecc71; color: white; }}
            
            /* Sync Button */
            .btn-opt {{ 
                margin: 20px; padding: 18px; background: var(--accent); 
                color: white; border: none; font-weight: bold; cursor: pointer; 
                font-size: 1.1rem; border-radius: 30px; 
                box-shadow: 0 8px 25px rgba(255, 107, 0, 0.3);
                transition: 0.2s;
            }}
            .btn-opt:active {{ transform: scale(0.97); }}
            
            /* Map Elements */
            .driver-pin {{ 
                width: 22px; height: 22px; background: #3b82f6; 
                border: 3px solid white; border-radius: 50%; 
                box-shadow: 0 0 20px 8px rgba(59, 130, 246, 0.5); 
                animation: pulse-blur 2s infinite; 
            }}
            @keyframes pulse-blur {{ 
                0% {{ box-shadow: 0 0 5px 2px rgba(59, 130, 246, 0.4); }} 
                50% {{ box-shadow: 0 0 25px 10px rgba(59, 130, 246, 0.6); }} 
                100% {{ box-shadow: 0 0 5px 2px rgba(59, 130, 246, 0.4); }} 
            }}
            
            .pin-wrap {{ width:34px; height:34px; border-radius:50% 50% 50% 0; transform:rotate(-45deg); display:flex; justify-content:center; align-items:center; border:2px solid white; box-shadow:0 5px 15px rgba(0,0,0,0.3); }}
            .pin-num {{ transform:rotate(45deg); font-size:14px; font-weight:bold; color:white; }}
            
            .recenter-btn {{ 
                position: absolute; bottom: 30px; right: 20px; z-index: 1000; 
                width: 55px; height: 55px; border-radius: 50%; 
                background: var(--text); color: var(--bg); 
                display: flex; align-items: center; justify-content: center; 
                font-size: 1.5rem; cursor: pointer; 
                box-shadow: 0 8px 25px rgba(0,0,0,0.25); 
                transition: transform 0.2s;
            }}
            .recenter-btn:active {{ transform: scale(0.9); }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="header">
                <div class="brand">
                    <span>Fres<span style="color:var(--accent)">Q</span></span>
                    <div class="nav-icons">
                         <i class="fas fa-moon" onclick="toggleTheme()" id="theme-icon"></i>
                         <i class="fas fa-home" onclick="window.location.href='/'"></i>
                         <i class="fas fa-sign-out-alt" onclick="logout()" title="Logout" style="color:#e74c3c;"></i>
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
                <div style="text-align:center; padding:50px 20px; opacity:0.6; font-size:1.1rem;">
                    Go On Duty to track location.
                </div>
            </div>
            
            <button class="btn-opt" onclick="dispatch(true)" id="optBtn" disabled style="opacity:0.5">SYNC FLEET</button>
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
            
            // Tile Layers
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
                    requestAndToggleDuty(true); 
                }}
            }};

            // --- GPS & PERMISSIONS ---
            function requestAndToggleDuty(isRestoring = false) {{
                const toggle = document.getElementById('dutyToggle');
                
                if (toggle.checked) {{
                    if (!navigator.geolocation) {{ 
                        alert("GPS not supported."); 
                        toggle.checked = false; 
                        return; 
                    }}
                    
                    navigator.geolocation.getCurrentPosition(
                        (pos) => {{ 
                            isOnDuty = true; 
                            startTracking(); 
                            handleToggleAPI(true); 
                        }},
                        (err) => {{ 
                            if (!isRestoring) alert("Location access required."); 
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
                
                const icon = L.divIcon({{
                    className: 'c', 
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
                await fetch('/api/driver/toggle', {{
                    method: 'POST', 
                    headers: {{'Content-Type':'application/json'}}, 
                    body: JSON.stringify({{
                        is_active: status, 
                        lat: driverLoc ? driverLoc.lat : 0, 
                        lon: driverLoc ? driverLoc.lon : 0
                    }})
                }}); 
                if (status) dispatch(true); 
            }}
            
            async function sendHeartbeat() {{ 
                if(isOnDuty && driverLoc) {{
                    await fetch('/api/driver/heartbeat', {{
                        method: 'POST', 
                        headers: {{'Content-Type':'application/json'}}, 
                        body: JSON.stringify({{lat: driverLoc.lat, lon: driverLoc.lon}})
                    }}); 
                }}
            }}

            async function dispatch(showUI = false) {{
                if(!isOnDuty) return;
                const btn = document.getElementById('optBtn'); 
                
                if(showUI) {{
                    btn.innerText = "OPTIMIZING...";
                    btn.disabled = true;
                }}
                
                try {{
                    const res = await fetch('/api/dispatch', {{method:'POST'}}); 
                    const data = await res.json();
                    
                    if(data.error) {{ 
                        if(data.error.includes("No drivers")) sendHeartbeat(); 
                        if(showUI) btn.innerText = "SYNC FLEET"; 
                        if(showUI) btn.disabled = false;
                        return; 
                    }}
                    
                    const ordersRes = await fetch('/api/orders'); 
                    const allOrders = await ordersRes.json();
                    
                    drawRoute(data.route, allOrders); 
                    renderList(data.route, allOrders);
                    
                }} catch(e) {{ console.error(e); }}
                
                if(showUI) {{
                    btn.innerText = "SYNC FLEET";
                    btn.disabled = false;
                }}
            }}

            // --- RENDERERS ---
            function renderList(route, orders) {{
                const list = document.getElementById('list');
                
                if(!route || route.length === 0) {{ 
                    list.innerHTML = "<div style='text-align:center; padding:30px; opacity:0.6;'>No orders assigned.<br>Wait for dispatch.</div>"; 
                    return; 
                }}
                
                let html = ""; 
                let stepNum = 1;
                
                route.forEach(step => {{
                    if(step.type === 'start') return;
                    const order = orders.find(o => o.id == step.location_id.split('_')[0]); 
                    if(!order) return;
                    
                    const isPickup = step.type === 'pickup';
                    const color = isPickup ? '#2ecc71' : '#e74c3c';
                    
                    // --- PARSING ADDRESS LOGIC ---
                    let address = "Unknown Location";
                    let desc = isPickup ? order.details : order.ngo_name;
                    
                    if(isPickup && order.details.startsWith('[')) {{
                        const closing = order.details.indexOf(']');
                        if(closing > -1) {{
                            address = order.details.substring(1, closing);
                            desc = order.details.substring(closing + 1).trim();
                        }}
                    }} else if (!isPickup) {{
                        address = order.ngo_name + ", Kota"; // Fallback for NGO
                        desc = "Drop off donation";
                    }}
                    
                    // Navigation Coordinates
                    const lat = isPickup ? order.pickup_location.lat : order.delivery_location.lat;
                    const lon = isPickup ? order.pickup_location.lon : order.delivery_location.lon;
                    
                    html += `
                    <div class="task-card" style="border-left-color:${{color}}">
                        <div style="display:flex;justify-content:space-between;font-size:0.8rem;font-weight:bold;margin-bottom:10px;">
                            <span>STEP ${{stepNum++}} • ${{step.type.toUpperCase()}}</span>
                            <span style="opacity:0.5">#${{order.id.substring(0,4)}}</span>
                        </div>
                        
                        <div class="info-row">
                            <i class="fas fa-map-marker-alt" style="color:${{color}}"></i>
                            <span style="font-weight:700; font-size:1rem;">${{address}}</span>
                        </div>
                        
                        <div class="info-row">
                            <i class="fas fa-box"></i>
                            <span>${{desc}}</span>
                        </div>
                        
                        <div class="info-row" style="color:${{order.priority_level === 'CRITICAL' ? '#e74c3c' : '#2ecc71'}}">
                            <i class="fas fa-clock"></i>
                            <span style="font-weight:bold;">${{order.priority_level}} PRIORITY</span>
                        </div>
                        
                        <div class="card-actions">
                            <button class="action-btn btn-nav" onclick="navigate(${{lat}}, ${{lon}})">
                                <i class="fas fa-location-arrow"></i> Navigate
                            </button>
                            <button class="action-btn btn-done" onclick="completeTask('${{order.id}}', '${{step.type}}')">
                                <i class="fas fa-check-circle"></i> Complete
                            </button>
                        </div>
                    </div>`;
                }});
                
                list.innerHTML = html;
            }}
            
            // --- ACTION HANDLERS ---
            function navigate(lat, lon) {{
                // Opens Universal Google Maps Directions
                window.open(`https://www.google.com/maps/dir/?api=1&destination=${{lat}},${{lon}}`, '_blank');
            }}

            async function completeTask(orderId, type) {{
                if(!confirm("Mark this task as completed?")) return;
                
                // Pickup -> 'in_transit', Delivery -> 'completed'
                const status = type === 'pickup' ? 'in_transit' : 'completed';
                
                await fetch('/api/update_status', {{
                    method: 'POST',
                    headers: {{'Content-Type':'application/json'}},
                    body: JSON.stringify({{ order_id: orderId, status: status }})
                }});
                
                dispatch(true); // Force UI refresh
            }}

            function drawRoute(route, orders) {{
                routeLayer.clearLayers(); 
                if(!route || route.length === 0) return;
                
                const points = []; 
                if (driverLoc) points.push(driverLoc);
                let stepNum = 1;
                
                route.forEach(step => {{
                    if(step.type === 'start') return;
                    const order = orders.find(o => o.id == step.location_id.split('_')[0]); 
                    if(!order) return;
                    
                    const loc = step.type === 'pickup' ? order.pickup_location : order.delivery_location; 
                    points.push(loc);
                    
                    const color = step.type === 'pickup' ? '#2ecc71' : '#e74c3c';
                    
                    const icon = L.divIcon({{
                        className:'p', 
                        html:`<div class="pin-wrap" style="background:${{color}}"><span class="pin-num">${{stepNum++}}</span></div>`, 
                        iconSize:[34,44], 
                        iconAnchor:[17,44]
                    }});
                    
                    L.marker([loc.lat, loc.lon], {{icon: icon}}).addTo(routeLayer);
                }});
                
                if(points.length > 1) {{
                    const latlngs = points.map(p => [p.lat, p.lon]);
                    L.polyline(latlngs, {{color:'#ff6b00', weight:6, opacity:0.8}}).addTo(routeLayer);
                }}
            }}

            // --- UTILS ---
            function updateUI(active) {{
                const label = document.getElementById('status-label');
                label.innerText = active ? "ON DUTY" : "OFF DUTY"; 
                label.style.color = active ? "#2ecc71" : "#7f8c8d";
                document.getElementById('optBtn').disabled = !active; 
                document.getElementById('optBtn').style.opacity = active ? "1" : "0.5";
                
                if(!active) {{ 
                    document.getElementById('list').innerHTML = "<div style='text-align:center; padding:50px 20px; opacity:0.6; font-size:1.1rem;'>Go On Duty to track location.</div>"; 
                    routeLayer.clearLayers(); 
                }}
            }}
            
            function toggleTheme() {{ 
                document.body.classList.toggle('dark-mode'); 
                const isDark = document.body.classList.contains('dark-mode');
                document.getElementById('theme-icon').className = isDark ? 'fas fa-sun' : 'fas fa-moon';
                
                // Toggle Map Tiles
                const url = isDark 
                    ? 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png' 
                    : 'https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png';
                tileLayer.setUrl(url); 
            }}
            
            async function logout() {{ 
                await fetch('/api/auth/logout', {{method:'POST'}}); 
                window.location.href = '/login'; 
            }}
            
            // Background Loops - FASTER (Every 5 seconds)
            setInterval(() => {{ if(isOnDuty) sendHeartbeat(); }}, 5000);
            setInterval(() => {{ if(isOnDuty) dispatch(false); }}, 5000); // false = silent update
        </script>
    </body> 
    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)