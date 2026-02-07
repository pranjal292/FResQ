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
    background-color: ${color};
    width: 30px; height: 30px;
    display: flex; justify-content: center; align-items: center;
    border-radius: 30px 30px 0;
    transform: rotate(45deg);
    border: 2px solid #FFFFFF;
    box-shadow: 1px 1px 4px rgba(0,0,0,0.5);
  `;
  
  const iconCss = `transform: rotate(-45deg); color: white; font-size: 14px;`;

  return L.divIcon({
    className: 'custom-pin-icon',
    html: `<div style="${css}"><i class="${icon}" style="${iconCss}"></i></div>`,
    iconSize: [30, 42],
    iconAnchor: [15, 42],
    popupAnchor: [0, -35]
  });
};

// --- HELPER TO HANDLE THEME CHANGE ---
const TileLayerHandler = ({ darkMode }) => {
    const map = useMap();
    const darkUrl = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
    const lightUrl = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
    
    // We render a standard TileLayer, changing the URL prop will auto-update
    return (
        <TileLayer 
            url={darkMode ? darkUrl : lightUrl} 
            attribution='&copy; OpenStreetMap &copy; CARTO'
        />
    );
};

const RouteArrows = ({ positions }) => {
  const map = useMap();
  useEffect(() => {
    if (!map || !positions || positions.length === 0) return;
    const decorator = L.polylineDecorator(positions, {
      patterns: [{
          offset: '5%', repeat: '80px',
          symbol: L.Symbol.arrowHead({ pixelSize: 14, polygon: true, pathOptions: { stroke: false, fill: true, color: '#ffffff', fillOpacity: 1 } })
      }]
    });
    decorator.addTo(map);
    return () => map.removeLayer(decorator);
  }, [map, positions]);
  return null;
};

// --- MAIN COMPONENT ---
const MapComponent = ({ route, locations, darkMode }) => {
  const [routePath, setRoutePath] = useState([]);
  const [ngos, setNgos] = useState([]);
  const defaultCenter = [25.1825, 75.8236]; 

  useEffect(() => {
    axios.get('http://localhost:8000/api/ngos')
      .then(res => setNgos(res.data))
      .catch(err => console.error("Failed to fetch NGOs", err));
  }, []);

  useEffect(() => {
    if (!route || route.length < 1) { setRoutePath([]); return; }
    const waypoints = route.map(point => locations[point.location_id]).filter(Boolean);
    if (locations["DEPOT"]) waypoints.unshift(locations["DEPOT"]);
    if (waypoints.length < 2) return;

    const fetchRoadShape = async () => {
      try {
        const coords = waypoints.map(loc => `${loc.lon},${loc.lat}`).join(';');
        const url = `https://router.project-osrm.org/route/v1/driving/${coords}?overview=full&geometries=geojson`;
        const response = await axios.get(url);
        if (response.data.routes && response.data.routes.length > 0) {
            const geo = response.data.routes[0].geometry.coordinates;
            setRoutePath(geo.map(c => [c[1], c[0]]));
        }
      } catch (error) { setRoutePath(waypoints.map(w => [w.lat, w.lon])); }
    };
    fetchRoadShape();
  }, [route, locations]);

  const center = routePath.length > 0 ? routePath[0] : defaultCenter;

  return (
    <MapContainer key={center.join(',')} center={center} zoom={13} style={{ height: "100%", width: "100%", background: darkMode ? '#1a1a1a' : '#ddd' }}>
      
      {/* Dynamic Tile Layer */}
      <TileLayerHandler darkMode={darkMode} />

      {ngos.map((ngo, idx) => (
        <CircleMarker 
            key={`ngo-${idx}`} center={[ngo.lat, ngo.lon]} radius={5} 
            pathOptions={{ color: '#666', weight: 1, fillColor: '#fff', fillOpacity: 0.8 }}
        >
            <Popup><b style={{color:'black'}}>NGO: {ngo.name}</b></Popup>
        </CircleMarker>
      ))}

      {routePath.length > 0 && (
        <>
          <Polyline positions={routePath} color="#ff6b00" weight={6} opacity={0.8} />
          <RouteArrows positions={routePath} />
        </>
      )}

      {route && route.map((point, idx) => {
        const loc = locations[point.location_id];
        if (!loc || point.type === 'start') return null;

        return (
          <Marker 
            key={`stop-${idx}`} position={[loc.lat, loc.lon]} icon={createPin(point.type)} zIndexOffset={1000}
          >
            <Popup>
                <div style={{color:'black', textAlign:'center'}}>
                   <b>{point.type.toUpperCase()}</b><br/>Step #{idx}
                </div>
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
};

export default MapComponent;