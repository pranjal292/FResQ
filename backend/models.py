from typing import List, Literal
from pydantic import BaseModel

class Location(BaseModel):
    lat: float
    lon: float

class TimeWindow(BaseModel):
    start: int
    end: int

class Order(BaseModel):
    id: str
    quantity: int
    pickup_location: Location
    pickup_window: TimeWindow
    delivery_location: Location
    delivery_window: TimeWindow
    service_time: int

class Vehicle(BaseModel):
    id: str
    capacity: int
    start_location: Location

class OptimizationRequest(BaseModel):
    vehicle: Vehicle
    orders: List[Order]

class RoutePoint(BaseModel):
    location_id: str
    arrival_time: int
    type: Literal['pickup', 'delivery']

class OptimizationResponse(BaseModel):
    route: List[RoutePoint]
    total_distance: float