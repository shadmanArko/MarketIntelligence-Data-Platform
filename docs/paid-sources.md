# Sources that need a key, an account, payment or your decision

Everything else in the platform runs on free, open sources. Each item below is wired in already (or has a
slot behind the same connector interface) and switches on with a config flag or an `.env` value.

| Source | What it adds | Status | What is needed |
|---|---|---|---|
| **Instagram Graph API** (Business Discovery + Hashtag Search) | Competitor profiles, every post with likes / comments, hashtag top + recent media | Token set (never expires); 4,733 accounts queued | Meta App Review: Advanced Access for `instagram_basic` + `pages_read_engagement` (+ Public Content Access for hashtags) |
| **Uber Eats** | One-time store list: names, cuisines, ratings, price level, address | Connector built (`uber_eats`, via Apify, $10 cap); direct access is behind a bot challenge | `APIFY_TOKEN` (≈ $9 one time) |
| **Google organic rankings** | Who ranks for "biryani berlin" in web search | Connector built (`serp` organic); free HTML scraping of search engines is not attempted (bot challenges) | Free tier: `GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX` (100 queries/day) or `BRAVE_API_KEY`; paid: DataForSEO (~$0.0006 / page) |
| **Keyword search volume** | Monthly demand per keyword, seasonality | Not available free (Trends API is gated alpha, pytrends archived) | DataForSEO keyword volume (paid) or Google Trends API alpha access |
| **Foursquare OS Places** | A third master-list seed + category tree | ✅ loaded (2026-09-15, 48k Berlin food places) | done |
| **TripAdvisor European Restaurants (Kaggle, 2021)** | 2021 baseline: survival, rating change | ✅ loaded (7,559 Berlin restaurants) | done |
| **Yelp Open Dataset** | Pretraining reviews / photos | Not downloaded (licence click-through) | Accept the Yelp dataset licence and download; the loader registers it |
| **Souslab menus, Food-101** (Hugging Face) | Pretraining for menu-item and dish-image models | Not downloaded (large, pretraining only) | Say go; Souslab needs HF access approval |
| **Google Places API** | Official details for places the free sweep misses | Disabled (`google_places.enabled: false`) | API key with billing; free monthly caps per SKU |
| **Apify / xpoz** | Paid fallback for any free connector that breaks | Interface slot (`apify.enabled: false`) | `APIFY_TOKEN` and a budget |
| **Instaloader** (secondary Instagram) | Personal accounts, comments, carousels | Disabled per the plan | A separate, non-business Instagram login |
| **Residential proxies** | Only if a source starts blocking the home IP | Not used | Only if needed |
| **YouTube Data API** | Videos, Shorts, channels, comment language mix for 229 food / community / occasion queries | Connector built (`youtube`), waits for the key | Free `YOUTUBE_API_KEY` (credentials guide §6) |
| **X (Twitter) API** | Recent / full-archive post search with likes, reposts, impressions | Not built; no free read tier since 2026-02 | Pay per use: $0.005 per post read (10k posts ≈ $50) |
| **Meta Ad Library API** | All EU ads with reach by age / gender / region (competitor + food-delivery advertising) | Not built yet | ID confirmation (free) |
| **TikTok Commercial Content API** | All TikTok ads in the EU | Not built yet | Application (free) |
| **Threads keyword search** | Public Threads posts by keyword / topic | Not built yet | Meta App Review (free) |
| **TikTok Research API, Meta Content Library** | Full public TikTok / Meta content | Not possible | Academic / non-profit researchers only |
| **LinkedIn content** | Other companies' posts | Not possible | No public API; own page analytics only |
| **Dhaka Kacchi first-party** (Search Console, Business Profile, orders DB) | Ground truth for every estimate | Deferred, as agreed | Access via `dhaka-kacchi-connect` / `dhaka_kacchi_ai_harness` later |
