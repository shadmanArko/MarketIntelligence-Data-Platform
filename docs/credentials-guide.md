# Getting the keys and tokens

Put every value into the `.env` file in this folder (never into chat, email or git — `.env` is git-ignored).
After adding one, tell Claude which, and it runs the matching connector.

| Priority | Service | Cost | Unlocks | `.env` lines |
|---|---|---|---|---|
| 1 | Meta / Instagram | free | competitor Instagram profiles, every post's likes / comments, hashtags | `META_ACCESS_TOKEN`, `META_IG_USER_ID` |
| 2 | Apify | ≈ $9 one time (Starter $29 for one month) | Uber Eats store list: names, cuisines, ratings | `APIFY_TOKEN` |
| 3 | Hugging Face | free | Foursquare Open Places (a third map-data source) | `HF_TOKEN` |
| 4 | Kaggle | free | TripAdvisor 2021 baseline (which restaurants survived, rating changes) | file `~/.kaggle/kaggle.json` |
| 5 | DataForSEO (optional) | $50 deposit, ≈ $1–2 per run | Google web rankings + keyword search volume | `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` |

---

## 1. Meta / Instagram (Graph API)

**What it is for:** reading *other businesses'* public Instagram data through the official API ("Business
Discovery"), using Dhaka Kacchi's Instagram as the account that asks. It only ever **reads**.

### Before you start (check once)
1. Dhaka Kacchi's Instagram is a **Professional account** (Business or Creator).
   Instagram app → Settings → Account type and tools.
2. It is **linked to a Facebook Page** you manage. Instagram → Settings → Accounts Center → or from the
   Facebook Page → Settings → Linked accounts → Instagram.

### Steps
1. Go to **developers.facebook.com** → **My Apps** → open your existing app
   (or **Create App** → use case *Other* → type **Business**).
2. In the app, **Add product**: *Instagram* → choose **"API setup with Facebook login"**
   (the Graph API flavour; *not* "Instagram Login" / Basic Display).
3. Open **Tools → Graph API Explorer**:
   * Meta App: your app · User or Page: **Get User Access Token**
   * Tick **only these permissions**:
     | Permission | Why |
     |---|---|
     | `instagram_basic` | read Instagram profiles and media (Business Discovery) |
     | `pages_show_list` | find the Facebook Page your Instagram is linked to |
     | `pages_read_engagement` | required by Meta alongside the two above |
     | `business_management` | only if the Page lives inside a Meta Business Manager |
   * **Generate Access Token** → log in → select the Dhaka Kacchi Page and Instagram account → allow.
4. **Find the Instagram user id**: in the Explorer run
   `me/accounts?fields=name,instagram_business_account`
   → copy the `instagram_business_account.id` (a long number, e.g. `17841400000000000`).
5. **Make the token long-lived** (the Explorer token dies in ~1 hour):
   *Easiest:* Explorer → click the ⓘ next to the token → **Open in Access Token Tool** → **Extend Access
   Token** → copy the new token (valid ~60 days).
   *Best (never expires):* business.facebook.com → **Settings → Users → System users** → Add (role *Admin*) →
   **Add assets** → your Page + Instagram account → **Generate new token** for your app with the same
   permissions as above.
6. Put into `.env`:
   ```
   META_ACCESS_TOKEN=EAAG...long token...
   META_IG_USER_ID=17841400000000000
   ```

### Do **not** grant (not needed; they allow writing or private data)
`instagram_content_publish`, `instagram_manage_comments`, `instagram_manage_messages`,
`instagram_manage_insights` (only your own stats — later, for first-party data), `pages_manage_posts`,
`pages_manage_metadata`, `pages_messaging`, `ads_management`, `ads_read`, `email`, `user_*`.

### Hashtag search (optional, extra step)
Hashtag top / recent posts need the feature **"Instagram Public Content Access"**, which Meta grants through
**App Review** (App Dashboard → App Review → Permissions and Features → request *Instagram Public Content
Access*, explain "market research on public hashtag content for our restaurant", add a short screen recording).
Takes days to weeks. Without it, profiles + posts still work; only hashtag search is skipped.

### Limits to know
About 200 calls per hour per account (the connector stays below it). Only **Business / Creator** accounts can
be looked up; personal accounts are recorded as "not a business account".

---

## 2. Apify (Uber Eats store list)
1. Sign up at **apify.com** (Google login works).
2. For the full Berlin list choose **Starter ($29)** for one month (Billing → Plans) and cancel after the run;
   the free plan ($5 credit, 200 stores per run) is enough only for the test.
3. **Settings → API & Integrations** → copy the **Personal API token**.
4. `.env`:
   ```
   APIFY_TOKEN=apify_api_...
   ```
The connector stops itself at the `$10` cap set in `config/markets/berlin-food.yaml`.

---

## 3. Hugging Face (Foursquare Open Places)
1. Sign up at **huggingface.co**.
2. Open **huggingface.co/datasets/foursquare/fsq-os-places** → click **"Agree and access repository"**
   (fill in the short form; approval is usually immediate).
3. Avatar → **Settings → Access Tokens → Create new token** → type **Read** → name it `mip`.
4. `.env`:
   ```
   HF_TOKEN=hf_...
   ```

---

## 4. Kaggle (TripAdvisor European Restaurants, 2021)
1. Sign up at **kaggle.com** (phone verification may be asked).
2. Avatar → **Settings** → section **API** → **Create New Token** → a file `kaggle.json` downloads.
3. In Terminal:
   ```bash
   mkdir -p ~/.kaggle && mv ~/Downloads/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json
   ```
   (No `.env` line needed; Kaggle reads that file.)

---

## 5. DataForSEO (optional, paid)
1. Sign up at **dataforseo.com** → confirm email → **Billing**: deposit **$50** (minimum; does not expire,
   lasts years at our volume). A $1 free trial credit exists to test first.
2. Dashboard → **API Access**: the login is your account email, the **API password** is shown there
   (it is *not* your account password).
3. `.env`:
   ```
   DATAFORSEO_LOGIN=you@example.com
   DATAFORSEO_PASSWORD=api-password-from-dashboard
   ```

---

## 6. YouTube Data API v3 (free) — videos, Shorts, channels, comments

1. Go to https://console.cloud.google.com/ and create a project (e.g. `dhaka-kacchi-mip`). No billing needed.
2. **APIs & Services → Library** → search **YouTube Data API v3** → **Enable**.
3. **APIs & Services → Credentials → Create credentials → API key**.
4. Click the new key → **API restrictions → Restrict key → YouTube Data API v3** → Save.
5. Put it in `.env`: `YOUTUBE_API_KEY=...` (do not paste it in chat).
6. Test: `uv run mip healthcheck -m berlin-food -s youtube`, then `uv run mip fetch -m berlin-food -s youtube -w 2`.

Free quota: ~100 searches/day (the connector uses 90) + 10,000 units/day for video / channel / comment reads.
The first full pass of 229 search queries takes about 3 days; it resumes by itself.

## 7. Applications worth starting now (free, but reviewed by the platform)

| What | Where | Unlocks | Typical wait |
|---|---|---|---|
| **Meta Ad Library API** | Confirm your identity at facebook.com/ID, then add *Ad Library API* to your Meta app | Every ad (all topics) shown in Germany/EU with dates, creatives, reach by age / gender / region | 1–3 days |
| **Instagram Public Content Access + Business Discovery** (App Review) | developers.facebook.com → your app → App Review | Competitor posts with likes / comments; hashtag top + recent posts | 2–4 weeks |
| **Threads `threads_keyword_search`** (App Review) | Add the Threads use case to the same Meta app | Public Threads posts by keyword / topic tag | 2–4 weeks |
| **TikTok Commercial Content API** | developers.tiktok.com/products/commercial-content-api | Every TikTok ad shown in the EU, with reach and targeting | 2 days – 2 weeks |
| **Google Trends API (alpha)** | developers.google.com/search/apis/trends | Consistently scaled search interest per region, 5 years | allow-list |
| **Reddit Data API** (optional) | reddit.com/prefs/apps + Responsible Builder approval | Live comments / rising posts (the archive already covers posts) | 2–4 weeks; commercial use is paid |

## Already handled — nothing needed from you
OpenStreetMap, Overture, Zensus 2022, LOR, Chrome UX ranks, holidays, DWD weather, Wikidata, Wolt, Lieferando,
Google Maps, TikTok, restaurant websites. Dhaka Kacchi's own data (orders, Search Console, Business Profile)
comes later from `dhaka-kacchi-connect` / `dhaka_kacchi_ai_harness`, as agreed.
