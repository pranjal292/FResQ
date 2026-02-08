import math
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

class VRPSolver:
    def __init__(self):
        # Average speed assumption: 40 km/h = 666 meters/minute
        self.speed_mpm = 666  
        # Urgency Weight: Prioritize expiring goods
        self.urgency_weight = 100 

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """
        Calculate the great circle distance between two points 
        on the earth (specified in decimal degrees) in meters.
        """
        R = 6371000  # Radius of earth in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = math.sin(dphi / 2)**2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return int(R * c)

    def solve_route(self, vehicles, orders):
        """
        Solves the Multi-Vehicle Routing Problem with Load Balancing.
        """
        
        if not vehicles or not orders:
            return {}, 0

        # --- 1. BUILD NODE LIST ---
        nodes = []
        
        # A. Vehicle Start Nodes (Indices 0 to len(vehicles)-1)
        for v in vehicles:
            nodes.append({
                "lat": v.start_location.lat, 
                "lon": v.start_location.lon,
                "id": v.id,      
                "type": "start", 
                "demand": 0,
                "time_window": (0, 1440), 
                "priority": 0
            })

        # B. Order Nodes (Pickups and Deliveries)
        pickups_deliveries = []
        
        for order in orders:
            # Priority Score: Higher if closer to expiry
            priority_score = max(0, 1440 - order.delivery_window.end)
            
            # Pickup Node
            nodes.append({
                "lat": order.pickup_location.lat, 
                "lon": order.pickup_location.lon, 
                "id": order.id, 
                "type": "pickup",
                "demand": order.quantity,
                "time_window": (order.pickup_window.start, order.pickup_window.end),
                "priority": priority_score
            })
            p_index = len(nodes) - 1

            # Delivery Node
            nodes.append({
                "lat": order.delivery_location.lat, 
                "lon": order.delivery_location.lon, 
                "id": order.id, 
                "type": "delivery",
                "demand": -order.quantity,
                "time_window": (order.delivery_window.start, order.delivery_window.end),
                "priority": priority_score
            })
            d_index = len(nodes) - 1

            pickups_deliveries.append((p_index, d_index))

        # --- 2. CONFIG ROUTING MODEL ---
        num_vehicles = len(vehicles)
        starts = [i for i in range(num_vehicles)]
        ends = [i for i in range(num_vehicles)]

        manager = pywrapcp.RoutingIndexManager(len(nodes), num_vehicles, starts, ends)
        routing = pywrapcp.RoutingModel(manager)

        # --- 3. CALLBACKS ---
        
        # A. Cost Callback (Distance - Urgency Reward)
        def cost_callback(from_index, to_index):
            fn = manager.IndexToNode(from_index)
            tn = manager.IndexToNode(to_index)
            
            dist = self.haversine_distance(
                nodes[fn]["lat"], nodes[fn]["lon"], 
                nodes[tn]["lat"], nodes[tn]["lon"]
            )
            
            # Reduce effective cost for urgent nodes to encourage visiting them
            urgency_discount = nodes[tn]["priority"] * self.urgency_weight
            return max(0, dist - urgency_discount)

        transit_callback_index = routing.RegisterTransitCallback(cost_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        # B. Pure Distance Callback
        def distance_callback(from_index, to_index):
            fn = manager.IndexToNode(from_index)
            tn = manager.IndexToNode(to_index)
            return self.haversine_distance(
                nodes[fn]["lat"], nodes[fn]["lon"], 
                nodes[tn]["lat"], nodes[tn]["lon"]
            )

        dist_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.AddDimension(dist_callback_index, 0, 3000000, True, "Distance")

        # C. Time Callback (Travel + Service)
        def time_callback(from_index, to_index):
            dist = distance_callback(from_index, to_index)
            travel_time = int(dist / self.speed_mpm)
            
            fn = manager.IndexToNode(from_index)
            service_time = 10 if nodes[fn]["type"] != "start" else 0 
            return travel_time + service_time

        time_callback_index = routing.RegisterTransitCallback(time_callback)
        
        # Add Time Dimension with GLOBAL SPAN COST
        routing.AddDimension(
            time_callback_index,
            30,   # slack
            1440, # max duration
            False, 
            "Time"
        )
        time_dimension = routing.GetDimensionOrDie("Time")
        
        # --- KEY CHANGE: GLOBAL SPAN COST ---
        # This coefficient forces the solver to minimize the time of the *last* finishing driver.
        # This effectively forces load balancing.
        time_dimension.SetGlobalSpanCostCoefficient(500)

        # D. Capacity Callback
        def demand_callback(from_index):
            return nodes[manager.IndexToNode(from_index)]["demand"]

        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index, 0, [v.capacity for v in vehicles], True, "Capacity"
        )

        # --- 4. CONSTRAINTS ---
        for p, d in pickups_deliveries:
            p_idx = manager.NodeToIndex(p)
            d_idx = manager.NodeToIndex(d)
            
            routing.AddPickupAndDelivery(p_idx, d_idx)
            routing.solver().Add(routing.VehicleVar(p_idx) == routing.VehicleVar(d_idx))
            routing.solver().Add(time_dimension.CumulVar(p_idx) <= time_dimension.CumulVar(d_idx))

            d_node = nodes[d]
            time_dimension.CumulVar(d_idx).SetRange(
                int(d_node["time_window"][0]), 
                int(d_node["time_window"][1])
            )

        # --- 5. SOLVE ---
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_params.time_limit.seconds = 5
        
        solution = routing.SolveWithParameters(search_params)

        # --- 6. EXTRACT RESULTS ---
        routes = {} 
        total_dist_meters = 0
        
        if solution:
            for vehicle_idx in range(num_vehicles):
                index = routing.Start(vehicle_idx)
                driver_id = vehicles[vehicle_idx].id 
                route_steps = []
                
                while not routing.IsEnd(index):
                    node = nodes[manager.IndexToNode(index)]
                    arrival = solution.Min(time_dimension.CumulVar(index))
                    
                    loc_id = "DEPOT" if node["type"] == "start" else f"{node['id']}_{node['type']}"
                    
                    route_steps.append({
                        "location_id": loc_id,
                        "type": node["type"],
                        "arrival_time": arrival
                    })
                    
                    prev = index
                    index = solution.Value(routing.NextVar(index))
                    total_dist_meters += distance_callback(prev, index)
                
                # Check if route has actual work
                if len(route_steps) > 1:
                     routes[driver_id] = route_steps
                else:
                     routes[driver_id] = []
        
        return routes, total_dist_meters