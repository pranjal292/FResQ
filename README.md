# FresQ Logistics Platform

**FresQ** is a food rescue logistics engine. It connects food donors with drivers to efficiently route surplus food to NGOs. The system utilizes a Python FastAPI backend for route optimization and a React frontend for the user interface.

## 📂 Project Structure

The project is divided into two main components based on your file structure:

### 1. Backend (Python/FastAPI)

Located in the root directory:

* `main.py`: The entry point for the FastAPI server and API endpoints.
* `solver.py`: Contains the Vehicle Routing Problem (VRP) algorithms.
* `models.py`: Pydantic data models for input validation.
* `fresq.db`: SQLite database storing users, orders, and driver status.

### 2. Frontend (React/Vite)

Located in the `src` directory:

* `src/main.jsx`: React entry point.
* `src/App.jsx`: Main application component.
* `src/MapComponent.jsx`: Leaflet map integration.
* `vite.config.js`: Configuration for the Vite build tool.

---

## 🛠️ Prerequisites

* **Python 3.8+**
* **Node.js & npm** (For the React Frontend)

---

## 🚀 Installation & Setup

### 1. Backend Setup (Python)

1. Navigate to the backend directory (root).
2. Install the required Python dependencies:
```bash
pip install fastapi uvicorn pydantic

```


3. Start the API server:
```bash
uvicorn main:app --host 0.0.0.0 --port 8005 --reload

```


*The server will start at `http://localhost:8005`.*

### 2. Frontend Setup (React)

1. Navigate to the frontend directory (where `package.json` is located).
2. Install the Node dependencies:
```bash
npm install

```


3. Start the development server:
```bash
npm run dev

```


*The frontend will typically start at `http://localhost:5173`.*

---

## 📱 Features

### 🍎 Donor Portal (Customer)

* **AI Spoilage Detection:** Upload food images to analyze freshness before donation.
* **Interactive Map:** Pin-point precise pickup locations.

### 🚛 Driver Portal (Fleet)

* **Duty Toggle:** Switch between "On Duty" and "Off Duty" status.
* **Route Optimization:** Visualizes the most efficient path for pickups and deliveries.
* **Live Tracking:** Updates location in real-time.

---

## ⚠️ Troubleshooting

* **Database Errors:** If you encounter schema errors, delete the `fresq.db` file. The system will auto-generate a fresh one on the next restart.
---

## 🛡️ License

This project is open-source and available under the MIT License.
