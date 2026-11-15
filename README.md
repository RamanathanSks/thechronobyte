# Daily tech, gaming and space news (Threads & Instagram)

A small, MIT-licensed automation covering AI/ML, video games, mobile phones,
RAM/CPU/GPU hardware and announced prices, major technology companies, space
programs and emerging technology. It checks original sources, generates a
preview, and supports the existing Threads and Instagram publishing pipeline.

**Strict source mode is enabled by default and in the scheduled workflow.**
It uses original publisher wording instead of AI rewrites, including when a
Groq key exists. No new paid service or news API key is required.

## Files

| File | Purpose |
| --- | --- |
| `post_daily.py` | Select fresh news, format a Threads post, preview or publish once |
| `news_sources.py` | Approved publishers, feed/newsroom readers, article checks and price evidence |
| `SOURCES.md` | All 29 official source endpoints, coverage and validation notes |
| `card_generator.py` | Instagram news carousel rendering |
| `requirements.txt` | Direct dependencies: `requests`, `pillow` |
| `.github/workflows/daily_post.yml` | Daily schedule (`03:17 UTC / 08:47 IST`) and manual trigger |
| `tests/` | Source verification, pricing, publishing and rendering regression tests |
| `LICENSE` | MIT license for this project's code |

## Sources and accuracy

Every run checks **29 official source endpoints**, including Figma,
Anthropic/Claude, JPMorganChase's technology blog, Notion, Amazon, Comcast, AWS,
Google DeepMind, GitHub, Cloudflare, Cisco, Salesforce, Stripe, Mozilla and IBM,
alongside the existing AI, hardware, gaming, phone and space sources. See
[SOURCES.md](SOURCES.md) for the complete linked catalog and availability notes.

Twenty-four endpoints provide RSS/Atom; five use official newsrooms or a sitemap.
No news API key is needed. Six workers fetch sources concurrently. Each newsroom
inspects at most six article links, then reads the original page's headline and
publication metadata. Downloaded newsroom articles are reused for verification.
Listing dates and sitemap modification times only order discovery; they never
establish publication dates. An unavailable publisher is logged and skipped.

Relevant title terms and each dedicated source's coverage determine eligibility.
Amazon, Comcast and IBM additionally require a technology-related headline;
JPMorganChase is restricted to its technology blog. Financial-results stories and
headlines explicitly described as rumors/leaks are excluded. This is a curated
set of primary sources, not complete coverage of every company or space agency.
New publishers must be explicitly added with an approved domain.

The default freshness window is **72 hours** (`MAX_NEWS_AGE_HOURS`: 1–168).
Selection uses newest eligible publication, not an unsupported claim that a
story is socially trending. There is no guaranteed rotation through every topic.

Before a story can be used:

1. The feed/newsroom and article must use HTTPS on their configured hostname.
   DeepMind's explicitly approved migration to Google's `blog.google` is the
   sole additional host exception. Credentials in URLs, unusual ports and
   unapproved redirects are rejected before following them. Downloads and
   request timeouts are bounded.
2. The original HTML page must confirm the feed headline through an H1 or
   publisher headline metadata. A canonical URL, when present, must identify
   that same article on the approved domain.
3. Publication dates must be within the freshness window, with no future dates.
   Original article metadata takes precedence over feed dates. Atom update times
   alone are insufficient: they require original publication metadata. A publisher
   supplying only a calendar date is recorded with day precision; midnight UTC
   is used conservatively for freshness and sorting, not asserted as a release time.
4. Detail text comes from the retrieved article's main/article paragraphs.
   RSS-only summaries are discarded after verification; missing details stay
   missing. Posts attribute the publisher and include the publication date.
5. At most five unposted candidates are checked per run. The passing story with
   the newest confirmed publication date wins; a feed update cannot outrank a
   newer original publication. If none passes, nothing is published.

The GitHub Actions run summary records the source URL, check time, publication
date basis and a SHA-256 fingerprint of the fetched HTML. This is evidence of
what page was checked, **not** a publisher signature or proof of factual truth.
These automatic checks establish provenance and consistency. Company performance
claims remain company claims; they are not independently replicated benchmarks.

### RAM, GPU and phone price information

Prices may come from **any market**, always in their original currency. A
price-focused story must include an explicit amount, currency and market in the
original article paragraph. Supported labels currently cover USD/United States,
INR/India, GBP/United Kingdom, CAD/Canada, AUD/Australia, JPY/Japan and EUR for
explicitly named Germany, France, Eurozone or European Union. Unknown or ambiguous
contexts are skipped, rather than guessed. Amounts are not converted.

Price paragraphs are labeled with market, currency, publication date and
**publisher announcement—not a live retailer quote**. Unscoped price paragraphs
are excluded even from otherwise valid product stories. This project covers
verified official price announcements; it is **not a live RAM/GPU retail-price
tracker** and does not infer current stock, taxes, discounts, price movement or
street prices from MSRP. Historical comparisons need a separate dated price
dataset and are not synthesized by the model.

### Source text and optional rewriting

`STRICT_SOURCE_MODE=true` is the default. It bypasses Groq for both Threads and
Instagram, retaining publisher text and neutral attribution. Long text may be
shortened to fit; follow the source link for the full context. Captions, cards,
topic tags and hashtags now cover gaming, mobile, prices, hardware, technology
companies and space as well as AI.

The previous optional Groq rewriting code remains for local experimentation
with `STRICT_SOURCE_MODE=false`. That mode can introduce unsupported statements
and does not meet the strict source-text requirement. The workflow explicitly
keeps strict mode enabled. No model is used as a fact-checker.

Posts stay within Threads' **500-character** limit per post (checked
conservatively against UTF-8 byte length) and use Threads' native features:
- **Unique story daily:** Checks recent posts on your Threads profile
  (`GET /{user_id}/threads`) and skips already-posted headlines so quiet days
  pick the next-newest story instead of repeating.
- **Deep article context + 2-part thread chains:** Uses confirmed original article
  paragraphs. When extra detail is
  available, it publishes a crisp main post followed by a self-reply (`reply_to_id`)
  ending with a topic-tailored discussion question (or optionally crafts the
  thread via Groq only in the optional non-strict mode).
- **Rich link preview card:** Attaches the official article URL via Threads'
  `link_attachment` parameter rather than pasting a raw URL into the text.
- **Threads Topic tag (`topic_tag`):** Automatically attaches a relevant topic
  badge such as `Video Games`, `Mobile Phones`, `Component Prices`, `Space Programs`,
  `Tech Industry`, `Computer Hardware`, `OpenAI` or `Machine Learning`.
- **Reply control (`THREADS_REPLY_CONTROL`):** Defaults to `everyone`
  (supports `everyone`, `accounts_you_follow`, `mentioned_only`, `followers_only`).

## 1. Create a Meta Threads App (Free, no App Review for your own account)

1. Sign in to [Meta for Developers](https://developers.facebook.com/) and create an app.
2. Select the **Access the Threads API** use case.
3. Under **Use cases → Customize**, enable **`threads_basic`** and **`threads_content_publish`**, and set a **Redirect Callback URL** (e.g. `https://localhost/` or your repository URL).
4. Keep the app in **Development Mode** (no App Review needed for your own account):
   - Go to **App roles → Roles → Add People → Threads Testers** and add your Threads username.
   - Open your Threads account → **Settings → Website Permissions → Invites** and **accept** the tester invite.
5. Generate your **Long-Lived Threads User Access Token** (valid for **60 days**) and copy your numeric **Threads User ID**.

> **60-day token renewal:** Long-lived Threads tokens expire after 60 days. Before expiration (at least 24h after creation), run locally:
> ```sh
> THREADS_ACCESS_TOKEN="your_current_token" python post_daily.py --refresh-token
> ```
> Then update the `THREADS_ACCESS_TOKEN` secret on GitHub.

## 2. Add GitHub Repository Secrets & Enable Live Posting

Create a **public** GitHub repository (free standard Ubuntu runners), push these files to `main`, and open **Settings → Secrets and variables → Actions**:

### Secrets (New repository secret)

| Secret | Value | Required for |
| --- | --- | --- |
| `THREADS_USER_ID` | Your numeric Threads user ID (or `me`) | Live posting |
| `THREADS_ACCESS_TOKEN` | Long-lived Threads OAuth 2.0 user token | Live posting |
| `GROQ_API_KEY` | Optional Groq API key (`llama-3.1-8b-instant`) | Experimental rewriting only; unused in strict mode |

### Testing and Enabling Daily Live Runs

1. Leave live-posting variables unset first and run **Actions → Daily tech gaming and space news (Threads & Instagram) → Run workflow** with **dry_run** checked. Inspect the source verification section in the run summary before enabling publishing.
2. When ready for automated daily posts, go to **Settings → Secrets and variables → Actions → Variables** and add:
   - `ENABLE_THREADS_POSTING` = `true`
3. Run a manual dispatch with **dry_run** unchecked to verify your first live Threads post.

| `ENABLE_THREADS_POSTING` | Trigger | Manual `dry_run` | Result |
| --- | --- | --- | --- |
| Unset or anything except `true` | Either | Either | Preview (`DRY RUN`) |
| `true` | Schedule | Not applicable | Live Threads post |
| `true` | Manual | Checked (default) | Preview (`DRY RUN`) |
| `true` | Manual | Unchecked | Live Threads post |

## 3. Local preview and tests

```sh
python -m venv .venv
# PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python post_daily.py
```
