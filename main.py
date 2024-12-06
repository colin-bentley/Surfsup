import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from twilio.rest import Client
from config import (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, WHATSAPP_TO_NUMBER, STORMGLASS_API_KEY, EMAIL_ADDRESS, EMAIL_PASSWORD)
from astral import LocationInfo
from astral.sun import sun

# Configuration
WAVE_HEIGHT_THRESHOLD = 1.2
TIDE_WINDOW_HOURS = 2

# Killiney Beach location info
KILLINEY = LocationInfo(
    name="Killiney Beach",
    region="Ireland",
    timezone="Europe/Dublin",
    latitude=53.2557,
    longitude=-6.1124
)

# Killiney Beach coordinates for API
params = {
    'lat': KILLINEY.latitude,
    'lng': KILLINEY.longitude,
    'params': 'waveHeight',
    'start': datetime.now().isoformat(),
    'end': (datetime.now() + timedelta(days=2)).isoformat()
}

def is_daylight(check_time):
    """Check if time is during daylight hours based on actual sunrise/sunset"""
    time = datetime.strptime(check_time, '%Y-%m-%dT%H:%M:%S+00:00')
    s = sun(KILLINEY.observer, date=time.date())

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
                if (current - previous).total_seconds() <= 7200:
                    current_group.append(conditions[i])
                else:
                    # Format the time range using the new format
                    time_range = format_time_range(
                        current_group[0]['time'],
                        current_group[-1]['time']
                    )
                    grouped.append({
                        'time': time_range,
                        'wave_height': f"{min(float(c['wave_height']) for c in current_group):.1f}-{max(float(c['wave_height']) for c in current_group):.1f}m",
                        'low_tide_time': current_group[0]['low_tide_time']
                    })
                    current_group = [conditions[i]]
            # Add the last group
            time_range = format_time_range(
                current_group[0]['time'],
                current_group[-1]['time']
            )
            grouped.append({
                'time': time_range,
                'wave_height': f"{min(float(c['wave_height']) for c in current_group):.1f}-{max(float(c['wave_height']) for c in current_group):.1f}m",
                'low_tide_time': current_group[0]['low_tide_time']
            })
            return grouped

def get_wave_data():
    url = 'https://api.stormglass.io/v2/weather/point'
    headers = {'Authorization': STORMGLASS_API_KEY}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        print(f"Wave API Status Code: {response.status_code}")
        return response.json()
    except requests.Timeout:
        print("Wave API request timed out")
        return None
    except Exception as e:
        print(f"Error getting wave data: {e}")
        return None

def get_tide_data():
    url = 'https://api.stormglass.io/v2/tide/extremes/point'
    tide_params = {
        'lat': KILLINEY.latitude,
        'lng': KILLINEY.longitude,
        'start': datetime.now().isoformat(),
        'end': (datetime.now() + timedelta(days=2)).isoformat()
    }
    headers = {'Authorization': STORMGLASS_API_KEY}
    try:
        response = requests.get(url, params=tide_params, headers=headers, timeout=10)
        print(f"Tide API Status Code: {response.status_code}")
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

def send_email(good_conditions):
    message_text = "🏄 Surf Alert - Killiney Beach!\n\n"

    for condition in good_conditions:
        message_text += f"{condition['time']}\n"
        message_text += f"Wave Height: {condition['wave_height']}\n"
        message_text += f"Low Tide at: {condition['low_tide_time']}\n\n"

    msg = MIMEText(message_text)
    msg['Subject'] = '🏄 Surf Alert - Killiney Beach'
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = EMAIL_ADDRESS

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
        message_text += f"Wave Height: {condition['wave_height']}\n"
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
    wave_data = get_wave_data()
    if not wave_data:
        print("Failed to get wave data")
        return False  # Add return value

    print("Wave data received")
    tide_data = get_tide_data()
    if not tide_data:
        print("Failed to get tide data")
        return False  # Add return value

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

                if wave_height >= WAVE_HEIGHT_THRESHOLD and is_daylight(hour['time']):
                    near_low_tide, tide_time = is_near_low_tide(hour['time'], tide_data)

                    if near_low_tide:
                        time = datetime.strptime(hour['time'], '%Y-%m-%dT%H:%M:%S+00:00')
                        good_conditions.append({
                            'time': time.strftime('%Y-%m-%d %H:%M'),
                            'wave_height': round(wave_height, 1),
                            'low_tide_time': tide_time.strftime('%H:%M')
                        })
                        processed_times.add(hour['time'])

        if good_conditions:
            print(f"Found {len(good_conditions)} good conditions during daylight hours")
            grouped_conditions = group_consecutive_times(good_conditions)
            send_email(grouped_conditions)
            send_whatsapp(grouped_conditions)
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