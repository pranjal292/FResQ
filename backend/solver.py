import math
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

class VRPSolver:
    def __init__(self):
        # Average speed assumption: 40 km/h = 666 meters/minute
        self.speed_mpm = 666  
        # High urgency weight forces drivers to deviate for expiring food
        self.urgency_weight = 100 

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        R = 6371000  # Radius of earth in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return int(R * c)

    def solve_route(self, vehicles, orders):
        """
        Solves the Multi-Vehicle Routing Problem.
        Args:
            vehicles: List of Vehicle objects (All active drivers).
            orders: List of Order objects (All pending orders).
        """
        if not vehicles or not orders:
            return {}, 0

        # --- 1. BUILD NODE LIST ---
        # Structure: [Vehicle Starts (0..N-1)] + [Pickups & Deliveries (N...End)]
        nodes = []
        
        # Add Vehicle Starts (each driver has their own start node)
        for v in vehicles:
            nodes.append({
                "lat": v.start_location.lat, "lon": v.start_location.lon,
                "id": v.id, "type": "start", "demand": 0,
                "time_window": (0, 1440), "priority": 0
            })

        # Add Orders
        pickups_deliveries = []
        for order in orders:
            # Priority increases as expiration nears (1440 - end_time)
            priority_score = max(0, 1440 - order.delivery_window.end)
            
            # Pickup
            nodes.append({
                "lat": order.pickup_location.lat, "lon": order.pickup_location.lon,
                "id": order.id, "type": "pickup", "demand": order.quantity,
                "time_window": (order.pickup_window.start, order.pickup_window.end),
                "priority": priority_score
            })
            p_index = len(nodes) - 1

            # Delivery
            nodes.append({
                "lat": order.delivery_location.lat, "lon": order.delivery_location.lon,
                "id": order.id, "type": "delivery", "demand": -order.quantity,
                "time_window": (order.delivery_window.start, order.delivery_window.end),
                "priority": priority_score
            })
            d_index = len(nodes) - 1
            pickups_deliveries.append((p_index, d_index))

        # --- 2. CONFIG ---
        num_vehicles = len(vehicles)
        starts = [i for i in range(num_vehicles)] # Indices 0 to N-1 are starts
        ends = [i for i in range(num_vehicles)]   # Ends same as starts (Round trip or dummy)

        manager = pywrapcp.RoutingIndexManager(len(nodes), num_vehicles, starts, ends)
        routing = pywrapcp.RoutingModel(manager)

        # --- 3. CALLBACKS ---
        
        # Cost Callback (Distance + Urgency)
        def cost_callback(from_index, to_index):
            fn = manager.IndexToNode(from_index)
            tn = manager.IndexToNode(to_index)
            dist = self.haversine_distance(nodes[fn]["lat"], nodes[fn]["lon"], nodes[tn]["lat"], nodes[tn]["lon"])
            
            # Urgency Logic: Reduce "cost" for urgent items to attract drivers
            urgency_discount = nodes[tn]["priority"] * self.urgency_weight
            return max(0, dist - urgency_discount)

        transit_callback_index = routing.RegisterTransitCallback(cost_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        # Real Distance Callback (For Distance Dimension)
        def distance_callback(from_index, to_index):
            fn = manager.IndexToNode(from_index)
            tn = manager.IndexToNode(to_index)
            return self.haversine_distance(nodes[fn]["lat"], nodes[fn]["lon"], nodes[tn]["lat"], nodes[tn]["lon"])

        dist_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.AddDimension(dist_callback_index, 0, 3000000, True, "Distance")

        # Time Callback
        def time_callback(from_index, to_index):
            fn = manager.IndexToNode(from_index)
            dist = distance_callback(from_index, to_index)
            travel_time = int(dist / self.speed_mpm)
            service_time = 10 if nodes[fn]["type"] != "start" else 0
            return travel_time + service_time

        time_callback_index = routing.RegisterTransitCallback(time_callback)
        routing.AddDimension(time_callback_index, 30, 1440, False, "Time")
        time_dimension = routing.GetDimensionOrDie("Time")

        # Capacity Callback
        def demand_callback(from_index):
            return nodes[manager.IndexToNode(from_index)]["demand"]

        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index, 0, [v.capacity for v in vehicles], True, "Capacity"
        )

        # --- 4. CONSTRAINTS ---
        for p, d in pickups_deliveries:
            p_idx, d_idx = manager.NodeToIndex(p), manager.NodeToIndex(d)
            routing.AddPickupAndDelivery(p_idx, d_idx)
            routing.solver().Add(routing.VehicleVar(p_idx) == routing.VehicleVar(d_idx))
            routing.solver().Add(time_dimension.CumulVar(p_idx) <= time_dimension.CumulVar(d_idx))
            
            # Time Window (Expiry)
            d_node = nodes[d]
            time_dimension.CumulVar(d_idx).SetRange(
                int(d_node["time_window"][0]), int(d_node["time_window"][1])
            )

        # --- 5. SOLVE ---
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_params.time_limit.seconds = 5
        solution = routing.SolveWithParameters(search_params)

        # --- 6. OUTPUT ---
        routes = {} # Map: driver_id -> [steps]
        total_dist = 0
        
        if solution:
            for vehicle_id in range(num_vehicles):
                index = routing.Start(vehicle_id)
                real_driver_id = vehicles[vehicle_id].id 
                route_steps = []
                
                while not routing.IsEnd(index):
                    node = nodes[manager.IndexToNode(index)]
                    arrival = solution.Min(time_dimension.CumulVar(index))
                    loc_id = "DEPOT" if node["type"] == "start" else f"{node['id']}_{node['type']}"
                    
                    route_steps.append({
                        "location_id": loc_id, "type": node["type"], "arrival_time": arrival
                    })
                    
                    prev = index
                    index = solution.Value(routing.NextVar(index))
                    total_dist += distance_callback(prev, index)
                
                # Only assign if route has actual work
                if len(route_steps) > 1:
                    routes[real_driver_id] = route_steps
        
        return routes, total_dist