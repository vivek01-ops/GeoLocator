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

API_KEY = 'AIzaSyAC1xdWpqg9idXyl0ZB3GU9kyPK2mZP-e8'  # Replace with your Google Maps API key
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
def get_users_in_same_city_and_root(temp_lat, temp_lon, root_lat, root_lon):
    users = session.query(User).filter(User.temp_latitude.isnot(None)).all()  # Users with a temporary location
    matching_users = []
    
    for user in users:
        temp_distance = haversine_distance(temp_lat, temp_lon, user.temp_latitude, user.temp_longitude)
        root_distance = haversine_distance(root_lat, root_lon, user.root_latitude, user.root_longitude)
        
        if temp_distance < 50 and root_distance < 50:  # Check if both root and temp cities are a match
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

# Function to perform HDBSCAN clustering
def cluster_users_hdbscan(users):
    coords = np.array([[user.temp_latitude, user.temp_longitude] for user in users])
    
    if len(coords) < 2:  # Need at least 2 points for clustering
        return [None] * len(users)

    try:
        clusterer = hdbscan.HDBSCAN(min_cluster_size=2)
        cluster_labels = clusterer.fit_predict(coords)
        return cluster_labels
    except Exception as e:
        st.warning(f"Clustering Error: {e}")
        return [None] * len(users)

# Function to perform BIRCH clustering
def cluster_users_birch(users):
    coords = np.array([[user.temp_latitude, user.temp_longitude] for user in users])
    
    if len(coords) < 2:  # Need at least 2 points for clustering
        return [None] * len(users)

    try:
        birch_model = Birch(n_clusters=None)
        cluster_labels = birch_model.fit_predict(coords)
        return cluster_labels
    except Exception as e:
        st.warning(f"Clustering Error: {e}")
        return [None] * len(users)

# Function to perform SOM clustering
def cluster_users_som(users):
    coords = np.array([[user.temp_latitude, user.temp_longitude] for user in users])
    
    if len(coords) < 2:  # Need at least 2 points for clustering
        return [None] * len(users)

    try:
        som = MiniSom(5, 5, 2, sigma=1.0, learning_rate=0.5)  # Adjust parameters as needed
        som.train(coords, 100)  # Training with 100 iterations
        bmus = som.win_map(coords)
        return [bmus for _ in range(len(users))]  # Return best matching units
    except Exception as e:
        st.warning(f"Clustering Error: {e}")
        return [None] * len(users)

# Display map with markers for root and temp locations, including geofence
def display_map_with_geofence(temp_lat, temp_lon, nearby_users):
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
                    radius: 1000  // Geofence radius in meters (1 km)
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
    return f"https://www.google.com/maps/search/?api=1&query={user.temp_latitude},{user.temp_longitude}"


# Registration Form
def show_registration():
    st.subheader("Register")
    name = st.text_input("Name")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    root_address = st.text_input("Home Location (Address)")
    
    if st.button("Register"):
        if not (name, email, password, root_address):
            st.error("All fields are required.")
        else:
            root_lat, root_lon = get_coordinates_google(root_address, API_KEY)
            if root_lat and root_lon:
                register_user(name, email, password, root_lat, root_lon)
                st.success("User registered successfully!")
            else:
                st.error("Invalid home location address.")

# Login Form
def show_login():
    st.subheader("Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    temp_address = st.text_input("Current Location (Address)")

    if st.button("Login"):
        if not (email and password and temp_address):
            st.error("All fields are required.")
        else:
            user = validate_login(email, password)
            if user:
                temp_lat, temp_lon = get_coordinates_google(temp_address, API_KEY)
                if temp_lat and temp_lon:
                    update_temp_location(user, temp_lat, temp_lon)

                    # Get nearby users
                    nearby_users = get_users_in_same_city_and_root(temp_lat, temp_lon, user.root_latitude, user.root_longitude)

                    if nearby_users:
                        # Perform clustering
                        hdbscan_labels = cluster_users_hdbscan(nearby_users)
                        birch_labels = cluster_users_birch(nearby_users)
                        som_bmus = cluster_users_som(nearby_users)

                        # Display the map with the user's current location and nearby users
                        display_map_with_geofence(temp_lat, temp_lon, nearby_users)

                        # Show tracking links for nearby friends
                        st.subheader("Tracking Links for Nearby Friends:")
                        for nearby_user in nearby_users:
                             link = generate_tracking_link(nearby_user)
                             st.write(f"{nearby_user.name}: [Track Location]({link})")

                        st.success("Clustering completed successfully, and the map is displayed.")
                    else:
                        st.warning("No users found in the same city with matching roots.")
                else:
                    st.error("Invalid current location address.")
            else:
                st.error("Invalid email or password.")

# Main function to switch between registration and login
def main():
    st.title("Global Geofencing App")
    menu = ["Login", "Register"]
    choice = st.sidebar.selectbox("Select an option", menu)

    if choice == "Register":
        show_registration()
    else:
        show_login()

if __name__ == "__main__":
    main()
