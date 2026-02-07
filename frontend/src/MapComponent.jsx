import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, CircleMarker, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import axios from 'axios';
import L from 'leaflet';
import 'leaflet-polylinedecorator';

// --- CUSTOM PINS ---
const createPin = (type) => {
  let color = '#3b82f6';
  let icon = 'fas fa-car';
  
  if (type === 'pickup') { color = '#2ecc71'; icon = 'fas fa-box'; } 
  if (type === 'delivery') { color = '#e74c3c'; icon = 'fas fa-flag-checkered'; } 

  const css = `
    width: 32px; height: 32px;
    background: ${color};
    border-radius: 50% 50% 50% 0;
    transform: rotate(-45deg);
    position: absolute; left: 50%; top: 50%;
    margin: -16px 0 0 -16px;
    box-shadow: -3px 5px 8px rgba(0,0,0,0.6);
    display: flex; justify-content: center; align-items: center;
    border: 2px solid white;
  `;
  
  const iconCss = `
    transform: rotate(45deg);
    color: white; font-size: 14px;
  `;

  return L.divIcon({
    className: 'custom-pin',
    html: `<div style="${css}"><i class="${icon}" style="${iconCss}"></i></div>`,
    iconSize: [32, 42],
    iconAnchor: [16, 42],
    popupAnchor: [0, -35]
  });
};

// --- ARROWS COMPONENT ---
const RouteArrows = ({ positions }) => {
  const map = useMap();
  useEffect(() => {
    if (!map || !positions || positions.length === 0) return;
    const decorator = L.polylineDecorator(positions, {
      patterns: [{
          offset: '5%', repeat: '80px',
          symbol: L.Symbol.arrowHead({ 
            pixelSize: 14, 
            polygon: true, 
            pathOptions: { stroke: false, fill: true, color: '#ffffff', fillOpacity: 1 } 
          })
      }]
    });
    decorator.addTo(map);
    return () => map.removeLayer(decorator);
  }, [map, positions]);
  return null;
};

// --- MAIN COMPONENT ---
const MapComponent = ({ route, locations }) => {
  const [routePath, setRoutePath] = useState([]);
  const [ngos, setNgos] = useState([]);
  const defaultCenter = [25.1825, 75.8236]; // Kota

  // 1. Fetch NGOs ONCE on load (Permanent Visibility)
  useEffect(() => {
    axios.get('http://localhost:8000/api/ngos')
      .then(res => setNgos(res.data))
      .catch(err => console.error("Failed to fetch NGOs", err));
  }, []);

  // 2. Calculate Route Shape (OSRM)
  useEffect(() => {
    if (!route || route.length < 1) { 
        setRoutePath([]); 
        return; 
    }

    // Extract lat/lon from route locations
    const waypoints = route.map(point => locations[point.location_id]).filter(Boolean);
    
    // Add Driver Start (Depot) if available
    if (locations["DEPOT"]) waypoints.unshift(locations["DEPOT"]);

    if (waypoints.length < 2) return;

    const fetchRoadShape = async () => {
      try {
        const coordinatesString = waypoints.map(loc => `${loc.lon},${loc.lat}`).join(';');
        const url = `https://router.project-osrm.org/route/v1/driving/${coordinatesString}?overview=full&geometries=geojson`;
        const response = await axios.get(url);
        
        if (response.data.routes && response.data.routes.length > 0) {
            const geoJsonCoords = response.data.routes[0].geometry.coordinates;
            setRoutePath(geoJsonCoords.map(coord => [coord[1], coord[0]])); // Flip to LatLng
        }
      } catch (error) { 
          // Fallback: Straight lines if OSRM fails
          setRoutePath(waypoints.map(w => [w.lat, w.lon])); 
      }
    };
    fetchRoadShape();
  }, [route, locations]);

  const center = routePath.length > 0 ? routePath[0] : defaultCenter;

  return (
    <MapContainer key={center.join(',')} center={center} zoom={13} style={{ height: "100%", width: "100%", background: '#000' }}>
      {/* Dark Theme Tiles */}
      <TileLayer 
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" 
        attribution='&copy; OpenStreetMap &copy; CARTO'
      />

      {/* --- LAYER 1: STATIC NGOs (White/Red Dots) --- */}
      {ngos.map((ngo, idx) => (
        <CircleMarker 
            key={`ngo-${idx}`} 
            center={[ngo.lat, ngo.lon]} 
            radius={5} 
            pathOptions={{ color: '#666', weight: 1, fillColor: '#fff', fillOpacity: 0.8 }}
        >
            <Popup>
                <b style={{color:'black'}}>NGO: {ngo.name}</b><br/>
                <span style={{color:'black'}}>{ngo.city}</span>
            </Popup>
        </CircleMarker>
      ))}

      {/* --- LAYER 2: ROUTE LINE --- */}
      {routePath.length > 0 && (
        <>
          <Polyline positions={routePath} color="#ff6b00" weight={6} opacity={0.8} />
          <RouteArrows positions={routePath} />
        </>
      )}

      {/* --- LAYER 3: DYNAMIC PINS (Pickups & Drops) --- */}
      {route && route.map((point, idx) => {
        const loc = locations[point.location_id];
        if (!loc) return null;
        
        // Skip rendering start point if it's just the driver location (optional)
        if (point.type === 'start') return null;

        return (
          <Marker 
            key={`stop-${idx}`} 
            position={[loc.lat, loc.lon]} 
            icon={createPin(point.type)}
          >
            <Popup>
                <b style={{color:'black'}}>{point.type.toUpperCase()}</b><br/>
                <span style={{color:'black'}}>Stop #{idx}</span>
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
};

export default MapComponent;