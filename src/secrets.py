# Secrets!

## Wifi Network
WIFI_NETWORK = "os2025-badge"
WIFI_PASS    = "mV*M66s8TkY!rYcnDpVY"

## Registration
HOST_ADDRESS = 'https://badger.becomingahacker.com/'

## Webex (used by apps/webex_meetings)
# Meetings API only accepts a personal access token or an OAuth
# integration/service-app token with the meeting:schedules_read scope --
# bot tokens have no meetings scope at all and always get a 401 here.
# Get one at https://developer.webex.com/docs/getting-your-personal-access-token
# (12h, fine for testing) or https://developer.webex.com/my-apps for a
# longer-lived integration token.
WEBEX_TOKEN = "YOUR_WEBEX_TOKEN"
# IANA zone name; Webex returns UTC if unset. IST = Asia/Kolkata (no DST).
# WEBEX_TIMEZONE = "Asia/Kolkata"