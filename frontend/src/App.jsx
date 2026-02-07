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
  
  // --- THEME STATE ---
  const [darkMode, setDarkMode] = useState(true);

  // 1. Fetch Live Orders
  const handleFetchLive = async () => {
    setLoading(true);
    setRoute(null);
    setError(null);

    try {
      const myVehicle = {
        id: "Driver_1",
        capacity: 100, 
        start_location: { lat: 25.1825, lon: 75.8236 } 
      };
      setVehicle(myVehicle);

      const response = await axios.get('http://localhost:8000/api/orders');
      const liveOrders = response.data;
      
      if (liveOrders.length === 0) {
        setError("No active orders found. Go to /customer to create one!");
        setOrders([]);
      } else {
        const sortedOrders = liveOrders.sort((a, b) => 
          a.pickup_window.end - b.pickup_window.end
        );
        setOrders(sortedOrders);
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

  // 3. Helpers
  const createLocationLookup = () => {
    const lookup = {};
    if (vehicle) {
      lookup["DEPOT"] = vehicle.start_location;
      lookup["DEPOT_START"] = vehicle.start_location;
      lookup["DEPOT_END"] = vehicle.start_location;
    }
    orders.forEach((order) => {
      const strId = String(order.id); 
      lookup[`${strId}_pickup`] = order.pickup_location;
      lookup[`${strId}_delivery`] = order.delivery_location;
    });
    return lookup;
  };

  const getOrderStyle = (minsRemaining) => {
    // Critical: < 2 Hours
    if (minsRemaining <= 120) {
      return {
        borderLeft: '6px solid #e74c3c',
        background: darkMode ? '#342222' : '#fce4e4', // Adaptive dark/light bg
        color: darkMode ? '#ecf0f1' : '#2c3e50',
        animation: 'pulse 2s infinite'
      };
    }
    // High Priority
    if (minsRemaining <= 300) {
      return {
        borderLeft: '6px solid #e67e22',
        background: darkMode ? '#34495e' : '#fff3e0',
        color: darkMode ? '#ecf0f1' : '#2c3e50'
      };
    }
    // Normal
    return {
      borderLeft: '4px solid #2ecc71',
      background: darkMode ? '#34495e' : '#e8f8f5',
      color: darkMode ? '#ecf0f1' : '#2c3e50'
    };
  };

  // --- DYNAMIC STYLES ---
  const theme = {
    bg: darkMode ? '#1a1a1a' : '#f4f4f9',
    sidebar: darkMode ? '#2c3e50' : '#ffffff',
    text: darkMode ? '#ecf0f1' : '#2c3e50',
    statBox: darkMode ? '#34495e' : '#ecf0f1',
    border: darkMode ? '#465c71' : '#bdc3c7',
    card: darkMode ? '#34495e' : '#ffffff'
  };

  const styles = {
    layout: { display: 'flex', height: '100vh', flexDirection: 'row', backgroundColor: theme.bg, color: theme.text, overflow: 'hidden', transition: '0.3s' },
    sidebar: { width: '350px', backgroundColor: theme.sidebar, padding: '20px', display: 'flex', flexDirection: 'column', boxShadow: '2px 0 10px rgba(0,0,0,0.1)', zIndex: 10, transition: '0.3s' },
    header: { marginBottom: '30px', display:'flex', justifyContent:'space-between', alignItems:'center' },
    title: { margin: 0, fontSize: '1.8rem', fontWeight: 'bold', color: '#e67e22' },
    subtitle: { margin: 0, fontSize: '0.85rem', opacity: 0.6 },
    statsGrid: { display: 'flex', gap: '10px', marginBottom: '20px' },
    statBox: { flex: 1, backgroundColor: theme.statBox, padding: '15px', borderRadius: '8px', textAlign: 'center', border: `1px solid ${theme.border}` },
    statLabel: { fontSize: '0.7rem', textTransform: 'uppercase', opacity: 0.7, display: 'block', color: theme.text },
    statValue: { fontSize: '1.4rem', fontWeight: 'bold', display: 'block', marginTop: '5px', color: theme.text },
    buttonGroup: { display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '30px' },
    btnSecondary: { padding: '12px', backgroundColor: theme.statBox, color: theme.text, border: `1px solid ${theme.border}`, borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' },
    btnPrimary: { padding: '12px', backgroundColor: '#e67e22', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' },
    orderList: { flex: 1, overflowY: 'auto' },
    card: { padding: '15px', borderRadius: '6px', marginBottom: '10px', transition: '0.3s', boxShadow: darkMode ? 'none' : '0 2px 5px rgba(0,0,0,0.05)' },
    mapContainer: { flex: 1, position: 'relative' },
    
    // Floating Theme Button
    themeToggle: {
      position: 'absolute', top: '20px', right: '20px', zIndex: 1000,
      width: '45px', height: '45px', borderRadius: '50%',
      backgroundColor: theme.sidebar, color: theme.text,
      border: `1px solid ${theme.border}`,
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      cursor: 'pointer', boxShadow: '0 4px 10px rgba(0,0,0,0.3)',
      fontSize: '1.2rem'
    },
    // Home Button in Header
    homeBtn: {
      color: theme.text, textDecoration: 'none', fontSize: '1.2rem', 
      cursor: 'pointer', padding: '5px', marginLeft: '10px'
    }
  };

  return (
    <div style={styles.layout}>
      {/* Pulse Animation Style */}
      <style>{`@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(231, 76, 60, 0.4); } 70% { box-shadow: 0 0 0 10px rgba(231, 76, 60, 0); } 100% { box-shadow: 0 0 0 0 rgba(231, 76, 60, 0); } }`}</style>

      {/* Sidebar */}
      <div style={styles.sidebar}>
        <div style={styles.header}>
          <div>
            <h1 style={styles.title}>FresQ Driver</h1>
            <p style={styles.subtitle}>Logistics Dashboard</p>
          </div>
          {/* HOME BUTTON */}
          <a href="http://localhost:8000/" style={styles.homeBtn} title="Go Home">
            <i className="fas fa-home"></i>
          </a>
        </div>

        <div style={styles.statsGrid}>
          <div style={styles.statBox}>
            <span style={styles.statLabel}>PENDING</span>
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

        {error && <div style={{padding:'10px', background:'#c0392b', color:'white', marginBottom:'15px', borderRadius:'4px'}}>{error}</div>}

        <div style={styles.orderList}>
            {orders.length === 0 && <div style={{opacity:0.5, textAlign:'center'}}>No orders. Wait for customers.</div>}
            
            {orders.map((order, idx) => {
              const minutesLeft = order.pickup_window ? order.pickup_window.end : 999;
              const cardStyle = { ...styles.card, ...getOrderStyle(minutesLeft) };
              const isCritical = minutesLeft <= 120;

              return (
                <div key={idx} style={cardStyle}>
                  <div style={{fontWeight:'bold', marginBottom:'5px', display:'flex', justifyContent:'space-between'}}>
                    <span>Order #{String(order.id).substring(0,4)}</span>
                    {isCritical && <span style={{color:'#e74c3c', fontSize:'0.8rem'}}>⚠️ CRITICAL</span>}
                  </div>
                  <div style={{fontSize:'0.9rem', opacity:0.9}}>
                     <div>📦 {order.details}</div>
                     <div style={{marginTop:'5px', fontSize:'0.8rem', opacity:0.8}}>
                       <i className="fas fa-clock"></i> Expires in: <b>{minutesLeft} mins</b>
                     </div>
                     <div style={{marginTop:'5px', color: isCritical ? '#e74c3c' : '#e67e22', fontWeight:'bold'}}>
                       ➡ To: {order.ngo_name}
                     </div>
                  </div>
                </div>
              );
            })}
        </div>
      </div>

      {/* Map Area */}
      <div style={styles.mapContainer}>
          {/* THEME TOGGLE BUTTON */}
          <div style={styles.themeToggle} onClick={() => setDarkMode(!darkMode)}>
             <i className={darkMode ? "fas fa-sun" : "fas fa-moon"}></i>
          </div>

          <MapComponent 
             route={route} 
             locations={createLocationLookup()} 
             darkMode={darkMode} // Pass theme to map
          />
      </div>
    </div>
  );
}

export default App;