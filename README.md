# Daily AI, CPU, GPU and ML news (Meta Threads)

A small, MIT-licensed Python automation that finds the newest relevant AI,
CPU, GPU or machine-learning headline from official news feeds, optionally
shortens it with Groq, previews it, and publishes to **Meta Threads** for free
(`$0`) using the official Threads Graph API.

## Files

| File | Purpose |
| --- | --- |
| `post_daily.py` | Select fresh news, format a Threads post, preview or publish once |
| `requirements.txt` | Direct dependency: `requests` |
| `.github/workflows/daily_post.yml` | Daily schedule (`03:17 UTC / 08:47 IST`) and manual trigger |
| `tests/test_post_daily.py` | Offline unit tests using mocked HTTP responses |
| `LICENSE` | MIT license for this project's code |

## Sources and accuracy

| Publisher | Official feed | Coverage |
| --- | --- | --- |
| OpenAI | [News RSS](https://openai.com/news/rss.xml) | AI models, products and research |
| NVIDIA | [Blog RSS](https://blogs.nvidia.com/feed/) | GPUs, AI and accelerated computing |
| Google AI | [AI RSS](https://blog.google/technology/ai/rss/) | Gemini, AI products and research |
| AMD | [Press release RSS](https://ir.amd.com/news-events/press-releases/rss) | CPUs, GPUs and AI hardware |
| Microsoft Research | [Research RSS](https://www.microsoft.com/en-us/research/feed/) | ML and AI research |

Every run fetches all five feeds without an API key, filters headlines for
AI/ML and CPU/GPU terms, excludes financial-results headlines, and selects the
newest eligible publication. The default freshness window is **72 hours** (set
`MAX_NEWS_AGE_HOURS` between `1` and `168`). If nothing qualifies, the run skips
successfully.

Posts stay within Threads' **500-character** limit (checked conservatively
against UTF-8 byte length) and use Threads' native features:
- **Readable post text (no raw URL clutter):** Includes `Source | YYYY-MM-DD`,
  the headline, and the article summary extracted from the RSS `<description>` /
  `<content:encoded>` (or optionally refined via Groq).
- **Rich link preview card:** Attaches the official article URL via Threads'
  `link_attachment` parameter rather than pasting a raw URL into the text.
- **Threads Topic tag (`topic_tag`):** Automatically attaches a relevant topic
  badge (such as `OpenAI`, `Google Gemini`, `AI Hardware`, `Machine Learning`,
  or `Artificial Intelligence`).
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
| `GROQ_API_KEY` | Optional Groq API key (`llama-3.1-8b-instant`) | Optional rewriting |

### Testing and Enabling Daily Live Runs

1. Leave `ENABLE_THREADS_POSTING` unset first and run **Actions → Daily AI and hardware news (Threads) → Run workflow** with **dry_run** checked to confirm a `DRY RUN` preview succeeds.
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
