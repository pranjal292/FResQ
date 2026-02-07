import math
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

class VRPSolver:
    def __init__(self):
        pass

    def calculate_distance(self, lat1, lon1, lat2, lon2):
        # Manhattan distance approximation (meters)
        lat_m = abs(lat1 - lat2) * 111000.0
        lon_m = abs(lon1 - lon2) * 111000.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
        return int(lat_m + lon_m)

    def solve_route(self, data):
        nodes = []
        # Node 0: Depot (Driver Start)
        nodes.append({
            "lat": data.vehicle.start_location.lat, 
            "lon": data.vehicle.start_location.lon,
            "id": "DEPOT", "type": "start"
        })

        orders = data.orders
        for order in orders:
            nodes.append({"lat": order.pickup_location.lat, "lon": order.pickup_location.lon, "id": order.id, "type": "pickup"})
            nodes.append({"lat": order.delivery_location.lat, "lon": order.delivery_location.lon, "id": order.id, "type": "delivery"})

        if not orders:
            return [], 0

        manager = pywrapcp.RoutingIndexManager(len(nodes), 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            fn = manager.IndexToNode(from_index)
            tn = manager.IndexToNode(to_index)
            return self.calculate_distance(nodes[fn]["lat"], nodes[fn]["lon"], nodes[tn]["lat"], nodes[tn]["lon"])

        transit_idx = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
        routing.AddDimension(transit_idx, 0, 3000000, True, "Distance")
        distance_dimension = routing.GetDimensionOrDie("Distance")

        for i in range(len(orders)):
            p_idx = manager.NodeToIndex(1 + (i * 2))
            d_idx = manager.NodeToIndex(2 + (i * 2))
            routing.AddPickupAndDelivery(p_idx, d_idx)
            routing.solver().Add(distance_dimension.CumulVar(p_idx) <= distance_dimension.CumulVar(d_idx))
            # Force visit with high penalty
            routing.AddDisjunction([p_idx], 10000000)
            routing.AddDisjunction([d_idx], 10000000)

        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_params.time_limit.seconds = 5
        
        solution = routing.SolveWithParameters(search_params)
        route = []

        if solution:
            index = routing.Start(0)
            while not routing.IsEnd(index):
                node_idx = manager.IndexToNode(index)
                node = nodes[node_idx]
                
                # Add node to route
                loc_id = "DEPOT" if node['type'] == 'start' else f"{node['id']}_{node['type']}"
                route.append({"location_id": loc_id, "type": node["type"], "arrival_time": 0})
                
                index = solution.Value(routing.NextVar(index))
                
            # CHECK FINAL DESTINATION
            # If the routing model loops back to start (Node 0), do NOT append it.
            node_idx = manager.IndexToNode(index)
            node = nodes[node_idx]
            
            if node['type'] != 'start': 
                # Only add the final node if it is NOT the depot
                loc_id = f"{node['id']}_{node['type']}"
                route.append({"location_id": loc_id, "type": node["type"], "arrival_time": 0})
        else:
            # Fallback
            for node in nodes:
                if node['type'] != 'start': # Simple linear fallback
                    loc_id = f"{node['id']}_{node['type']}"
                    route.append({"location_id": loc_id, "type": node["type"], "arrival_time": 0})

        return route, 0