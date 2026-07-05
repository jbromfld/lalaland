-- Rebuild health tables for database: health
-- Health-related tables can be recreated from scratch by request.
-- This script is rerunnable and leaves the schema in the shape used by health/backend/app.py.

BEGIN;

DROP TABLE IF EXISTS public.apple_health_workouts;
DROP TABLE IF EXISTS public.fitness_events;
DROP TABLE IF EXISTS public.nutrition_events;
DROP TABLE IF EXISTS public.glucose_readings;

CREATE TABLE public.glucose_readings (
    timestamp TIMESTAMPTZ PRIMARY KEY,
    glucose_mgdl SMALLINT NOT NULL CHECK (glucose_mgdl > 0),
    source_device VARCHAR(100) NOT NULL DEFAULT 'FreeStyle Libre',
    serial_number TEXT NOT NULL DEFAULT 'unknown',
    record_type SMALLINT,
    scan_glucose_mgdl SMALLINT CHECK (scan_glucose_mgdl IS NULL OR scan_glucose_mgdl > 0)
);

CREATE TABLE public.fitness_events (
    id SERIAL PRIMARY KEY,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    activity_type VARCHAR(20),
    intensity_zone SMALLINT CHECK (intensity_zone BETWEEN 1 AND 5),
    avg_hr SMALLINT,
    notes TEXT
);

CREATE TABLE public.nutrition_events (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    meal_name VARCHAR(100),
    est_carbs_g DOUBLE PRECISION,
    est_protein_g DOUBLE PRECISION,
    est_fat_g DOUBLE PRECISION,
    is_buffer_meal BOOLEAN DEFAULT FALSE
);

CREATE TABLE public.apple_health_workouts (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(100),
    device VARCHAR(150),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    workout_type VARCHAR(100),
    activity_type VARCHAR(20),
    duration_seconds INTEGER,
    distance_meters DOUBLE PRECISION,
    avg_hr SMALLINT,
    avg_pace_sec_per_km DOUBLE PRECISION,
    elevation_ascended_meters DOUBLE PRECISION,
    calories_burned DOUBLE PRECISION,
    CONSTRAINT uq_apple_health_source_start UNIQUE (source_name, start_time)
);

CREATE INDEX IF NOT EXISTS ix_apple_health_workouts_start_time
    ON public.apple_health_workouts (start_time);

COMMIT;
