import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from twilio.rest import Client
from config import (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, WHATSAPP_TO_NUMBER, STORMGLASS_API_KEY, EMAIL_ADDRESS, EMAIL_PASSWORD)
from astral import LocationInfo
from astral.sun import sun

# Configuration
WAVE_HEIGHT_THRESHOLD = 1.0
TIDE_WINDOW_HOURS = 2

class SurfLocation:
    def __init__(self, name, region, timezone, latitude, longitude):
        self.info = LocationInfo(name=name, region=region, timezone=timezone, 
                               latitude=latitude, longitude=longitude)
        self.params = {
            'lat': latitude,
            'lng': longitude,
            'params': 'waveHeight,windDirection,windSpeed',
            'start': datetime.now().isoformat(),
            'end': (datetime.now() + timedelta(days=5)).isoformat()
        }

# Define locations
LOCATIONS = [
    SurfLocation(
        name="Killiney Beach",
        region="Ireland",
        timezone="Europe/Dublin",
        latitude=53.2557,
        longitude=-6.1124
    ),
]

def degrees_to_cardinal(degrees):
    """Convert degrees to cardinal directions"""
    directions = [
        "N", "NNE", "NE", "ENE", 
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", 
        "W", "WNW", "NW", "NNW"
    ]
    # Divide the degrees by 22.5 (360/16) to get the index
    index = int((degrees + 11.25) % 360 // 22.5)
    return directions[index]

def is_daylight(check_time, location):
    """Check if time is during daylight hours based on actual sunrise/sunset"""
    time = datetime.strptime(check_time, '%Y-%m-%dT%H:%M:%S+00:00')
    
    # Use a simpler method that doesn't require elevation
    s = sun(location.info.observer, date=time.date())

    # Convert time to naive datetime for comparison
    time = time.replace(tzinfo=None)
    sunrise = s['sunrise'].replace(tzinfo=None) + timedelta(minutes=30)
    sunset = s['sunset'].replace(tzinfo=None) - timedelta(minutes=30)

    return sunrise <= time <= sunset

def format_time(time_str):
    """Convert time string to a more readable format"""
    time = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
    return time.strftime('%A %d %B, %-I:%M%p').replace('AM', 'am').replace('PM', 'pm')

def format_time_range(start_time_str, end_time_str):
    """Convert time range to a more readable format"""
    start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M')
    end_time = datetime.strptime(end_time_str, '%Y-%m-%d %H:%M')

    # Format: "Tuesday 11:00-13:00"
    return f"{start_time.strftime('%A %H:%M')}-{end_time.strftime('%H:%M')}"

def group_consecutive_times(conditions):
    if not conditions:
        return []
    grouped = []
    current_group = [conditions[0]]
    for i in range(1, len(conditions)):
        current = datetime.strptime(conditions[i]['time'], '%Y-%m-%d %H:%M')
        previous = datetime.strptime(current_group[-1]['time'], '%Y-%m-%d %H:%M')
        if (current - previous).total_seconds() <= 3600:  # Group within 1 hour
            current_group.append(conditions[i])
        else:
            # Use the actual last time in the group plus one hour
            last_time = datetime.strptime(current_group[-1]['time'], '%Y-%m-%d %H:%M')
            time_range = format_time_range(
                current_group[0]['time'],
                current_group[-1]['time']
            )
            grouped.append({
                'time': time_range,
                'wave_height': f"{min(float(c['wave_height']) for c in current_group):.1f}-{max(float(c['wave_height']) for c in current_group):.1f}m",
                'windSpeed': f"{round(min(float(c['windSpeed']) * 3.6 for c in current_group))}-{round(max(float(c['windSpeed']) * 3.6 for c in current_group))}kph",
                'windDirection': degrees_to_cardinal(float(current_group[0]['windDirection'])),
                'low_tide_time': current_group[0]['low_tide_time']
            })
            current_group = [conditions[i]]

    # Add the last group if not empty
    if current_group:
        time_range = format_time_range(
            current_group[0]['time'],
            current_group[-1]['time']
        )
        grouped.append({
        'time': time_range,
        'wave_height': f"{min(float(c['wave_height']) for c in current_group):.1f}-{max(float(c['wave_height']) for c in current_group):.1f}m",
        'windSpeed': f"{round(min(float(c['windSpeed']) * 3.6 for c in current_group))}-{round(max(float(c['windSpeed']) * 3.6 for c in current_group))}kph",
         'windDirection': degrees_to_cardinal(float(current_group[0]['windDirection'])),
        'low_tide_time': current_group[0]['low_tide_time']
    })
    return grouped

def get_wave_data(location):
    url = 'https://api.stormglass.io/v2/weather/point'
    headers = {'Authorization': STORMGLASS_API_KEY}
    try:
        response = requests.get(url, params=location.params, headers=headers, timeout=10)
        print(f"Wave API Status Code: {response.status_code}")
        data = response.json()
        print("\nRaw API Response:")
        print(data)
        return data
    except requests.Timeout:
        print("Wave API request timed out")
        return None
    except Exception as e:
        print(f"Error getting wave data: {e}")
        return None

def get_tide_data(location):
    url = 'https://api.stormglass.io/v2/tide/extremes/point'
    tide_params = {
        'lat': location.info.latitude,
        'lng': location.info.longitude,
        'start': datetime.now().isoformat(),
        'end': (datetime.now() + timedelta(days=5)).isoformat()
    }
    headers = {'Authorization': STORMGLASS_API_KEY}
    try:
        response = requests.get(url, params=tide_params, headers=headers, timeout=10)
        print(f"Tide API Status Code: {response.status_code}")
        if response.status_code == 402:
            print("Tide API quota exceeded or payment required")
            return None
        return response.json()
    except requests.Timeout:
        print("Tide API request timed out")
        return None
    except Exception as e:
        print(f"Error getting tide data: {e}")
        return None

def is_near_low_tide(check_time, tide_data):
    """Check if a given time is within 2 hours of low tide"""
    check_time = datetime.strptime(check_time, '%Y-%m-%dT%H:%M:%S+00:00')
    for tide in tide_data['data']:
        if tide['type'] == 'low':
            tide_time = datetime.strptime(tide['time'], '%Y-%m-%dT%H:%M:%S+00:00')
            time_difference = abs((tide_time - check_time).total_seconds() / 3600)
            if time_difference <= TIDE_WINDOW_HOURS:
                return True, tide_time
    return False, None

def send_email(good_conditions, location):
    message_text = f"🏄 Surf Alert - {location.info.name}!\n\n"
    for condition in good_conditions:
        message_text += f"{condition['time']}\n"
        message_text += f"Wave Height: {condition['wave_height']}m\n"
        message_text += f"Wind: {condition['windSpeed']} from {condition['windDirection']}\n"
        message_text += f"Low Tide at: {condition['low_tide_time']}\n\n"
        message_text += "https://www.windguru.cz/47766/\n\n"
    msg = MIMEText(message_text)
    msg['Subject'] = '🏄 Surf Alert - Killiney Beach'
    msg['From'] = EMAIL_ADDRESS
    recipients = [EMAIL_ADDRESS, ADDITIONAL_EMAIL]
    msg['To'] = ', '.join(recipients)

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Email notification sent!")
    except Exception as e:
        print(f"Error sending email: {e}")

def send_whatsapp(good_conditions):
    """Send surf conditions via WhatsApp"""
    message_text = "🏄 Surf Alert - Killiney Beach!\n\n"

    for condition in good_conditions:
        message_text += f"{condition['time']}\n"
        message_text += f"Wave Height: {condition['wave_height']}m\n"
        message_text += f"Wind: {condition['windSpeed']} from {condition['windDirection']}\n"
        message_text += f"Low Tide at: {condition['low_tide_time']}\n\n"
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=message_text,
            from_=TWILIO_FROM_NUMBER,
            to=WHATSAPP_TO_NUMBER
        )
        print("WhatsApp notification sent!")
        return True
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")
        return False

def check_conditions():
    print("Starting condition check...")
    all_conditions = []
    
    for location in LOCATIONS:
        print(f"\nChecking conditions for {location.info.name}...")
        wave_data = get_wave_data(location)
        if not wave_data:
            print(f"Failed to get wave data for {location.info.name}")
            continue

    print("Wave data received")
    tide_data = get_tide_data(LOCATIONS[0])  # Using Killiney Beach location
    if not tide_data:
        print("Failed to get tide data")
        return False
    
    if 'data' not in tide_data:
        print(f"Invalid tide data response: {tide_data}")
        return False

    print("Tide data received")

    try:
        if 'hours' not in wave_data:
            print(f"Unexpected wave data format: {wave_data}")
            return False

        good_conditions = []
        processed_times = set()  # Track processed times to avoid duplicates

        for hour in wave_data['hours']:
            if hour['time'] in processed_times:
                continue

            if 'waveHeight' in hour and 'sg' in hour['waveHeight']:
                    wave_height = hour['waveHeight']['sg']
                    wind_speed = hour['windSpeed']['sg'] if 'windSpeed' in hour and 'sg' in hour['windSpeed'] else 0
                    wind_direction = hour['windDirection']['sg'] if 'windDirection' in hour and 'sg' in hour['windDirection'] else 0

                    if wave_height >= WAVE_HEIGHT_THRESHOLD and is_daylight(hour['time'], location):
                        near_low_tide, tide_time = is_near_low_tide(hour['time'], tide_data)

                        if near_low_tide:
                            time = datetime.strptime(hour['time'], '%Y-%m-%dT%H:%M:%S+00:00')
                            good_conditions.append({
                                'time': time.strftime('%Y-%m-%d %H:%M'),
                                'wave_height': round(wave_height, 1),
                                'windSpeed': round(wind_speed, 1),  # Keep in m/s, will convert in grouping
                                'windDirection': round(wind_direction),
                                'low_tide_time': tide_time.strftime('%H:%M')
                            })
                        processed_times.add(hour['time'])

        if good_conditions:
            print("Debug - First condition:", good_conditions[0])
            print(f"Found {len(good_conditions)} good conditions during daylight hours")
            grouped_conditions = group_consecutive_times(good_conditions)
            send_email(grouped_conditions, location)
            return True
        else:
            print("No ideal conditions found during daylight hours")
            return False

    except Exception as e:
        print(f"Error processing data: {e}")
        return False

if __name__ == "__main__":
    print("Starting surf checker...")
    check_conditions()
    print("Program finished")
    print('\033[?25h', end='')  # Makes cursor visible again