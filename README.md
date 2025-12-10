# Family E-Ink Calendar Display

![WeekCalendar Preview](output.jpg)

This project is designed to create a family-friendly weekly calendar display on a 7.3" Inky frame e-ink 6 color screen from  Pimoroni (https://shop.pimoroni.com/products/inky-impression-7-3?variant=55186435244411). The calendar aggregates events from multiple sources—like your shared family Google Calendar, Norwegian public holidays, local renovation schedules, and even weather data—and displays them in a visually intuitive format. Since the Inky Frame processing is very lightweight the screen can refresh for a long time on just batteries - put in a Ikea frame on a shelf in the kitchen for all to see. 

## Developer disclaimer
Note that the developer of this project is ChatGPT and some parts Gemini. I have only been advising and instructing the ai-models on the way to the final solution. Hence going into details there are probably parts of this code way too complicated - there are "fallback" code snippets around that could have been removed +++ I am sure a skilled developer could have done the same with 50% of the code :)
## Data Sources

- **Google Calendar**: Pulls in all family events.
- **Norwegian Public Holidays**: Adds local holidays so everyone knows when there's a day off.
- **Weather Data**: Integrates with Norwegian weather services to show the forecast for the week.
- **Renovation Schedule (Movar)**: Displays which type of waste collection happens on which days.
- **Google Sheet Mapping**: A mapping sheet that lets you turn event titles into icons or specific tags for each family member.

## Hardware Setup

- **Inky Frame 7.3"**: Runs MicroPython, wakes up every 12 hours to refresh the display.
- **Raspberry Pi Server**: Does all the heavy lifting, like fetching data, rendering the calendar image, and serving it to the Inky frame. The Pi also has a small screen for local monitoring.

## How It Works

The Inky frame wakes up, makes an API call to the Raspberry Pi to get the latest calendar image, and displays it. Icons and tags are automatically replaced based on your Google Sheet mappings, making it super easy for everyone in the family to see what’s going on at a glance.

## Python Scripts Overview (main components)

- **main.py**: This is the entry point for the Inky frame. It handles waking up the device, calling the Raspberry Pi server’s API to fetch the latest calendar image, and then displaying that image on the e-ink screen. Essentially, it’s the lightweight script that runs on the Inky side and just focuses on displaying the final product.
- **data_provider.py**: This script is the workhorse on the Raspberry Pi server. It fetches and normalizes data from all the different sources: Google Calendar events, public holidays, weather forecasts, and the renovation schedule. It also handles looking up event mappings from your Google Sheet to convert event titles into icons or tags.
- **render_calendar.py**: Once the data is gathered and normalized, this script handles generating the actual calendar image. It uses a graphics library, like Pillow, to draw the weekly calendar, lay out the icons, and format everything into a final image that the Inky frame can display.
- **server.py**: This is the script that runs a lightweight web server on the Raspberry Pi. It provides an API endpoint that the Inky frame can call to request the latest calendar image, and it triggers the rendering process whenever a refresh is needed.

## The Event mappings
This is a crucial part of the setup and enables me to on the fly add new mappings if there are new events that I would like to tag or present a nice icpn to 
![Event mappings](/readme_supportfiles/example_inkyframe_event_mappings.jpg)

Some modes have been created
- **replace_icon**: This takes the whole keyword from my calendar event title, removes it, and replaces it with the icon. If the calendar event title after replacements are empty - it will not show at all. An example - I have adaily  recurring "dinner: --> Middag:" tag in my google calendar. If I go in an edit a day changing it to "Middag: Pasta Carbonara" - the code will replace "Middag:" with a food icon and only show "Pasta Carbonara"
- **replace_text**: Replaces the text in the keyword with a colored tag.
- **replace_all**: Replaces the text AND adds an icon, 
- **add_all**: Leaves the text untouched and adds both the icon and the tag. Tag can be colored as the inkyframe supports 6 different colors.
- **add_icon**: Leaves the text untouched and adds the icon
- **add_text**: Leaves the text untouched and adds the text as a colored tag

Combinations of these mappings will also work - apart from Icon - here it will choose the first icon it finds in the mapping table. So an example from my output.jpg - in Google calendar I have an event "Oslo - Tom Waitz Christian". The code is adding the "city" icon based on "Oslo" being in the title - in addition it replaces "Christian" and puts a black "C" tag on it to show who this event is concerning...pretty neat :) 

## On the shelf
![Shelf1](/readme_supportfiles/ontheshelf1.jpg)
![Shelf2](/readme_supportfiles/ontheshelf2.jpg)

