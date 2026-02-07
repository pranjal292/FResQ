import React, { useState } from 'react';
import axios from 'axios';
import MapComponent from './MapComponent';

function App() {
  const [vehicle, setVehicle] = useState(null);
  const [orders, setOrders] = useState([]);
  const [route, setRoute] = useState(null);
  const [distance, setDistance] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // 1. Fetch Live Orders from Server
  const handleFetchLive = async () => {
    setLoading(true);
    setRoute(null);
    setError(null);

    try {
      // Initialize a default Driver Vehicle (You, the driver)
      const myVehicle = {
        id: "Driver_1",
        capacity: 100, // Large capacity
        start_location: { lat: 25.1825, lon: 75.8236 } // Kota Center
      };
      setVehicle(myVehicle);

      // Call Backend to get orders created by Customers
      // Note: Make sure to use your IP if testing on mobile, or localhost if on PC
      const response = await axios.get('http://localhost:8000/api/orders');
      
      const liveOrders = response.data;
      
      if (liveOrders.length === 0) {
        setError("No active orders found. Go to /customer to create one!");
        setOrders([]);
      } else {
        setOrders(liveOrders);
      }

    } catch (err) {
      console.error(err);
      setError("Failed to fetch orders. Is backend running?");
    } finally {
      setLoading(false);
    }
  };

  // 2. Optimize Route
  const handleOptimize = async () => {
    if (!vehicle || orders.length === 0) {
      setError("No orders to optimize. Fetch live data first.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const payload = { vehicle, orders };
      const response = await axios.post('http://localhost:8000/api/optimize', payload);
      
      setRoute(response.data.route);
      setDistance((response.data.total_distance / 1000).toFixed(2)); 
    } catch (err) {
      console.error(err);
      setError("Optimization failed. Backend error.");
    } finally {
      setLoading(false);
    }
  };

  // 3. Helper for Map Lookup
  const createLocationLookup = () => {
    const lookup = {};
    if (vehicle) {
      lookup["DEPOT"] = vehicle.start_location;
      lookup["DEPOT_START"] = vehicle.start_location;
      lookup["DEPOT_END"] = vehicle.start_location;
    }
    orders.forEach((order) => {
      // Backend returns them as 'order.id'
      lookup[`${order.id}_pickup`] = order.pickup_location;
      lookup[`${order.id}_delivery`] = order.delivery_location;
    });
    return lookup;
  };

  // --- Styles ---
  const styles = {
    layout: { display: 'flex', height: '100vh', flexDirection: 'row', backgroundColor: '#1a1a1a', color: '#ecf0f1', overflow: 'hidden' },
    sidebar: { width: '350px', backgroundColor: '#2c3e50', padding: '20px', display: 'flex', flexDirection: 'column', boxShadow: '2px 0 10px rgba(0,0,0,0.5)', zIndex: 10 },
    header: { marginBottom: '30px' },
    title: { margin: 0, fontSize: '1.8rem', fontWeight: 'bold', color: '#e67e22' },
    subtitle: { margin: 0, fontSize: '0.85rem', opacity: 0.6 },
    statsGrid: { display: 'flex', gap: '10px', marginBottom: '20px' },
    statBox: { flex: 1, backgroundColor: '#34495e', padding: '15px', borderRadius: '8px', textAlign: 'center', border: '1px solid #465c71' },
    statLabel: { fontSize: '0.7rem', textTransform: 'uppercase', opacity: 0.7, display: 'block' },
    statValue: { fontSize: '1.4rem', fontWeight: 'bold', display: 'block', marginTop: '5px' },
    buttonGroup: { display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '30px' },
    btnSecondary: { padding: '12px', backgroundColor: '#34495e', color: 'white', border: '1px solid #5d6d7e', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' },
    btnPrimary: { padding: '12px', backgroundColor: '#e67e22', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' },
    orderList: { flex: 1, overflowY: 'auto' },
    card: { backgroundColor: '#34495e', padding: '15px', borderRadius: '6px', marginBottom: '10px', borderLeft: '4px solid #2ecc71' },
    mapContainer: { flex: 1, position: 'relative' }
  };

  return (
    <div style={styles.layout}>
      {/* Sidebar */}
      <div style={styles.sidebar}>
        <div style={styles.header}>
          <h1 style={styles.title}>FresQ Driver</h1>
          <p style={styles.subtitle}>Logistics Dashboard</p>
        </div>

        <div style={styles.statsGrid}>
          <div style={styles.statBox}>
            <span style={styles.statLabel}>PENDING ORDERS</span>
            <span style={styles.statValue}>{orders.length}</span>
          </div>
          <div style={styles.statBox}>
            <span style={styles.statLabel}>ROUTE KM</span>
            <span style={styles.statValue}>{distance}</span>
          </div>
        </div>

        <div style={styles.buttonGroup}>
          <button style={styles.btnSecondary} onClick={handleFetchLive} disabled={loading}>
            {loading ? "Fetching..." : "Fetch Live Orders"}
          </button>
          
          <button style={styles.btnPrimary} onClick={handleOptimize} disabled={loading || orders.length === 0}>
            Optimize Path
          </button>
        </div>

        {error && <div style={{padding:'10px', background:'#c0392b', marginBottom:'15px', borderRadius:'4px'}}>{error}</div>}

        <div style={styles.orderList}>
            {orders.length === 0 && <div style={{opacity:0.5, textAlign:'center'}}>No orders. Wait for customers.</div>}
            
            {orders.map((order, idx) => (
              <div key={idx} style={styles.card}>
                <div style={{fontWeight:'bold', marginBottom:'5px'}}>Order #{order.id}</div>
                <div style={{fontSize:'0.9rem', opacity:0.8}}>
                   <div>📦 {order.details}</div>
                   <div style={{marginTop:'5px', color:'#e67e22'}}>➡ To: {order.ngo_name}</div>
                </div>
              </div>
            ))}
        </div>
      </div>

      {/* Map Area */}
      <div style={styles.mapContainer}>
          <MapComponent route={route} locations={createLocationLookup()} />
      </div>
    </div>
  );
}

export default App;