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
csv_file_path = r"doc.csv"
# !!! IMPORTANT: REPLACE WITH YOUR ACTUAL COLUMN NAMES !!!
latitude_column = 'LAT'
longitude_column = 'LON'
disease_column = 'Disease'
# Add other columns you might want to display in the popup
name_column = 'NAME'
details_column = 'Specialist'

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


# --- Initialize Flask App ---
# IMPORTANT: This MUST come *after* imports and setup, but *before* route definitions
app = Flask(__name__)

# --- Helper Function for Finding Locations and Calculating Routes ---
def find_and_calculate_routes(disease_to_find, origin_lat, origin_lon):
    """
    Filters the CSV data for a disease and calculates routes from the origin.

    Args:
        disease_to_find (str): The disease name to search for (case-insensitive).
        origin_lat (float): The latitude of the starting point (user location).
        origin_lon (float): The longitude of the starting point (user location).

    Returns:
        list: A list of dictionaries, where each dictionary represents a found
              location with its details and route information. Returns empty list
              if no data loaded, no disease provided, or no locations found.
    """
    results = []
    if not disease_to_find or not data_load_success or csv_data_df.empty:
        print("Helper: Invalid input or data not loaded, returning empty results.")
        return results

    disease_lower = disease_to_find.lower()
    origin_location_mapbox = (origin_lon, origin_lat) # Mapbox uses (lon, lat)

    print(f"Helper: Filtering for disease '{disease_lower}'...")
    filtered_df = csv_data_df[
        csv_data_df[disease_column].str.contains(disease_lower, case=False, na=False, regex=False)
    ].copy()

    if filtered_df.empty:
        print(f"Helper: No locations found matching '{disease_lower}'.")
        return results

    print(f"Helper: Found {len(filtered_df)} potential locations. Calculating routes from ({origin_lat}, {origin_lon})...")

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
            response = directions_client.directions(
               [origin_location_mapbox, doctor_location_mapbox],
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

        results.append(location_info)

    print(f"Helper: Finished processing {len(results)} locations.")
    return results


# --- Define Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    found_locations = []
    search_disease = None
    user_lat = None
    user_lon = None
    map_center = None
    map_zoom = None

    # --- Define Default/Fallback User Location ---
    # This is used if the browser doesn't provide location OR for the initial GET request.
    default_user_lat = 11.0283
    default_user_lon = 77.0273

    # --- Define Initial Search Parameters for GET request ---
    # <<< CHANGE THESE AS NEEDED >>>
    initial_load_disease = "Cardiology" # The disease to automatically search for on first load
    initial_load_user_lat = default_user_lat # Use the default coordinates for the initial search origin
    initial_load_user_lon = default_user_lon # Use the default coordinates for the initial search origin

    if request.method == 'POST':
        print("\n--- Handling POST Request ---")
        search_disease = request.form.get('disease_name', '').strip()

        # --- User Location Handling for POST Request ---
        user_lat_str = request.form.get('user_lat')
        user_lon_str = request.form.get('user_lon')

        temp_user_lat = None
        temp_user_lon = None

        try:
            # Try parsing the received coordinates
            if user_lat_str and user_lon_str:
                temp_user_lat = float(user_lat_str)
                temp_user_lon = float(user_lon_str)
                # Basic validation
                if not (-90 <= temp_user_lat <= 90 and -180 <= temp_user_lon <= 180):
                    print(f"Received coordinates out of valid range: Lat={temp_user_lat}, Lon={temp_user_lon}. Using default.")
                    temp_user_lat = None
                    temp_user_lon = None
                else:
                    print(f"Received user location from form: Lat={temp_user_lat}, Lon={temp_user_lon}")
            else:
                print("User location not provided by form. Using default.")

        except ValueError:
            print(f"Invalid (non-numeric) user location coordinates received: lat='{user_lat_str}', lon='{user_lon_str}'. Using default.")
            temp_user_lat = None
            temp_user_lon = None

        # Decide which location to use for routing: form input OR the default
        if temp_user_lat is not None and temp_user_lon is not None:
            user_lat = temp_user_lat
            user_lon = temp_user_lon
            print(f"Using user location from form for search: Lat={user_lat}, Lon={user_lon}")
        else:
            user_lat = default_user_lat
            user_lon = default_user_lon
            print(f"--- Using default/fallback user location for search: Lat={user_lat}, Lon={user_lon} ---")

        # --- Filter Data and Calculate Routes using Helper Function ---
        if search_disease:
            found_locations = find_and_calculate_routes(search_disease, user_lat, user_lon)
        else:
             print("No disease name provided in POST request.")
             found_locations = [] # Ensure it's empty if no disease searched

        # Set map center and zoom based on the determined user location for POST
        map_center = [user_lon, user_lat]
        map_zoom = 14 # Zoom in closer for specific searches

    else: # Handle GET Request (Initial Page Load)
        print("\n--- Handling GET Request (Initial Load) ---")
        # Perform the predefined initial search
        search_disease = initial_load_disease
        user_lat = initial_load_user_lat
        user_lon = initial_load_user_lon

        print(f"Performing initial search for disease: '{search_disease}'")
        print(f"Using predefined initial user location: Lat={user_lat}, Lon={user_lon}")

        found_locations = find_and_calculate_routes(search_disease, user_lat, user_lon)

        # Set map center and zoom for the initial view based on the predefined location
        map_center = [user_lon, user_lat]
        map_zoom = 13 # Maybe slightly less zoomed in for initial view

    # --- Render Template ---
    # Pass the final determined values to the template
    # These variables will now always have appropriate values based on GET or POST
    print(f"Rendering template with {len(found_locations)} locations.")
    print(f"Map Center: {map_center}, Zoom: {map_zoom}")
    print(f"Search Disease: '{search_disease}', User Location: ({user_lat}, {user_lon})")
    return render_template(
        'index.html',
        mapbox_token=MAPBOX_TOKEN,
        locations=found_locations,
        search_disease=search_disease, # Will be the initial disease or the searched one
        map_center=map_center,      # Will be initial default loc or user's loc
        map_zoom=map_zoom,          # Adjusted based on context
        user_lat=user_lat,          # Will be initial default lat or user's lat
        user_lon=user_lon           # Will be initial default lon or user's lon
    )

# --- Run Flask App ---
# This block should be at the very end of the file
if __name__ == '__main__':
    # debug=True enables auto-reloading and detailed error pages (useful for development)
    # Use a production WSGI server (like Gunicorn or Waitress) for deployment
    app.run(debug=True)
