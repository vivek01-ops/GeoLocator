import streamlit as st
import requests
from math import radians, sin, cos, atan2, sqrt
from sqlalchemy import create_engine, Column, Integer, Float, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import hdbscan
from sklearn.cluster import Birch
import numpy as np
from minisom import MiniSom
import geocoder  # To automatically detect user location

API_KEY = 'AIzaSyAC1xdWpqg9idXyl0ZB3GU9kyPK2mZP-e8'
EARTH_RADIUS = 6371  # in kilometers
DATABASE_URL = 'sqlite:///global_geofencing.db'

st.set_page_config(page_title="Global Geofencing App", layout="centered", initial_sidebar_state="auto")
Base = declarative_base()

# Define the User table schema with root and current locations
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=False)
    root_latitude = Column(Float, nullable=False)  # Root (home) location
    root_longitude = Column(Float, nullable=False)
    temp_latitude = Column(Float, nullable=True)   # Temporary (current) location
    temp_longitude = Column(Float, nullable=True)
    last_updated = Column(String, nullable=True)   # Last location update time

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# Utility to get coordinates using Google Geocode API
def get_coordinates_google(address, api_key):
    url = f'https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}'
    response = requests.get(url)
    data = response.json()
    
    if data['status'] == 'OK':
        latitude = data['results'][0]['geometry']['location']['lat']
        longitude = data['results'][0]['geometry']['location']['lng']
        return latitude, longitude
    else:
        return None, None

# Automatically detect location using geocoder
def auto_detect_location():
    g = geocoder.ip('me')  # Detect the location using the device's IP address
    if g.latlng:
        return g.latlng[0], g.latlng[1]
    else:
        return None, None

# Calculate the distance between two lat-lon points using the haversine formula
def haversine_distance(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    distance = EARTH_RADIUS * c
    return distance

# Fetch users currently in the same temporary location and have the same root location
def get_users_in_same_city_and_root(temp_lat, temp_lon, root_lat, root_lon, radius):
    users = session.query(User).filter(User.temp_latitude.isnot(None)).all()  # Users with a temporary location
    matching_users = []
    
    for user in users:
        temp_distance = haversine_distance(temp_lat, temp_lon, user.temp_latitude, user.temp_longitude)
        root_distance = haversine_distance(root_lat, root_lon, user.root_latitude, user.root_longitude)
        
        if temp_distance < radius and root_distance < 50:  # Check if both root and temp cities are a match
            matching_users.append(user)
    
    return matching_users

# Register a new user with root location
def register_user(name, email, password, root_lat, root_lon):
    hashed_password = generate_password_hash(password)
    new_user = User(name=name, email=email, password=hashed_password, root_latitude=root_lat, root_longitude=root_lon)
    session.add(new_user)
    session.commit()

# Update the current location of a user
def update_temp_location(user, temp_lat, temp_lon):
    user.temp_latitude = temp_lat
    user.temp_longitude = temp_lon
    user.last_updated = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    session.commit()

# Validate user credentials
def validate_login(email, password):
    user = session.query(User).filter_by(email=email).first()
    if user and check_password_hash(user.password, password):
        return user
    return None

# Check if a user is already registered
def is_user_registered(email):
    user = session.query(User).filter_by(email=email).first()
    return user is not None

# Function to display nearby users and their tracking links
def show_nearby_users(nearby_users):
    if nearby_users:
        st.subheader("Nearby Users")
        for user in nearby_users:
            tracking_link = generate_tracking_link(user)
            st.write(f"{user.name}: [Track Location]({tracking_link})")
    else:
        st.info("No nearby users found.")

# Display map with markers for root and temp locations, including geofence
def display_map_with_geofence(temp_lat, temp_lon, nearby_users, radius):
    user_markers = ""
    for user in nearby_users:
        user_markers += f"""
        var userMarker = new google.maps.Marker({{
            position: {{ lat: {user.temp_latitude}, lng: {user.temp_longitude} }},
            map: map,
            icon: 'http://maps.google.com/mapfiles/ms/icons/blue-dot.png',
            title: '{user.name}'
        }});"""

    # Adding a geofence circle covering the user's location and friends
    st.components.v1.html(
        f"""
        <div id="map" style="height: 450px;"></div>
        <script>
            function initMap() {{
                var userLocation = {{lat: {temp_lat}, lng: {temp_lon}}};
                var map = new google.maps.Map(document.getElementById('map'), {{
                    zoom: 14,
                    center: userLocation
                }});
                var userMarker = new google.maps.Marker({{
                    position: userLocation,
                    map: map,
                    title: 'Your Current Location',
                    icon: 'http://maps.google.com/mapfiles/ms/icons/red-dot.png'  // Highlight the current user location with a red marker
                }});

                // Adding geofence circle around user's current location
                var geofence = new google.maps.Circle({{
                    strokeColor: '#FF0000',
                    strokeOpacity: 0.8,
                    strokeWeight: 2,
                    fillColor: '#FF0000',
                    fillOpacity: 0.2,
                    map: map,
                    center: userLocation,
                    radius: {radius * 1000}  // Geofence radius in meters
                }});
                {user_markers}
            }}
        </script>
        <script async defer src="https://maps.googleapis.com/maps/api/js?key={API_KEY}&callback=initMap"></script>
        """,
        height=450
    )

# Generate tracking link for friends that redirects to Google Maps
def generate_tracking_link(user):
    return f"https://www.google.com/maps?q={user.temp_latitude},{user.temp_longitude}"

# Registration Form
def show_registration():
    st.subheader("Register")
    name = st.text_input("Name")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    root_location = st.text_input("Enter your root (home) location")

    if st.button("Register"):
        if name and email and password and root_location:
            root_lat, root_lon = get_coordinates_google(root_location, API_KEY)
            if root_lat and root_lon:
                if not is_user_registered(email):
                    register_user(name, email, password, root_lat, root_lon)
                    st.success("Registration successful!")
                else:
                    st.warning("This email is already registered.")
            else:
                st.warning("Could not find the specified location. Please enter a valid address.")
        else:
            st.warning("All fields are required for registration.")

# Login Form
def show_login():
    st.subheader("Login")
    email = st.text_input("Email", placeholder="Enter your email address")    
    password = st.text_input("Password", type="password", placeholder="Enter your password")
    location_choice = st.radio("How do you want to set your current location?", ("Auto-detect", "Manual entry"))
    
    radius = st.number_input("Select the radius (in km) to find nearby users")  # Slider for geofence radius

    if location_choice == "Manual entry":
        current_location = st.text_input("Enter your current location", placeholder="Enter your current location")
    else:
        current_location = None  # Auto-detect location later

    if st.button("Login"):
        if email and password:
            user = validate_login(email, password)
            if user:
                if location_choice == "Manual entry" and current_location:
                    temp_lat, temp_lon = get_coordinates_google(current_location, API_KEY)
                else:
                    temp_lat, temp_lon = auto_detect_location()
                
                if temp_lat and temp_lon:
                    update_temp_location(user, temp_lat, temp_lon)
                    st.success(f"Welcome, {user.name}!")
                    
                    nearby_users = get_users_in_same_city_and_root(temp_lat, temp_lon, user.root_latitude, user.root_longitude, radius)
                    show_nearby_users(nearby_users)
                    display_map_with_geofence(temp_lat, temp_lon, nearby_users, radius)
                else:
                    st.warning("Could not detect your current location.")
            else:
                st.error("User not Registered. Please register with valid email-id.")
        else:
            st.warning("Please enter both email and password.")

# Main app structure
st.title("Global Geofencing App")
page = st.sidebar.selectbox("Choose a page", ["Login", "Register"])

if page == "Login":
    show_login()
else:
    show_registration()
