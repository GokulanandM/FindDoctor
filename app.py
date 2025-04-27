# app.py
import os
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv
import sys # Import sys for exiting
import polyline # Import polyline to decode the route path if needed server-side (though we'll decode in JS)

# Import Mapbox specific libraries
from mapbox import Directions # The Directions API client
import mapbox.errors # The errors module to catch API exceptions

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
MAPBOX_TOKEN = os.getenv('MAPBOX_TOKEN')
if not MAPBOX_TOKEN or MAPBOX_TOKEN == "YOUR_MAPBOX_ACCESS_TOKEN":
    print("Error: MAPBOX_TOKEN not found or is placeholder in .env file.")
    print("Please create/update a .env file in the same directory as app.py and add MAPBOX_TOKEN=YOUR_MAPBOX_ACCESS_TOKEN")
    print("Exiting.")
    sys.exit(1) # Use sys.exit to stop the script

# --- Initialize Mapbox Directions Client ---
try:
    directions_client = Directions(access_token=MAPBOX_TOKEN)
    print("Mapbox Directions Client initialized.")
except Exception as e:
    # Catch broader exceptions during client initialization if needed
    print(f"Error initializing Mapbox Client. Check your Access Token or network connection: {e}")
    print("Exiting.")
    sys.exit(1)


# --- CSV Configuration ---
# !!! IMPORTANT: REPLACE WITH YOUR ACTUAL FILE PATH !!!
csv_file_path = r'E:\Ungoppandahhh\doc.csv'
# !!! IMPORTANT: REPLACE WITH YOUR ACTUAL COLUMN NAMES !!!
latitude_column = 'LAT'
longitude_column = 'LON'
disease_column = 'Disease'
# Add other columns you might want to display in the popup
name_column = 'Name'
details_column = 'Details'

# --- Load and Preprocess Data from CSV ---
# Load this once when the application starts
csv_data_df = pd.DataFrame() # Initialize an empty DataFrame
data_load_success = False # Flag to indicate if data loaded ok

try:
    print(f"Attempting to load data from {csv_file_path}")
    df = pd.read_csv(csv_file_path)
    print(f"Successfully loaded data from {csv_file_path}. Initial rows: {len(df)}")

    # Validate columns
    required_columns = [latitude_column, longitude_column, disease_column]
    optional_columns_check = {name_column, details_column} # Use a set for faster lookup

    missing_required_columns = [col for col in required_columns if col not in df.columns]
    if missing_required_columns:
        print(f"Error: Missing required columns in the CSV: {missing_required_columns}")
        print(f"Available columns are: {df.columns.tolist()}")
        print("Exiting.")
        sys.exit(1)

    # Data Cleaning: Convert lat/lon to numeric, drop rows with invalid coordinates
    print("Cleaning data...")
    df[latitude_column] = pd.to_numeric(df[latitude_column], errors='coerce')
    df[longitude_column] = pd.to_numeric(df[longitude_column], errors='coerce')
    initial_rows = len(df)
    df.dropna(subset=[latitude_column, longitude_column], inplace=True)
    if len(df) < initial_rows:
        print(f"Removed {initial_rows - len(df)} rows due to invalid LAT/LON data.")

    # Data Cleaning: Handle potential NaN in disease column for filtering
    df[disease_column] = df[disease_column].fillna('').astype(str)

    # Store the cleaned DataFrame globally
    csv_data_df = df.copy() # Use .copy() to avoid potential issues later
    print(f"Data preprocessing complete. Usable rows: {len(csv_data_df)}")
    data_load_success = True

except FileNotFoundError:
    print(f"Error: The CSV file was not found at {csv_file_path}")
    print("Exiting.")
    sys.exit(1)
except Exception as e:
    print(f"An error occurred while loading or processing the CSV file: {e}")
    print("Exiting.")
    sys.exit(1)

if not data_load_success or csv_data_df.empty:
    print("Warning: No valid data points found in the CSV or data loading failed.")
    # We don't exit here, but the app won't show map markers


app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    found_locations = []
    search_disease = None
    user_lat = None
    user_lon = None

    # Default map center (can be based on your location or a general area)
    # Example: Your initial fixed location [lon, lat]
    # Adjust this to a suitable default if needed, perhaps the average of all points if data exists
    map_center = [77.0267093, 11.0285484]
    map_zoom = 12 # Default zoom level

    # If data loaded successfully, calculate a more sensible initial center/zoom based on the whole dataset
    if data_load_success and not csv_data_df.empty:
        try:
            avg_lat = csv_data_df[latitude_column].mean()
            avg_lon = csv_data_df[longitude_column].mean()
            map_center = [avg_lon, avg_lat]
            map_zoom = 10 # Zoom out a bit initially
        except Exception as e:
            print(f"Could not calculate initial average center from CSV data: {e}")
            # Fallback to hardcoded default center if calculation fails


    if request.method == 'POST':
        search_disease = request.form.get('disease_name', '').strip() # Keep original case for display
        search_disease_lower = search_disease.lower() # Use lowercase for filtering

        # Get user location from the form (sent via JavaScript)
        user_lat_str = request.form.get('user_lat')
        user_lon_str = request.form.get('user_lon')

        try:
            user_lat = float(user_lat_str) if user_lat_str else None
            user_lon = float(user_lon_str) if user_lon_str else None
            if user_lat is not None and user_lon is not None:
                 print(f"Received user location: Lat={user_lat}, Lon={user_lon}")
                 # If user location is available, center map on it after search
                 map_center = [user_lon, user_lat] # Mapbox expects [lon, lat]
                 map_zoom = 13 # Zoom in on user location
            else:
                 print("User location not provided or invalid.")

        except ValueError:
            print(f"Invalid user location coordinates received: lat={user_lat_str}, lon={user_lon_str}")
            user_lat = None
            user_lon = None # Treat as not provided


        if search_disease_lower and data_load_success and not csv_data_df.empty:
            # Filter the preloaded DataFrame based on the disease column (case-insensitive)
            filtered_df = csv_data_df[
                csv_data_df[disease_column].str.contains(search_disease_lower, case=False, na=False, regex=False)
            ].copy()

            # Prepare data for the template
            found_locations = []
            if not filtered_df.empty:
                # If user location is available, get routes, times, and distances
                if user_lat is not None and user_lon is not None:
                     user_location_mapbox = (user_lon, user_lat)
                     print(f"Calculating routes from user location ({user_lat}, {user_lon})...")

                     for index, row in filtered_df.iterrows():
                         loc_lat = row[latitude_column]
                         loc_lon = row[longitude_column]
                         doctor_location_mapbox = (loc_lon, loc_lat)

                         location_info = {
                             'lat': loc_lat,
                             'lon': loc_lon,
                             'disease_info': row[disease_column], # Full text from CSV
                             'travel_time_text': "Calculating...", # Initial placeholder
                             'travel_distance_text': "Calculating...",
                             'route_geometry_encoded': None # Will store Mapbox encoded polyline
                         }

                         # Add optional columns if they exist and are not NaN
                         if name_column in row and pd.notna(row[name_column]):
                              location_info['name'] = str(row[name_column])
                         if details_column in row and pd.notna(row[details_column]):
                              location_info['details'] = str(row[details_column])

                         try:
                             # Mapbox Directions API request
                             # Use profile 'mapbox/driving' for car routes
                             response = directions_client.directions(
                                [user_location_mapbox, doctor_location_mapbox],
                                profile='mapbox/driving', # Use the driving profile
                                geometries='polyline', # Request encoded polyline
                                overview='simplified' # Request simplified overview geometry
                             )
                             response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

                             directions_result = response.json()

                             if directions_result and directions_result.get('routes'):
                                 route = directions_result['routes'][0] # Get the first route

                                 duration_seconds = route.get('duration') # in seconds
                                 distance_meters = route.get('distance') # in meters
                                 route_geometry_encoded = route.get('geometry') # encoded polyline

                                 # Format time
                                 if duration_seconds is not None:
                                     minutes = int(duration_seconds // 60)
                                     hours = minutes // 60
                                     remaining_minutes = minutes % 60
                                     if hours > 0:
                                         location_info['travel_time_text'] = f"{hours} hr {remaining_minutes} min (driving)"
                                     else:
                                         location_info['travel_time_text'] = f"{minutes} min (driving)"
                                 else:
                                     location_info['travel_time_text'] = "Time N/A"

                                 # Format distance
                                 if distance_meters is not None:
                                     distance_km = distance_meters / 1000
                                     location_info['travel_distance_text'] = f"{distance_km:.2f} km (driving)"
                                 else:
                                     location_info['travel_distance_text'] = "Distance N/A"

                                 location_info['route_geometry_encoded'] = route_geometry_encoded # Store the encoded polyline

                                 # print(f"  - Route calculated for ({loc_lat}, {loc_lon})") # Debug print

                             elif directions_result and directions_result.get('code') != 'Ok':
                                  error_code = directions_result.get('code', 'Unknown API Error')
                                  error_message_detail = directions_result.get('message', '')
                                  print(f"  - Mapbox API returned error code for ({loc_lat}, {loc_lon}): {error_code} - {error_message_detail}")
                                  location_info['travel_time_text'] = f"API Error: {error_code}"
                                  location_info['travel_distance_text'] = f"API Error: {error_code}"
                             else:
                                 print(f"  - No route found by Mapbox for ({loc_lat}, {loc_lon}).")
                                 location_info['travel_time_text'] = "Route not found"
                                 location_info['travel_distance_text'] = "Route not found"

                         except mapbox.errors.MapboxAPIError as e:
                             print(f"  - Mapbox API Error getting route for ({loc_lat}, {loc_lon}): {e}")
                             location_info['travel_time_text'] = f"API Error: {e}"
                             location_info['travel_distance_text'] = f"API Error: {e}"
                         except Exception as e:
                             print(f"  - An unexpected error occurred getting route for ({loc_lat}, {loc_lon}): {e}")
                             location_info['travel_time_text'] = f"Error: {e}"
                             location_info['travel_distance_text'] = f"Error: {e}"

                         found_locations.append(location_info)

                else: # User location not available, just pass basic location info
                    print("User location not available. Skipping route calculations.")
                    for index, row in filtered_df.iterrows():
                         location_info = {
                             'lat': row[latitude_column],
                             'lon': row[longitude_column],
                             'disease_info': row[disease_column],
                             'travel_time_text': "Requires Location",
                             'travel_distance_text': "Requires Location",
                             'route_geometry_encoded': None
                         }
                         if name_column in row and pd.notna(row[name_column]):
                              location_info['name'] = str(row[name_column])
                         if details_column in row and pd.notna(row[details_column]):
                              location_info['details'] = str(row[details_column])
                         found_locations.append(location_info)


            # Recalculate map center/zoom based on *found* locations if no user location was provided
            # This helps center the map on the results if user location isn't used
            if found_locations and (user_lat is None or user_lon is None):
                try:
                     avg_lat = sum(loc['lat'] for loc in found_locations) / len(found_locations)
                     avg_lon = sum(loc['lon'] for loc in found_locations) / len(found_locations)
                     map_center = [avg_lon, avg_lat] # Mapbox expects [lon, lat]
                     map_zoom = 13 # Zoom in a bit when specific locations are found
                except Exception as e:
                     print(f"Could not calculate average center from found locations: {e}")
                     # Fallback to default or user location if available

    # Pass the actual search term, user location status, and found locations to the template
    return render_template(
        'index.html',
        mapbox_token=MAPBOX_TOKEN,
        locations=found_locations,
        search_disease=search_disease, # Use this for displaying the search term
        map_center=map_center,
        map_zoom=map_zoom,
        user_lat=user_lat, # Pass user location to JS to add a marker
        user_lon=user_lon
    )

if __name__ == '__main__':
    # Run the Flask app
    # debug=True is useful for development (auto-reloads on code changes)
    # app.run(debug=True, port=8000) # Example running on port 8000
    app.run(debug=True) # Runs on default port 5000