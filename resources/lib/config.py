# -*- coding: utf-8 -*-
"""Static FIAWEC+/Staylive configuration and season metadata.

Internal refactor module: intentionally contains data only.
"""

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0"


TEST_SLUG = "s-4-hours-of-imola-2026-race-en-elms-18z65i"


PLATFORM_UID = "platform_MaZLpcxHYO6C"


OAUTH_CLIENT_ID = "eX30xifPGKGmuNmO3FPU0ZpAXvJyBemJ"


OAUTH_AUTHORIZE_URL = "https://auth.staylive.io/authorize"


OAUTH_TOKEN_URL = "https://auth.staylive.io/oauth/token"


OAUTH_REDIRECT_URI = "https://plus.fiawec.com"


OAUTH_SCOPE = "openid profile email offline_access"


OAUTH_AUDIENCE = "api.staylive.tv"


OAUTH_ORGANIZATION = "org_Dr1AhIfBitEoqGeN"


AUTH0_CLIENT_INFO = "eyJuYW1lIjoiYXV0aDAtcmVhY3QiLCJ2ZXJzaW9uIjoiMi4zLjAifQ=="


ELMS_2026_WEEKENDS = {
    "barcelona": "10.04.2026 – 12.04.2026",
    "le castellet": "01.05.2026 – 03.05.2026",
    "imola": "03.07.2026 – 05.07.2026",
    "spa-francorchamps": "21.08.2026 – 23.08.2026",
    "silverstone": "11.09.2026 – 13.09.2026",
    "portimão": "08.10.2026 – 10.10.2026",
    "portimao": "08.10.2026 – 10.10.2026",
}


ELMS_2025_WEEKENDS = {
    "barcelona": "04.04.2025 – 06.04.2025",
    "le castellet": "02.05.2025 – 04.05.2025",
    "imola": "04.07.2025 – 06.07.2025",
    "spa-francorchamps": "22.08.2025 – 24.08.2025",
    "silverstone": "12.09.2025 – 14.09.2025",
    "portimão": "17.10.2025 – 19.10.2025",
    "portimao": "17.10.2025 – 19.10.2025",
}


ELMS_2024_WEEKENDS = {
    "barcelona": "12.04.2024 – 14.04.2024",
    "le castellet": "03.05.2024 – 05.05.2024",
    "imola": "05.07.2024 – 07.07.2024",
    "spa-francorchamps": "23.08.2024 – 25.08.2024",
    "mugello": "27.09.2024 – 29.09.2024",
    "portimão": "17.10.2024 – 19.10.2024",
    "portimao": "17.10.2024 – 19.10.2024",
}


ELMS_SEASON_PAGES = {
    "2026": "european-le-mans-series",
    "2025": "european-le-mans-series-2025",
    "2024": "european-le-mans-series-2024",
}


MLMC_SEASON_PAGES = {
    "2026": "michelin-le-mans-cup",
    "2025": "michelin-le-mans-cup-2025",
    "2024": "michelin-le-mans-cup-2024",
}


MLMC_2025_WEEKENDS = {
    "barcelona": "04.04.2025 – 05.04.2025",
    "le castellet": "02.05.2025 – 03.05.2025",
    "road to le mans": "12.06.2025 – 14.06.2025",
    "spa-francorchamps": "22.08.2025 – 23.08.2025",
    "silverstone": "12.09.2025 – 13.09.2025",
    "portimão": "17.10.2025 – 18.10.2025",
    "portimao": "17.10.2025 – 18.10.2025",
}


MLMC_2024_WEEKENDS = {
    "barcelona": "12.04.2024 – 13.04.2024",
    "le castellet": "03.05.2024 – 04.05.2024",
    "road to le mans": "13.06.2024 – 15.06.2024",
    "spa-francorchamps": "23.08.2024 – 24.08.2024",
    "mugello": "27.09.2024 – 28.09.2024",
    "portimão": "18.10.2024 – 19.10.2024",
    "portimao": "18.10.2024 – 19.10.2024",
}


MLMC_2026_WEEKENDS = {
    "barcelona": "10.04.2026 – 11.04.2026",
    "le castellet": "01.05.2026 – 02.05.2026",
    "road to le mans": "10.06.2026 – 12.06.2026",
    "spa-francorchamps": "21.08.2026 – 22.08.2026",
    "silverstone": "11.09.2026 – 12.09.2026",
    "portimão": "08.10.2026 – 10.10.2026",
    "portimao": "08.10.2026 – 10.10.2026",
}


WEC_SEASON_SCHEDULES = {
    "2026": [
        {"path": "race/6-hours-of-imola", "label": "6 Hours of Imola", "date": "2026-04-17", "date_label": "17.04.2026 – 19.04.2026"},
        {"path": "race/totalenergies-6-hours-of-spa-francorchamps", "label": "TotalEnergies 6 Hours of Spa-Francorchamps", "date": "2026-05-07", "date_label": "07.05.2026 – 09.05.2026"},
        {"path": "race/24-hours-of-le-mans", "label": "24 Hours of Le Mans", "date": "2026-06-10", "date_label": "10.06.2026 – 14.06.2026"},
        {"path": "race/rolex-6-hours-of-sao-paulo", "label": "Rolex 6 Hours of São Paulo", "date": "2026-07-10", "date_label": "10.07.2026 – 12.07.2026"},
        {"path": "race/lone-star-le-mans", "label": "Lone Star Le Mans", "date": "2026-09-04", "date_label": "04.09.2026 – 06.09.2026"},
        {"path": "race/6-hours-of-fuji", "label": "6 Hours of Fuji", "date": "2026-09-25", "date_label": "25.09.2026 – 27.09.2026"},
        # 6 Hours of Barcelona remains intentionally hidden.
        {"path": "race/6-hours-of-monza", "label": "6 Hours of Monza", "date": "2026-11-06", "date_label": "06.11.2026 – 08.11.2026"},
    ],
    "2025": [
        {"path": "race/6-hours-of-imola", "label": "6 Hours of Imola", "date": "2025-04-20", "date_label": "18.04.2025 – 20.04.2025"},
        {"path": "race/totalenergies-6-hours-of-spa-francorchamps", "label": "TotalEnergies 6 Hours of Spa-Francorchamps", "date": "2025-05-10", "date_label": "08.05.2025 – 10.05.2025"},
        {"path": "race/24-hours-of-le-mans", "label": "24 Hours of Le Mans", "date": "2025-06-14", "date_label": "11.06.2025 – 15.06.2025"},
        {"path": "race/rolex-6-hours-of-sao-paulo", "label": "Rolex 6 Hours of São Paulo", "date": "2025-07-13", "date_label": "11.07.2025 – 13.07.2025"},
        {"path": "race/lone-star-le-mans", "label": "Lone Star Le Mans", "date": "2025-09-07", "date_label": "05.09.2025 – 07.09.2025"},
        {"path": "race/6-hours-of-fuji", "label": "6 Hours of Fuji", "date": "2025-09-28", "date_label": "26.09.2025 – 28.09.2025"},
    ],
    "2024": [
        {"path": "race/6-hours-of-imola", "label": "6 Hours of Imola", "date": "2024-04-21", "date_label": "19.04.2024 – 21.04.2024"},
        {"path": "race/totalenergies-6-hours-of-spa-francorchamps", "label": "TotalEnergies 6 Hours of Spa-Francorchamps", "date": "2024-05-11", "date_label": "09.05.2024 – 11.05.2024"},
        {"path": "race/24-hours-of-le-mans", "label": "24 Hours of Le Mans", "date": "2024-06-15", "date_label": "12.06.2024 – 16.06.2024"},
        {"path": "race/rolex-6-hours-of-sao-paulo", "label": "Rolex 6 Hours of São Paulo", "date": "2024-07-14", "date_label": "12.07.2024 – 14.07.2024"},
        {"path": "race/lone-star-le-mans", "label": "Lone Star Le Mans", "date": "2024-09-01", "date_label": "30.08.2024 – 01.09.2024"},
        {"path": "race/6-hours-of-fuji", "label": "6 Hours of Fuji", "date": "2024-09-15", "date_label": "13.09.2024 – 15.09.2024"},
    ],
    "2023": [
        {"path": "race/totalenergies-6-hours-of-spa-francorchamps", "label": "TotalEnergies 6 Hours of Spa-Francorchamps", "date": "2023-04-29", "date_label": "27.04.2023 – 29.04.2023"},
        {"path": "race/24-hours-of-le-mans", "label": "24 Hours of Le Mans", "date": "2023-06-10", "date_label": "07.06.2023 – 11.06.2023"},
        {"path": "race/6-hours-of-monza", "label": "6 Hours of Monza", "date": "2023-07-09", "date_label": "07.07.2023 – 09.07.2023"},
        {"path": "race/6-hours-of-fuji", "label": "6 Hours of Fuji", "date": "2023-09-10", "date_label": "08.09.2023 – 10.09.2023"},
    ],
}

