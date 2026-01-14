# 📅 AI-Enhanced Inky Frame Dashboard

A high-fidelity, intelligent calendar designed for the **Pimoroni Inky Frame (7.3")**. This system features an automated asset pipeline and semantic AI event mapping to provide a functional, low-maintenance home overview for the whole family



## 🚀 Features
* **Data consolidation**: Consolidates date from Google family calendar, public holidays, renovation ("Movar") and weather data ("yr.no") into one simple view showing as many days forward as possible (depending on how eventful the days are)
* **Light weight + server**: The frame itself only renders the data and a small rapberry pi server acts as the "brain" doing all the work producing the image. Frame wakes up ones (can be set to more) a day in the morning and updates doing a api call to the server, then renders the new image.
* **Event Mapping**: Event mapping to replace or add icons and tags. E.g. if "Christian" is in the calendar event the event is tagged with a "C" in a color so it is easy to see who it relates to. One event can be tagged with multiple persons.
* **Semantic AI Icon Mapping**: Uses OpenAI (GPT-4o-mini) to interpret event meanings. Even without a manual mapping, the system understands that "Middag med naboen" (Norwegian) should display a `utensils` icon.
* **Dynamic Asset Pipeline**: Automatically fetches missing icons from the Lucide CDN via `unpkg.com`, caches them locally, and converts them to the correct format for the Inky Frame.

## 🛠 Tech Stack

* **Display**: Inky Frame 7.3" (Pimoroni)
* **Language**: Python 3.x
* **Server**: Raspberry Pi 2W
* **Core Libraries**: 
    * `Pillow` (Image composition)
    * `resvg-py` (Fast, high-quality SVG rendering)
    * `OpenAI` (Semantic event analysis)
    * `Requests` (API communication)
    * `Flask` (Remote trigger webhook)
