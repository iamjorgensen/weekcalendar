# 📅 AI-Enhanced Inky Frame Dashboard

A high-fidelity, intelligent calendar and weather dashboard designed for the **Pimoroni Inky Frame (7.3")**. This system features an automated asset pipeline and semantic AI event mapping to provide a beautiful, low-maintenance home overview.



## 🚀 Unique Features

* **Semantic AI Icon Mapping**: Uses OpenAI (GPT-4o-mini) to interpret event meanings. Even without a manual mapping, the system understands that "Middag med naboen" (Norwegian) should display a `utensils` icon.
* **Ultra-Crisp SVG Rendering**: Utilizes a specialized `resvg-py` integration to render Lucide icons as high-quality vectors, ensuring zero pixelation on the E-Ink display.
* **Dynamic Asset Pipeline**: Automatically fetches missing icons from the Lucide CDN via `unpkg.com`, caches them locally, and converts them to the correct format for the Inky Frame.
* **Norwegian Localization**: Custom handlers for Norwegian public holidays, MET Norway weather data, and Movar "Tommekalender" (waste collection) integration.
* **Remote Webhook Updates**: A Flask-based listener allows for triggering a `git pull` and service restart via a simple `curl` command.

---

## 🛠 Tech Stack

* **Display**: Inky Frame 7.3" (Pimoroni)
* **Language**: Python 3.x
* **Core Libraries**: 
    * `Pillow` (Image composition)
    * `resvg-py` (Fast, high-quality SVG rendering)
    * `OpenAI` (Semantic event analysis)
    * `Requests` (API communication)
    * `Flask` (Remote trigger webhook)
