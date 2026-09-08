-- Enable PostGIS Extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Create Stations Table
CREATE TABLE IF NOT EXISTS stations (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    location geography(Point, 4326)
);

-- Spatial index on stations location
CREATE INDEX IF NOT EXISTS idx_stations_location ON stations USING GIST (location);

-- Create Readings Table
CREATE TABLE IF NOT EXISTS readings (
    id BIGSERIAL PRIMARY KEY,
    station_id BIGINT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    pollutant VARCHAR(50) NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_readings_station_pollutant_ts UNIQUE (station_id, pollutant, timestamp)
);

-- Required Indexes on Readings
CREATE INDEX IF NOT EXISTS idx_readings_station_id ON readings (station_id);
CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings (timestamp);

-- Create Interpolated Locations Table (PEVI inputs for Parks / Green Spaces)
CREATE TABLE IF NOT EXISTS interpolated_locations (
    id BIGSERIAL PRIMARY KEY,
    location_name VARCHAR(255) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    pollutant VARCHAR(50) NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    location geography(Point, 4326),
    CONSTRAINT uq_interp_loc_pollutant_ts UNIQUE (location_name, pollutant, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_interp_loc_spatial ON interpolated_locations USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_interp_loc_ts ON interpolated_locations (timestamp);
CREATE INDEX IF NOT EXISTS idx_interp_loc_name ON interpolated_locations (location_name);

-- Create PEVI Scores Table (Park Environmental Vulnerability Index)
CREATE TABLE IF NOT EXISTS pevi_scores (
    id BIGSERIAL PRIMARY KEY,
    location_name VARCHAR(255) NOT NULL,
    pevi_value DOUBLE PRECISION NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    contrib_o3 DOUBLE PRECISION,
    contrib_no2 DOUBLE PRECISION,
    contrib_pm25 DOUBLE PRECISION,
    contrib_pm10 DOUBLE PRECISION,
    contrib_so2 DOUBLE PRECISION,
    contrib_co DOUBLE PRECISION,
    o3_ugm3 DOUBLE PRECISION,
    no2_ugm3 DOUBLE PRECISION,
    pm25_ugm3 DOUBLE PRECISION,
    pm10_ugm3 DOUBLE PRECISION,
    so2_ugm3 DOUBLE PRECISION,
    co_mgm3 DOUBLE PRECISION,
    CONSTRAINT uq_pevi_scores_loc_ts UNIQUE (location_name, timestamp)
);

-- Create Weather Table
CREATE TABLE IF NOT EXISTS weather (
    id BIGSERIAL PRIMARY KEY,
    station_id BIGINT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL,
    wind_speed DOUBLE PRECISION,
    wind_direction DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    precipitation DOUBLE PRECISION,
    temperature DOUBLE PRECISION,
    CONSTRAINT uq_weather_station_ts UNIQUE (station_id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_weather_station_id ON weather (station_id);
CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather (timestamp);
