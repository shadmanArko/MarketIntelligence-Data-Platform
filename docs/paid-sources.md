# Sources that need a key, an account, payment or your decision

Everything else in the platform runs on free, open sources. Each item below is wired in already (or has a
slot behind the same connector interface) and switches on with a config flag or an `.env` value.

| Source | What it adds | Status | What is needed |
|---|---|---|---|
| **Instagram Graph API** (Business Discovery + Hashtag Search) | Competitor profiles, every post with likes / comments, hashtag top + recent media | Connector built (`instagram_graph`), discovery fed by 371+ Instagram handles found on restaurant sites | `META_ACCESS_TOKEN` (long-lived, `instagram_basic` + `pages_show_list`; Public Content Access for hashtags) and `META_IG_USER_ID` of Dhaka Kacchi's business account, in `.env` |
| **Uber Eats** | Stores, menus, prices, fees | Not built: the automated-permission check blocked calling Uber's internal API with a synthetic location cookie | Your decision: allow it, or use the Apify Uber Eats actor (paid) behind the same interface |
| **Google organic rankings** | Who ranks for "biryani berlin" in web search | Connector built (`serp` organic); free HTML scraping of search engines is not attempted (bot challenges) | Free tier: `GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX` (100 queries/day) or `BRAVE_API_KEY`; paid: DataForSEO (~$0.0006 / page) |
| **Keyword search volume** | Monthly demand per keyword, seasonality | Not available free (Trends API is gated alpha, pytrends archived) | DataForSEO keyword volume (paid) or Google Trends API alpha access |
| **Foursquare OS Places** | A third master-list seed + category tree | Loader slot ready | `HF_TOKEN` with access granted to `foursquare/fsq-os-places` on Hugging Face |
| **TripAdvisor European Restaurants (Kaggle, 2021)** | 2021 baseline: survival, rating change | Loader slot ready | Kaggle API token (`~/.kaggle/kaggle.json`) |
| **Yelp Open Dataset** | Pretraining reviews / photos | Not downloaded (licence click-through) | Accept the Yelp dataset licence and download; the loader registers it |
| **Souslab menus, Food-101** (Hugging Face) | Pretraining for menu-item and dish-image models | Not downloaded (large, pretraining only) | Say go; Souslab needs HF access approval |
| **Google Places API** | Official details for places the free sweep misses | Disabled (`google_places.enabled: false`) | API key with billing; free monthly caps per SKU |
| **Apify / xpoz** | Paid fallback for any free connector that breaks | Interface slot (`apify.enabled: false`) | `APIFY_TOKEN` and a budget |
| **Instaloader** (secondary Instagram) | Personal accounts, comments, carousels | Disabled per the plan | A separate, non-business Instagram login |
| **Residential proxies** | Only if a source starts blocking the home IP | Not used | Only if needed |
| **Dhaka Kacchi first-party** (Search Console, Business Profile, orders DB) | Ground truth for every estimate | Deferred, as agreed | Access via `dhaka-kacchi-connect` / `dhaka_kacchi_ai_harness` later |
