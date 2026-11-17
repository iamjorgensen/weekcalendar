# Copy this to the frame as "secrets.py" (Thonny: File -> Save as -> the Pico on the frame)
# and fill in your values. Never commit the real secrets.py.

WIFI_SSID = "your-wifi-name"
WIFI_PASSWORD = "your-wifi-password"

# The image address: FunctionUrl from the AWS stack + your FRAME_TOKEN.
CALENDAR_URL = "https://<id>.lambda-url.eu-west-1.on.aws/image.png?token=<FRAME_TOKEN>&fresh=1"
PRE_TRIGGER_URL = ""

# Local Oslo times the frame wakes up by itself (buttons also wake it).
# After 17:00 the calendar shows tomorrow ("I morgen"), so an evening refresh is useful.
UPDATE_TIMES = ["04:00", "17:30"]
