# Official news sources

The bot checks 29 endpoints: 24 RSS/Atom feeds and five official newsrooms or
sitemaps. All links below belong to the publisher. Configuration lives in
[`news_sources.py`](news_sources.py); source checks are described in
[`README.md`](README.md#sources-and-accuracy).

## AI, research and cloud

| Publisher | Official endpoint | Discovery | Coverage |
| --- | --- | --- | --- |
| OpenAI | [News](https://openai.com/news/rss.xml) | RSS | AI models, products and research |
| Anthropic | [Newsroom](https://www.anthropic.com/news) | HTML | Claude, AI products and company announcements |
| Google AI | [AI blog](https://blog.google/technology/ai/rss/) | RSS | Gemini, AI products and research |
| Google DeepMind | [Blog](https://deepmind.google/blog/rss.xml) | RSS | Models, research and AI systems |
| Microsoft Research | [Research](https://www.microsoft.com/en-us/research/feed/) | RSS | ML, AI and computing research |
| AWS | [AWS News Blog](https://aws.amazon.com/blogs/aws/feed/) | RSS | Cloud services and infrastructure |
| AWS Machine Learning | [Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/feed/) | RSS | AI services, models and ML engineering |
| IBM | [Newsroom](https://newsroom.ibm.com/announcements?pagetemplate=rss) | RSS | Technology, AI, enterprise and quantum computing |

## Devices, hardware, gaming and space

| Publisher | Official endpoint | Discovery | Coverage |
| --- | --- | --- | --- |
| NVIDIA | [Blog](https://blogs.nvidia.com/feed/) | RSS | GPUs, AI and accelerated computing |
| AMD | [Press releases](https://ir.amd.com/news-events/press-releases/rss) | RSS | CPUs, GPUs and AI hardware |
| Apple | [Newsroom](https://www.apple.com/newsroom/rss-feed.rss) | Atom | iPhone, Apple devices and company announcements |
| Samsung | [Global Newsroom](https://news.samsung.com/global/feed) | RSS | Phones, memory, devices and technology |
| Google Devices | [Pixel blog](https://blog.google/products-and-platforms/devices/pixel/rss/) | RSS | Pixel devices and software |
| Xbox | [Xbox Wire](https://news.xbox.com/en-us/feed/) | RSS | Games, consoles and gaming services |
| PlayStation | [Blog](https://blog.playstation.com/feed/) | RSS | Games, consoles and releases |
| NASA | [News](https://www.nasa.gov/news-release/feed/) | RSS | Missions, space science and technology |

## Technology companies, design, developer tools and connectivity

| Publisher | Official endpoint | Discovery | Coverage |
| --- | --- | --- | --- |
| Figma | [Blog](https://www.figma.com/blog/) | HTML | Design tools, product releases and AI workflows |
| Notion | [Blog](https://www.notion.com/blog) | HTML | Productivity, collaboration and Notion AI |
| Amazon | [About Amazon](https://www.aboutamazon.com/rss/feed.rss) | RSS | Technology, devices, AI and cloud announcements |
| Meta | [Newsroom](https://about.fb.com/news/feed/) | RSS | AI, social platforms and devices |
| Microsoft | [Company blog](https://blogs.microsoft.com/feed/) | RSS | Microsoft products and company updates |
| GitHub | [Blog](https://github.blog/feed/) | RSS | Developer tools, Copilot and software engineering |
| Cloudflare | [Blog](https://blog.cloudflare.com/rss/) | RSS | Internet infrastructure, security and developer tools |
| Cisco | [Blogs](https://blogs.cisco.com/feed) | RSS | Networking, connectivity and security |
| Salesforce | [News](https://www.salesforce.com/news/feed/?bc=DB) | RSS | Business software, AI and productivity |
| Mozilla | [Blog](https://blog.mozilla.org/en/feed/) | RSS | Firefox, browsers and web technology |
| Comcast | [Corporate press](https://corporate.comcast.com/press) | HTML | Connectivity, broadband and technology; availability limited below |

## Financial technology

| Publisher | Official endpoint | Discovery | Coverage |
| --- | --- | --- | --- |
| JPMorganChase | [Official sitemap](https://www.jpmorganchase.com/sitemap.xml) | XML sitemap | Only articles under `/about/technology/blog/`: AI, computing and technology |
| Stripe | [Blog](https://stripe.com/blog/feed.rss) | RSS | Payments, financial technology and developer products |

## Selection and availability

The newest eligible, unposted story that passes article checks is selected from
up to five candidates. Sources do not receive a guaranteed rotation. Freshness
defaults to 72 hours; a publisher with only older articles will not be used that
day. Broad Amazon, Comcast and IBM feeds also require a technology keyword.
JPMorganChase's sitemap is scoped to its technology blog, excluding investor
relations and general banking pages. Figma discovery requires dated article
links to avoid category navigation. Newsroom pages without original publication
metadata are skipped.

Live validation on **2026-11-15 UTC** retrieved usable entries from **28 of 29
endpoints**. Sample original-article checks passed for 26 sources, including
Figma, Anthropic, Notion, JPMorganChase and Amazon. Apple's calendar-only date
format and DeepMind's redirect to Google's official blog were verified separately.
Sample checks establish compatibility, not freshness of every article or future
availability.

- **Comcast:** its official newsroom timed out during validation. It is configured
  but skipped while unavailable; it has not passed a live article check. An
  accessible page with matching metadata is required before it can supply a post.
- **OpenAI:** the feed was readable, but the sampled article returned HTTP 403.
  That candidate was rejected.
- **Samsung:** the feed was readable, but the sampled article timed out in this
  audit. That candidate was rejected. A previous article check had succeeded.

Every run repeats the checks. Access failures do not fall back to search snippets,
unofficial mirrors, generated facts or unchecked feed summaries. Strict source
mode retains publisher wording and attribution. Primary sources establish who
made a statement; company claims are not independently fact-checked. Announced
prices require an explicit market, original currency and date and are never
presented as current retailer quotes.
