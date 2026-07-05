from __future__ import annotations

import csv
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.config import Settings
from backend.db import (
    delete_apple_health_workout as db_delete_apple_health_workout,
    delete_glucose_reading as db_delete_glucose_reading,
    delete_nutrition_event as db_delete_nutrition_event,
    fetch_latest_apple_health_workout_start_time,
    insert_nutrition_event,
    get_connection,
    list_apple_health_workouts,
    list_glucose_readings,
    list_nutrition_events,
    update_nutrition_event,
    upsert_apple_health_workout,
    upsert_glucose_reading,
)


APPLE_HEALTH_WORKOUT_MAP = {
    "HKWorkoutActivityTypeRunning": "run",
    "HKWorkoutActivityTypeWalking": "run",
    "HKWorkoutActivityTypeHiking": "run",
    "HKWorkoutActivityTypeCycling": "bike",
    "HKWorkoutActivityTypeSwimming": "swim",
    "HKWorkoutActivityTypeOpenWaterSwimming": "swim",
    "HKWorkoutActivityTypeTraditionalStrengthTraining": "strength",
    "HKWorkoutActivityTypeFunctionalStrengthTraining": "strength",
    "HKWorkoutActivityTypeCrossTraining": "strength",
    "HKWorkoutActivityTypeHighIntensityIntervalTraining": "strength",
    "HKWorkoutActivityTypeElliptical": "strength",
    "HKWorkoutActivityTypeYoga": "strength",
    "HKWorkoutActivityTypePilates": "strength",
    "HKWorkoutActivityTypeStairClimbing": "strength",
    "HKWorkoutActivityTypeRowing": "strength",
}


def _resolve_timezone(name: str):
    if name.lower() == "local":
        return datetime.now().astimezone().tzinfo

    return ZoneInfo(name)


def _day_bounds(settings: Settings, target_date: date) -> tuple[datetime, datetime]:
    timezone = _resolve_timezone(settings.schedule_timezone)
    start = datetime.combine(target_date, time.min, timezone)
    return start, start + timedelta(days=1)


def fetch_health_day_for_date(settings: Settings, target_date: date) -> dict:
    start_at, end_at = _day_bounds(settings, target_date)
    return {
        "date": target_date.isoformat(),
        "nutrition": list_nutrition_events(settings, start_at, end_at),
        "glucose": list_glucose_readings(settings, start_at, end_at),
        "apple_health_workouts": list_apple_health_workouts(settings, start_at, end_at),
    }


def create_nutrition_entry(
    settings: Settings,
    *,
    timestamp: datetime,
    meal_name: str | None,
    est_carbs_g: float | None,
    est_protein_g: float | None,
    est_fat_g: float | None,
    comments: str | None,
    is_buffer_meal: bool,
) -> dict:
    return insert_nutrition_event(
        settings,
        timestamp=timestamp,
        meal_name=meal_name,
        est_carbs_g=est_carbs_g,
        est_protein_g=est_protein_g,
        est_fat_g=est_fat_g,
        comments=comments,
        is_buffer_meal=is_buffer_meal,
    )


def update_nutrition_entry(
    settings: Settings,
    event_id: int,
    *,
    timestamp: datetime,
    meal_name: str | None,
    est_carbs_g: float | None,
    est_protein_g: float | None,
    est_fat_g: float | None,
    comments: str | None,
    is_buffer_meal: bool,
) -> dict | None:
    return update_nutrition_event(
        settings,
        event_id,
        timestamp=timestamp,
        meal_name=meal_name,
        est_carbs_g=est_carbs_g,
        est_protein_g=est_protein_g,
        est_fat_g=est_fat_g,
        comments=comments,
        is_buffer_meal=is_buffer_meal,
    )


def remove_nutrition_entry(settings: Settings, event_id: int) -> dict | None:
    return db_delete_nutrition_event(settings, event_id)


def create_glucose_entry(
    settings: Settings,
    *,
    timestamp: datetime,
    glucose_mgdl: int,
    source_device: str,
) -> bool:
    with get_connection(settings) as conn:
        inserted = upsert_glucose_reading(
            conn,
            timestamp=timestamp,
            glucose_mgdl=glucose_mgdl,
            source_device=source_device,
            serial_number="manual",
            record_type=None,
            scan_glucose_mgdl=None,
        )
        conn.commit()
        return inserted


def _find_libre_header_row(rows: list[list[str]]) -> tuple[int, list[str]]:
    required = {
        "Device",
        "Serial Number",
        "Device Timestamp",
        "Historic Glucose mg/dL",
        "Scan Glucose mg/dL",
    }
    for index, row in enumerate(rows):
        header = [cell.strip() for cell in row]
        if required.issubset(set(header)):
            return index, header
    raise ValueError(
        "Libre CSV header not found. Expected columns including "
        "'Device Timestamp', 'Historic Glucose mg/dL', and 'Scan Glucose mg/dL'."
    )


def _parse_libre_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%m-%d-%Y %I:%M %p").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"Invalid Device Timestamp: {value}") from exc


def _to_int(value: str, *, field_name: str) -> int | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def import_glucose_csv(
    settings: Settings,
    *,
    file_name: str,
    file_bytes: bytes,
) -> dict:
    stream = io.StringIO(file_bytes.decode("utf-8-sig"), newline=None)
    rows = list(csv.reader(stream))
    if not rows:
        raise ValueError("CSV is empty")

    header_index, header = _find_libre_header_row(rows)

    results = {
        "loaded": 0,
        "skipped": 0,
        "errors": 0,
        "file_name": file_name,
        "error_details": [],
    }

    with get_connection(settings) as conn:
        for row_num, raw_row in enumerate(rows[header_index + 1 :], start=header_index + 2):
            if not any(cell.strip() for cell in raw_row):
                continue

            try:
                padded_row = raw_row + [""] * max(0, len(header) - len(raw_row))
                row = dict(zip(header, padded_row, strict=False))

                timestamp_str = (row.get("Device Timestamp") or "").strip()
                historic_glucose_str = (row.get("Historic Glucose mg/dL") or "").strip()
                scan_glucose_str = (row.get("Scan Glucose mg/dL") or "").strip()

                if not timestamp_str:
                    raise ValueError("Missing Device Timestamp")

                glucose_str = historic_glucose_str or scan_glucose_str
                if not glucose_str:
                    raise ValueError("Missing glucose value in Historic or Scan columns")

                timestamp = _parse_libre_timestamp(timestamp_str)
                glucose = int(glucose_str)
                if glucose <= 0:
                    raise ValueError("Glucose value must be greater than 0")

                source_device = (row.get("Device") or "").strip() or "FreeStyle Libre"
                serial_number = (row.get("Serial Number") or "").strip() or "unknown"
                record_type = _to_int(row.get("Record Type") or "", field_name="Record Type")
                scan_glucose = _to_int(scan_glucose_str, field_name="Scan Glucose mg/dL")
                if scan_glucose is not None and scan_glucose <= 0:
                    raise ValueError("Scan Glucose mg/dL must be greater than 0")

                inserted = upsert_glucose_reading(
                    conn,
                    timestamp=timestamp,
                    glucose_mgdl=glucose,
                    source_device=source_device,
                    serial_number=serial_number,
                    record_type=record_type,
                    scan_glucose_mgdl=scan_glucose,
                )
                if inserted:
                    results["loaded"] += 1
                else:
                    results["skipped"] += 1
            except ValueError as exc:
                results["errors"] += 1
                results["error_details"].append({"row": row_num, "error": str(exc)})

        conn.commit()

    return results


def _parse_apple_health_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")


def _clean_device_name(device: str | None) -> str | None:
    if device and "name:" in device:
        try:
            return device.split("name:")[1].split(",")[0].strip()
        except Exception:
            return device
    return device


def _distance_meters_from_workout_statistics(workout) -> float | None:
    distance_stat_types = (
        "HKQuantityTypeIdentifierDistanceWalkingRunning",
        "HKQuantityTypeIdentifierDistanceCycling",
        "HKQuantityTypeIdentifierDistanceSwimming",
    )

    for stat in workout.findall("WorkoutStatistics"):
        stat_type = stat.get("type", "")
        if stat_type not in distance_stat_types:
            continue

        val = stat.get("sum")
        unit = (stat.get("unit") or "").lower()
        if not val:
            continue

        try:
            distance = float(val)
        except ValueError:
            continue

        if unit in ("km", "kilometers"):
            return distance * 1000
        if unit in ("mi", "mile", "miles"):
            return distance * 1609.344
        if unit in ("m", "meter", "meters"):
            return distance
        if unit in ("yd", "yard", "yards"):
            return distance * 0.9144
        if unit in ("ft", "foot", "feet"):
            return distance * 0.3048

    return None


def import_apple_health_workouts(
    settings: Settings,
    *,
    file_name: str,
    file_bytes: bytes,
) -> dict:
    if file_name.lower().endswith(".zip"):
        try:
            zip_file = zipfile.ZipFile(io.BytesIO(file_bytes))
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid ZIP file") from exc
        xml_names = [name for name in zip_file.namelist() if name.lower().endswith("export.xml")]
        if not xml_names:
            raise ValueError("No export.xml found in ZIP")
        xml_bytes = zip_file.read(xml_names[0])
    elif file_name.lower().endswith(".xml"):
        xml_bytes = file_bytes
    else:
        raise ValueError("File must be a .zip or .xml Apple Health export")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    imported = 0
    skipped = 0
    error_details: list[dict[str, str]] = []

    with get_connection(settings) as conn:
        latest_start_by_source: dict[str | None, datetime | None] = {}
        for workout in root.iter("Workout"):
            raw_type = workout.get("workoutActivityType", "")
            start_str = workout.get("startDate")
            end_str = workout.get("endDate")
            source_name = workout.get("sourceName")

            if not start_str or not end_str:
                error_details.append({"workout": raw_type, "error": "Missing start/end date"})
                continue

            try:
                start_dt = _parse_apple_health_date(start_str)
                end_dt = _parse_apple_health_date(end_str)
            except ValueError as exc:
                error_details.append({"workout": raw_type, "error": f"Date parse error: {exc}"})
                continue

            cache_key = source_name or None
            if cache_key not in latest_start_by_source:
                latest_start_by_source[cache_key] = fetch_latest_apple_health_workout_start_time(
                    conn,
                    cache_key,
                )

            latest_start = latest_start_by_source[cache_key]
            if latest_start is not None and start_dt <= latest_start:
                skipped += 1
                continue

            activity_type = APPLE_HEALTH_WORKOUT_MAP.get(raw_type)

            duration_seconds = None
            raw_duration = workout.get("duration")
            if raw_duration:
                try:
                    duration_seconds = round(float(raw_duration) * 60)
                except ValueError:
                    pass

            distance_meters = None
            raw_dist = workout.get("totalDistance")
            dist_unit = (workout.get("totalDistanceUnit") or "").lower()
            if raw_dist:
                try:
                    distance = float(raw_dist)
                    if dist_unit in ("km", "kilometers"):
                        distance_meters = distance * 1000
                    elif dist_unit in ("mi", "miles"):
                        distance_meters = distance * 1609.344
                    else:
                        distance_meters = distance
                except ValueError:
                    pass

            # Some Apple exports omit totalDistance attributes and only include distance in WorkoutStatistics.
            if distance_meters is None:
                distance_meters = _distance_meters_from_workout_statistics(workout)

            calories_burned = None
            raw_cal = workout.get("totalEnergyBurned")
            if raw_cal:
                try:
                    calories_burned = float(raw_cal)
                except ValueError:
                    pass

            device = _clean_device_name(workout.get("device"))

            avg_hr = None
            elevation_ascended_meters = None
            for stat in workout.findall("WorkoutStatistics"):
                stat_type = stat.get("type", "")
                if stat_type == "HKQuantityTypeIdentifierHeartRate":
                    val = stat.get("average")
                    if val:
                        try:
                            avg_hr = round(float(val))
                        except ValueError:
                            pass
                elif stat_type == "HKQuantityTypeIdentifierElevationAscended":
                    val = stat.get("sum")
                    unit = (stat.get("unit") or "").lower()
                    if val:
                        try:
                            elev = float(val)
                            if unit in ("ft", "feet"):
                                elev *= 0.3048
                            elevation_ascended_meters = elev
                        except ValueError:
                            pass

            avg_pace_sec_per_km = None
            if duration_seconds and distance_meters and distance_meters > 0:
                avg_pace_sec_per_km = duration_seconds / (distance_meters / 1000.0)

            inserted = upsert_apple_health_workout(
                conn,
                source_name=source_name,
                device=device,
                start_time=start_dt,
                end_time=end_dt,
                workout_type=raw_type,
                activity_type=activity_type,
                duration_seconds=duration_seconds,
                distance_meters=distance_meters,
                avg_hr=avg_hr,
                avg_pace_sec_per_km=avg_pace_sec_per_km,
                elevation_ascended_meters=elevation_ascended_meters,
                calories_burned=calories_burned,
            )
            if inserted:
                imported += 1
            else:
                skipped += 1

        conn.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": len(error_details),
        "error_details": error_details,
    }


def remove_glucose_entry(settings: Settings, timestamp: datetime) -> dict | None:
    return db_delete_glucose_reading(settings, timestamp)


def remove_apple_health_workout(settings: Settings, workout_id: int) -> dict | None:
    return db_delete_apple_health_workout(settings, workout_id)
